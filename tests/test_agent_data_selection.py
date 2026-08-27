from pathlib import Path

from gis_mapping_agent.agent.thinking import ThinkingGISMappingAgent, _boundary_extent_inputs
from gis_mapping_agent.data_sources.planner import plan_local_sources


class CaptureTool:
    name = "add_layer"
    args_schema = None

    def __init__(self):
        self.received = None

    def invoke(self, tool_input):
        self.received = tool_input
        return {"success": True}


def test_verified_boundary_is_reused_for_extent_calculation():
    data_dir, data_files = _boundary_extent_inputs("data_cache/boundaries/city.geojson")

    assert data_dir.endswith("data_cache\\boundaries") or data_dir.endswith("data_cache/boundaries")
    assert data_files == ["city.geojson"]


def test_location_default_file_overrides_model_hallucinated_path():
    tool = CaptureTool()
    agent = object.__new__(ThinkingGISMappingAgent)
    agent.tool_dict = {"add_layer": tool}
    agent.session_id = None
    agent._default_data_file_path = Path("data/data8/Beijing.shp")
    agent._explicit_data_files = False

    agent._execute_tool("add_layer", {"name": "北京", "data_path": "data/北京市.shp"})

    assert tool.received["data_path"] == "data/data8/Beijing.shp"


def test_semantic_layer_plan_overrides_one_default_file_for_each_requested_role():
    tool = CaptureTool()
    agent = object.__new__(ThinkingGISMappingAgent)
    agent.tool_dict = {"add_layer": tool}
    agent.session_id = None
    agent._default_data_file_path = Path("data/data1/Guangdong.shp")
    agent._explicit_data_files = False
    agent._semantic_data_plan = plan_local_sources(
        "绘制广东省的地图，要标定出广东省下的所有城市以及道路河流"
    )

    agent._execute_tool("add_layer", {"name": "道路", "data_path": "data/data1/Guangdong.shp"})
    assert tool.received["data_path"] == "data/data1/Highway.shp"

    result = agent._execute_tool("add_layer", {"name": "河流", "data_path": "data/data1/Guangdong.shp"})
    assert "没有经过校验的数据源" in result


def test_semantic_layer_plan_enables_all_city_labels_on_boundary_layer():
    tool = CaptureTool()
    agent = object.__new__(ThinkingGISMappingAgent)
    agent.tool_dict = {"add_layer": tool}
    agent.session_id = None
    agent._default_data_file_path = Path("data/data1/Guangdong.shp")
    agent._explicit_data_files = False
    agent._semantic_data_plan = plan_local_sources(
        "绘制广东省的地图，要标定出广东省下的所有城市以及道路河流"
    )

    agent._execute_tool(
        "add_layer",
        {"name": "广东省", "data_path": "data/data1/Guangdong.shp", "style": {"color": "blue"}},
    )

    assert tool.received["style"]["label_column"] == "name"


def test_semantic_layer_plan_assigns_distinguishable_visual_defaults():
    tool = CaptureTool()
    agent = object.__new__(ThinkingGISMappingAgent)
    agent.tool_dict = {"add_layer": tool}
    agent.session_id = None
    agent._default_data_file_path = Path("data/data1/Guangdong.shp")
    agent._explicit_data_files = False
    agent._semantic_data_plan = plan_local_sources(
        "绘制广东省的地图，要标定出广东省下的所有城市以及道路"
    )

    agent._execute_tool("add_layer", {"name": "道路"})

    assert tool.received["style"]["color"] == "#D97706"
    assert tool.received["style"]["linewidth"] == 1.4


def test_missing_local_roads_fall_back_to_remote_source(monkeypatch):
    agent = object.__new__(ThinkingGISMappingAgent)
    plan = plan_local_sources("绘制北京的地图，要显示主要的道路")

    monkeypatch.setattr(
        "gis_mapping_agent.agent.thinking.fetch_remote_roads",
        lambda place, bbox: Path("data_cache/remote_roads/beijing.geojson"),
    )

    updated = agent._add_remote_road_source("绘制北京的地图，要显示主要的道路", plan)

    assert updated.road_path == str(Path("data_cache/remote_roads/beijing.geojson"))
    assert not any("道路" in issue for issue in updated.issues)


