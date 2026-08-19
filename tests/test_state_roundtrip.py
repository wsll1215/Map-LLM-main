from gis_mapping_agent.models.schemas import GeometryType, LayerConfig, LayerStyle, MapConfig, MapState, SessionInfo
from gis_mapping_agent.state import MapStateManager


def test_generalization_state_roundtrip(tmp_path):
    manager = MapStateManager(str(tmp_path / "states.db"))
    state = MapState(
        config=MapConfig(map_id="map-1", title="test", extent=[0, 0, 1, 1]),
        session_info=SessionInfo(session_id="session-1"),
        is_generalization_task=True,
        generalization_algorithm="stroke",
        generalization_params={"algorithm": "stroke", "keep_ratio": 0.5},
        generalization_input_path="data/roads.shp",
        generalization_output_path="outputs/roads_generalized.shp",
        generalization_metrics={"output_count": 10},
        generalization_result_meta={"stroke_count": 3},
        generalization_result={"input_gdf": "large", "output_gdf": "large", "keep_ratio": 0.5},
    )

    assert manager.save_state(state)
    loaded = manager.load_state("session-1")

    assert loaded is not None
    assert loaded.generalization_algorithm == "stroke"
    assert loaded.generalization_params["keep_ratio"] == 0.5
    assert loaded.generalization_input_path == "data/roads.shp"
    assert loaded.generalization_output_path == "outputs/roads_generalized.shp"
    assert loaded.generalization_metrics["output_count"] == 10
    assert loaded.generalization_result_meta["stroke_count"] == 3
    assert loaded.generalization_result["input_gdf"] is None
    assert loaded.generalization_result["output_gdf"] is None


def test_layer_attribute_style_roundtrip(tmp_path):
    manager = MapStateManager(str(tmp_path / "states.db"))
    state = MapState(
        config=MapConfig(map_id="map-2", title="attribute map", extent=[0, 0, 1, 1]),
        session_info=SessionInfo(session_id="session-2"),
        layers=[
            LayerConfig(
                layer_id="wuhan",
                name="Wuhan",
                geometry_type=GeometryType.POLYGON,
                data_source="data/data5/Wuhan.shp",
                style=LayerStyle(attribute_column="地名", edgecolor="white", linewidth=0.8),
            )
        ],
    )

    assert manager.save_state(state)
    loaded = manager.load_state("session-2")

    assert loaded is not None
    assert loaded.layers[0].style.attribute_column == "地名"
    assert loaded.layers[0].style.edgecolor == "white"
