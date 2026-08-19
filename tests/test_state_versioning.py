from gis_mapping_agent.models.schemas import GeometryType, LayerConfig, MapConfig, MapState, SessionInfo
from gis_mapping_agent.specs import AdjustmentPatch, PatchOperation
from gis_mapping_agent.adjustment import ModificationEngine
from gis_mapping_agent.state import MapStateManager


def test_state_versioning_records_patch_and_diff(tmp_path):
    manager = MapStateManager(str(tmp_path / "states.db"))
    state = MapState(
        config=MapConfig(map_id="m1", title="old", extent=[0, 0, 1, 1]),
        session_info=SessionInfo(session_id="s1"),
        layers=[LayerConfig(layer_id="l1", name="roads", geometry_type=GeometryType.LINE, data_source="roads.shp")],
    )
    assert manager.save_state(state)

    result = ModificationEngine().apply_modifications(
        state,
        AdjustmentPatch(operations=[PatchOperation(action="update_map_config", target="title", parameters={"title": "new"})]),
        "rename",
    )
    changed, _ = result
    changed.output_path = "outputs/new.png"
    assert manager.save_state(changed)

    versions = manager.list_recent_versions("s1", limit=2)
    assert [item["version"] for item in versions] == [1, 2]
    assert '"user_request": "rename"' in versions[-1]["description"]
    assert '"patch"' in versions[-1]["description"]
    assert '"diff"' in versions[-1]["description"]
    assert manager.load_state("s1").output_path == "outputs/new.png"
