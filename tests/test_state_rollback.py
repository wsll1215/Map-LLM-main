from gis_mapping_agent.models.schemas import GeometryType, LayerConfig, MapConfig, MapState, SessionInfo
from gis_mapping_agent.specs import AdjustmentPatch, PatchOperation
from gis_mapping_agent.adjustment import ModificationEngine
from gis_mapping_agent.state import MapStateManager


def test_rollback_to_previous_state(tmp_path):
    manager = MapStateManager(str(tmp_path / "states.db"))
    state = MapState(
        config=MapConfig(map_id="m1", title="old", extent=[0, 0, 1, 1]),
        session_info=SessionInfo(session_id="s1"),
        layers=[LayerConfig(layer_id="l1", name="roads", geometry_type=GeometryType.LINE, data_source="roads.shp")],
    )
    assert manager.save_state(state)

    changed, _ = ModificationEngine().apply_modifications(
        state,
        AdjustmentPatch(operations=[PatchOperation(action="toggle_layer_visibility", target="roads", parameters={"visible": False})]),
        "hide roads",
    )
    assert manager.save_state(changed)
    assert manager.load_state("s1").layers[0].visible is False

    rolled_back = manager.rollback_to_previous("s1")
    assert rolled_back is not None
    assert rolled_back.get_current_version() == 1
    assert rolled_back.layers[0].visible is True
    assert manager.load_state("s1").get_current_version() == 1
