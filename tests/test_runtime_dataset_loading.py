from types import SimpleNamespace

import pytest


def test_bbox_geometry_is_explicitly_wgs84_for_postgis_queries():
    from mapping import dataset_reader

    bbox_geometry = dataset_reader._bbox_geometry((120, 30, 121, 31))

    assert bbox_geometry.srid == 4326


def test_add_layer_runtime_dataset_reads_postgis_reader_instead_of_file(monkeypatch):
    from gis_mapping_agent.tools.unified_mapping_tools import map_ops

    expected = SimpleNamespace(name="dataset-frame")
    monkeypatch.setattr(
        "mapping.dataset_reader.read_dataset_features",
        lambda dataset_id, bbox=None, limit=None: expected,
    )
    monkeypatch.setattr(
        map_ops.gpd,
        "read_file",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("runtime Dataset must not read the source file")
        ),
    )

    frame, source = map_ops._load_layer_data(
        {
            "data_path": "missing/roads.geojson",
            "data_source_meta": {"dataset_id": "road-1"},
        }
    )

    assert frame is expected
    assert source == "dataset://road-1"


def test_runtime_dataset_reader_receives_verified_scope_geometry(monkeypatch):
    from gis_mapping_agent.tools.unified_mapping_tools import map_ops

    calls = []
    expected = SimpleNamespace(name="scoped-frame")

    def reader(dataset_id, bbox=None, limit=None, clip_geometry=None):
        calls.append((dataset_id, bbox, limit, clip_geometry))
        return expected

    monkeypatch.setattr("mapping.dataset_reader.read_dataset_features", reader)

    frame, source = map_ops._load_layer_data(
        {
            "data_source_meta": {
                "dataset_id": "road-1",
                "scope_geometry": {"type": "Polygon", "coordinates": []},
            }
        }
    )

    assert frame is expected
    assert source == "dataset://road-1"
    assert calls[0][3]["type"] == "Polygon"


def test_add_layer_uses_runtime_loader_when_dataset_id_is_present(monkeypatch):
    import geopandas as gpd
    from shapely.geometry import Point
    from gis_mapping_agent.tools.unified_mapping_tools import UnifiedMappingTools
    from gis_mapping_agent.tools.unified_mapping_tools import map_ops

    frame = gpd.GeoDataFrame(
        {"name": ["road point"]}, geometry=[Point(120, 30)], crs="EPSG:4326"
    )
    monkeypatch.setattr(map_ops, "_load_layer_data", lambda _params: (frame, "dataset://road-1"))
    monkeypatch.setattr(
        map_ops.gpd,
        "read_file",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("add_layer must use the runtime loader")
        ),
    )
    tools = UnifiedMappingTools()
    assert tools.init_map({"title": "甲市", "extent": [119, 29, 121, 31]})["success"]

    result = tools.add_layer(
        {
            "name": "道路",
            "data_path": "missing/roads.geojson",
            "data_source_meta": {"dataset_id": "road-1", "source_type": "local"},
        }
    )

    assert result["success"] is True
    assert tools.current_map_state.layers[0].data_source == "dataset://road-1"


def test_add_layer_does_not_resolve_a_file_path_for_runtime_dataset(monkeypatch):
    import geopandas as gpd
    from shapely.geometry import Point
    from gis_mapping_agent.tools.unified_mapping_tools import UnifiedMappingTools
    from gis_mapping_agent.tools.unified_mapping_tools import map_ops

    frame = gpd.GeoDataFrame(
        {"name": ["road"]}, geometry=[Point(120, 30)], crs="EPSG:4326"
    )
    monkeypatch.setattr(map_ops, "_load_layer_data", lambda _params: (frame, "dataset://road-2"))

    class UnexpectedPath:
        def __init__(self, *_args, **_kwargs):
            raise AssertionError("runtime Dataset must not construct a source file path")

    monkeypatch.setattr(map_ops, "Path", UnexpectedPath)
    tools = UnifiedMappingTools()
    assert tools.init_map({"title": "甲市", "extent": [119, 29, 121, 31]})["success"]

    result = tools.add_layer(
        {
            "name": "道路",
            "data_source_meta": {"dataset_id": "road-2", "source_type": "local"},
        }
    )

    assert result["success"] is True
    assert tools.current_map_state.layers[0].data_source == "dataset://road-2"


def test_runtime_layer_loading_rejects_unregistered_file_path(monkeypatch, tmp_path):
    from gis_mapping_agent.tools.unified_mapping_tools import map_ops

    source = tmp_path / "roads.geojson"
    source.write_text(
        '{"type":"FeatureCollection","features":[]}',
        encoding="utf-8",
    )

    from mapping.dataset_reader import DatasetReadError

    with pytest.raises(DatasetReadError, match="dataset_id"):
        map_ops._load_layer_data({"data_path": str(source)})


def test_layer_distribution_reads_dataset_source_from_postgis(monkeypatch):
    import geopandas as gpd
    import matplotlib.pyplot as plt
    from shapely.geometry import Point

    from gis_mapping_agent.models.schemas import GeometryType, LayerConfig, MapConfig, MapState
    from gis_mapping_agent.tools.unified_mapping_tools.base import UnifiedMappingToolsBase

    frame = gpd.GeoDataFrame(
        {"name": ["road"]}, geometry=[Point(0.2, 0.3)], crs="EPSG:4326"
    )
    monkeypatch.setattr(
        "mapping.dataset_reader.read_dataset_features",
        lambda dataset_id, bbox=None, limit=None: frame,
    )
    monkeypatch.setattr(
        "geopandas.read_file",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("layer distribution must not read a source file")
        ),
    )

    figure, axes = plt.subplots()
    tools = object.__new__(UnifiedMappingToolsBase)
    tools.ax = axes
    tools.current_map_state = MapState(
        config=MapConfig(map_id="distribution", extent=[0, 0, 1, 1]),
        layers=[
            LayerConfig(
                layer_id="road-1",
                name="road",
                geometry_type=GeometryType.POINT,
                data_source="dataset://road-1",
                data_source_meta={"dataset_id": "road-1"},
            )
        ],
    )
    axes.set_xlim(0, 1)
    axes.set_ylim(0, 1)

    assert tools._analyze_layer_distribution() == [(0.2, 0.3, 0.2, 0.3)]
    plt.close(figure)