def test_first_creation_poi_request_is_planned_as_remote_source(monkeypatch):
    agent = object.__new__(ThinkingGISMappingAgent)
    plan = plan_local_sources(
        "标注秦皇岛市的小学",
        boundary_path="data_cache/remote_boundaries/qhd.geojson",
    )
    monkeypatch.setattr(
        "geopandas.read_file",
        lambda _path: type("Boundary", (), {"total_bounds": [119.2, 39.7, 119.8, 40.1]})(),
        raising=False,
    )
    monkeypatch.setattr(
        "gis_mapping_agent.agent.thinking.fetch_remote_pois",
        lambda place, bbox, category: Path("data_cache/remote_pois/qhd-primary.geojson"),
        raising=False,
    )

    planned = agent._add_remote_poi_source("标注秦皇岛市的小学", plan)

    assert planned.poi_path == "data_cache/remote_pois/qhd-primary.geojson"
    assert planned.poi_category == "primary_schools"
    assert planned.path_for_layer("秦皇岛市小学") == planned.poi_path


def test_named_poi_uses_single_geocoded_point_not_batch_bbox_query(monkeypatch):
    agent = object.__new__(ThinkingGISMappingAgent)
    plan = plan_local_sources(
        "标注清华大学的位置",
        boundary_path="data_cache/remote_boundaries/tsinghua.geojson",
    )
    monkeypatch.setattr(
        "geopandas.read_file",
        lambda _path: type("Boundary", (), {"total_bounds": [116.3, 39.9, 116.4, 40.0]})(),
        raising=False,
    )
    calls = []
    monkeypatch.setattr(
        "gis_mapping_agent.agent.thinking.fetch_remote_named_poi",
        lambda place, category: calls.append((place, category)) or Path("data_cache/remote_pois/named.geojson"),
    )
    monkeypatch.setattr(
        "gis_mapping_agent.agent.thinking.fetch_remote_pois",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("named POI must not use batch query")),
    )

    planned = agent._add_remote_poi_source("标注清华大学的位置", plan)

    assert planned.poi_path.endswith("named.geojson")
    assert calls == [("清华大学", "universities")]


def test_local_registered_poi_is_selected_before_remote_fallback():
    class Catalog:
        def scan(self):
            return [
                type(
                    "Descriptor",
                    (),
                    {
                        "name": "学校点位",
                        "aliases": [],
                        "role": "primary_school",
                        "source_type": "local",
                        "local_path": "poi/schools.geojson",
                        "geometry_type": "Point",
                        "bbox": [120, 30, 121, 31],
                        "feature_count": 4,
                        "metadata": {},
                    },
                )()
            ]

    plan = plan_local_sources(
        "标注甲市的小学",
        catalog=Catalog(),
        location_bbox=[120, 30, 121, 31],
    )

    assert plan.poi_path == "data/poi/schools.geojson"
    assert plan.poi_category == "primary_schools"


def test_local_line_sources_are_scoped_to_resolved_location_not_boundary_bbox():
    class Catalog:
        def scan(self):
            return [
                type(
                    "Descriptor",
                    (),
                    {
                        "name": "Highway",
                        "aliases": [],
                        "role": "road",
                        "source_type": "local",
                        "local_path": "road/province.geojson",
                        "geometry_type": "LineString",
                        "bbox": [100, 20, 130, 45],
                        "feature_count": 10,
                        "metadata": {},
                    },
                )()
            ]

    plan = plan_local_sources(
        "绘制甲市道路",
        catalog=Catalog(),
        boundary_path="data/boundary/province.geojson",
        location_bbox=[120, 30, 121, 31],
    )

    assert plan.road_path == "data/road/province.geojson"
