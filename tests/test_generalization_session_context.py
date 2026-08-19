from gis_mapping_agent.models.schemas import MapConfig, MapState, SessionInfo
from gis_mapping_agent.state import (
    clear_session_context,
    get_generalization_context,
    get_generalization_state,
    save_map_state_context,
    save_generalization_context,
)
from gis_mapping_agent.tools.generalization_tools import GeneralizeRoadNetworkTool


def _state(session_id: str, keep_ratio: float) -> MapState:
    return MapState(
        config=MapConfig(map_id=session_id, title=session_id, extent=[0, 0, 1, 1]),
        session_info=SessionInfo(session_id=session_id),
        is_generalization_task=True,
        generalization_params={"algorithm": "stroke", "keep_ratio": keep_ratio},
        generalization_result={"keep_ratio": keep_ratio},
    )


def test_explicit_session_context_prevents_generalization_state_bleed():
    clear_session_context("s1")
    clear_session_context("s2")

    save_generalization_context("s1", map_state=_state("s1", 0.2), generalization_result={"keep_ratio": 0.2})
    save_generalization_context("s2", map_state=_state("s2", 0.8), generalization_result={"keep_ratio": 0.8})

    _, state1, result1 = get_generalization_state("s1")
    _, state2, result2 = get_generalization_state("s2")

    assert state1.get_session_id() == "s1"
    assert result1["keep_ratio"] == 0.2
    assert state2.get_session_id() == "s2"
    assert result2["keep_ratio"] == 0.8


def test_generalization_context_ignores_plain_map_state():
    plain = MapState(
        config=MapConfig(map_id="plain", title="plain", extent=[0, 0, 1, 1]),
        session_info=SessionInfo(session_id="plain-session"),
    )
    clear_session_context("plain-session")
    save_map_state_context("plain-session", plain)

    assert get_generalization_context("plain-session", load_persisted=False) is None


def test_old_langchain_tool_import_still_exports_tools():
    assert GeneralizeRoadNetworkTool().name == "generalize_road_network"
