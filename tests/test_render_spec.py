import geopandas as gpd
import matplotlib.pyplot as plt
import pandas as pd
from shapely.geometry import Polygon
from types import SimpleNamespace

from gis_mapping_agent.rendering.classification import build_render_spec
from mapping.realtime import _layer_payload
from gis_mapping_agent.data_sources.metadata import source_metadata_from_path
from gis_mapping_agent.models.schemas import MapConfig, MapState, SessionInfo
from gis_mapping_agent.tools.unified_mapping_tools import UnifiedMappingTools


def _polygons(values):
    return gpd.GeoDataFrame(
        {"value": values, "category": ["a", "b", "a", "c", "b"]},
        geometry=[
            Polygon([(index, 0), (index + 1, 0), (index + 1, 1), (index, 1)])
            for index in range(len(values))
        ],
        crs="EPSG:4326",
    )


def test_quantile_render_spec_contains_stable_breaks_labels_and_colors():
    spec = build_render_spec(_polygons([1, 2, 3, 4, 5]), "value", "quantile", 3)

    assert spec["enabled"] is True
    assert spec["attribute"] == "value"
    assert spec["method"] == "quantile"
    assert spec["classes"] == 3
    assert len(spec["breaks"]) == 4
    assert len(spec["labels"]) == 3
    assert len(spec["colors"]) == 3
    assert spec["no_data_color"]


def test_equal_interval_and_natural_breaks_produce_monotonic_breaks():
    data = _polygons([1, 2, 10, 11, 20])

    for method in ("equal_interval", "natural_breaks"):
        spec = build_render_spec(data, "value", method, 3)
        assert spec["method"] == method
        assert spec["breaks"] == sorted(spec["breaks"])
        assert len(spec["breaks"]) >= 2


def test_categorical_render_spec_maps_values_to_stable_colors():
    spec = build_render_spec(_polygons([1, 2, 3, 4, 5]), "category", "quantile", 5)

    assert spec["kind"] == "categorical"
    assert spec["values"] == ["a", "b", "c"]
    assert len(spec["colors"]) == 3
    assert spec["value_colors"]["a"] == spec["value_colors"]["a"]


def test_missing_or_non_numeric_attribute_returns_structured_fallback():
    missing = build_render_spec(_polygons([1, 2, 3, 4, 5]), "unknown", "quantile", 5)
    non_numeric = build_render_spec(
        gpd.GeoDataFrame(
            {"value": [None, None], "geometry": [None, None]},
            geometry="geometry",
            crs="EPSG:4326",
        ),
        "value",
        "quantile",
        5,
    )

    assert missing["enabled"] is False
    assert missing["warning_code"] == "attribute_not_found"
    assert non_numeric["enabled"] is False
    assert non_numeric["warning_code"] == "no_numeric_values"


def test_layer_payload_exposes_the_shared_render_spec():
    spec = build_render_spec(_polygons([1, 2, 3, 4, 5]), "value", "equal_interval", 3)
    layer = SimpleNamespace(
        layer_id="regions",
        name="regions",
        geometry_type="polygon",
        visible=True,
        z_order=1,
        data_source="data/regions.geojson",
        data_hash="hash",
        feature_count=5,
        extent=[0, 0, 5, 1],
        render_mode="geojson",
        data_url=None,
        style=SimpleNamespace(model_dump=lambda: {"attribute_column": "value"}),
        render_spec=spec,
    )

    assert _layer_payload(layer)["render_spec"] == spec


def test_layer_payload_exposes_source_metadata_and_render_observability():
    layer = SimpleNamespace(
        layer_id="remote-roads",
        name="远程道路",
        geometry_type="line",
        visible=True,
        z_order=2,
        data_source="data_cache/remote_roads/beijing.geojson",
        data_hash="hash",
        feature_count=12,
        extent=[115.4, 39.4, 117.4, 41.1],
        render_mode="geojson",
        data_url=None,
        render_spec=None,
        data_source_meta={
            "source_type": "remote",
            "provider": "OpenStreetMap/Overpass",
            "source_url": "https://overpass-api.de/api/interpreter",
            "attribution": "© OpenStreetMap contributors",
            "cache_path": "data_cache/remote_roads/beijing.geojson",
            "status": "available",
        },
        style=SimpleNamespace(model_dump=lambda: {"color": "#123456"}),
    )

    payload = _layer_payload(layer)

    assert payload["data_source_meta"]["source_type"] == "remote"
    assert payload["data_source_meta"]["provider"] == "OpenStreetMap/Overpass"
    assert payload["feature_count"] == 12
    assert payload["render_mode"] == "geojson"


def test_source_metadata_normalizes_non_json_runtime_values():
    payload = source_metadata_from_path(
        "data_cache/remote_roads/beijing.geojson",
        {"cache_path": __import__("pathlib").Path("cache.geojson"), "attempt": __import__("numpy").int64(2)},
    )

    assert payload["cache_path"] == "cache.geojson"
    assert payload["attempt"] == 2


def test_annotations_without_positions_are_stacked_instead_of_overlapping():
    tools = UnifiedMappingTools()
    tools.current_map_state = MapState(
        config=MapConfig(map_id="annotation-map", extent=[0, 0, 10, 10]),
        session_info=SessionInfo(session_id="annotation-session"),
    )
    tools.figure, tools.ax = plt.subplots()

    try:
        for index in range(3):
            result = tools.add_annotation({"text": f"来源说明 {index}: https://example.com/data"})
            assert result["success"] is True

        positions = [annotation.position for annotation in tools.current_map_state.annotations]
        assert len({tuple(position) for position in positions}) == 3
        assert [position[1] for position in positions] == sorted(position[1] for position in positions)
    finally:
        plt.close(tools.figure)
