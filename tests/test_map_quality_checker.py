from pathlib import Path

import geopandas as gpd
from shapely.geometry import LineString

from gis_mapping_agent.models.schemas import (
    AnnotationConfig,
    GeometryType,
    LayerConfig,
    LegendConfig,
    LegendItem,
    MapConfig,
    MapState,
)
from gis_mapping_agent.rendering.elements import MapQualityChecker


def test_quality_checker_reports_output_file_and_extent(tmp_path):
    output = tmp_path / "map.png"
    output.write_bytes(b"png")
    state = MapState(
        config=MapConfig(map_id="m1", title="ok", extent=[0, 0, 1, 1]),
        is_generalization_task=True,
    )

    result = MapQualityChecker().check(state, str(output))

    assert result["ok"] is True
    assert result["warnings"] == []


def test_quality_checker_rejects_missing_output_and_bad_extent():
    state = MapState(config=MapConfig(map_id="m1", title="bad", extent=[0, 0, 1, 1]))
    state.config.extent = [1, 0, 0, 1]

    result = MapQualityChecker().check(state, str(Path("missing.png")))

    assert result["ok"] is False
    assert "invalid_extent" in result["errors"]
    assert "output_missing" in result["errors"]


def test_quality_checker_reports_crs_and_empty_layers():
    state = MapState(
        config=MapConfig(map_id="m1", title="crs", extent=[0, 0, 1, 1]),
        layers=[
            LayerConfig(
                layer_id="l1",
                name="roads",
                geometry_type=GeometryType.LINE,
                data_source="roads.shp",
                gdf=gpd.GeoDataFrame(geometry=[LineString([(0, 0), (1, 1)])], crs="EPSG:3857"),
            ),
            LayerConfig(
                layer_id="l2",
                name="empty",
                geometry_type=GeometryType.LINE,
                data_source="empty.shp",
                gdf=gpd.GeoDataFrame(geometry=[], crs="EPSG:4326"),
            ),
        ],
    )

    warnings = MapQualityChecker().check(state)["warnings"]

    assert {"empty_layers": ["empty"]} in warnings
    assert any("mixed_crs" in warning for warning in warnings if isinstance(warning, dict))
    assert any("crs_mismatch" in warning for warning in warnings if isinstance(warning, dict))


def test_quality_checker_reports_legend_and_overlap_warnings():
    state = MapState(
        config=MapConfig(map_id="m1", title="overlap", extent=[0, 0, 1, 1]),
        layers=[
            LayerConfig(
                layer_id="l1",
                name="roads",
                geometry_type=GeometryType.LINE,
                data_source="roads.shp",
            )
        ],
        legend_items=[
            LegendItem(label="railway", type="line", style={}),
        ],
        legends=[
            LegendConfig(legend_id="legend1", title="legend", position="lower left"),
        ],
        scalebar={"position": [0.01, 0.01]},
        annotations=[
            AnnotationConfig(annotation_id="a1", text="A", position=[0.2, 0.2]),
            AnnotationConfig(annotation_id="a2", text="B", position=[0.21, 0.21]),
        ],
    )

    warnings = MapQualityChecker().check(state)["warnings"]

    assert any("legend_layer_mismatch" in warning for warning in warnings if isinstance(warning, dict))
    assert any("element_overlaps" in warning for warning in warnings if isinstance(warning, dict))
    assert any("label_overlaps" in warning for warning in warnings if isinstance(warning, dict))
