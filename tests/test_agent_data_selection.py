from pathlib import Path

from gis_mapping_agent.agent.thinking import ThinkingGISMappingAgent
from gis_mapping_agent.data_sources.planner import plan_local_sources


class CaptureTool:
    name = "add_layer"
    args_schema = None

    def __init__(self):
        self.received = None

    def invoke(self, tool_input):
        self.received = tool_input
        return {"success": True}


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
