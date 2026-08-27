import json

from gis_mapping_agent.models.schemas import MapConfig, MapState, SessionInfo
from gis_mapping_agent.tools.base import BaseGISTool, GISToolInput
from gis_mapping_agent.tools.conversation_tools import ApplyModificationInput, ApplyModificationTool


class BrokenInput(GISToolInput):
    value: str


class BrokenTool(BaseGISTool):
    name: str = "broken_tool"
    description: str = "test tool"
    args_schema: type = BrokenInput

    def _execute_tool(self, input_data, run_manager=None):
        raise ValueError("必须提供text参数")


def make_state():
    return MapState(
        config=MapConfig(map_id="tool-result", title="test", extent=[0, 0, 1, 1]),
        session_info=SessionInfo(session_id="tool-session"),
    )


def test_base_tool_returns_machine_readable_recoverable_error():
    payload = json.loads(BrokenTool().invoke({"value": "bad"}))
    result = payload["tool_result"]

    assert result["success"] is False
    assert result["error_code"] == "validation_error"
    assert result["recoverable"] is True
    assert result["retryable"] is False
    assert result["next_action"] == "adjust_tool_arguments"


def test_apply_modification_returns_error_result_for_invalid_patch(monkeypatch):
    tool = ApplyModificationTool()
    tool.current_map_state = make_state()

    class FailingEngine:
        def analyze_modification_request(self, request, state):
            raise ValueError("必须提供text参数")

    monkeypatch.setattr(
        "gis_mapping_agent.tools.conversation_tools.get_modification_engine",
        lambda: FailingEngine(),
    )

    result = tool._execute_tool(ApplyModificationInput(modification_request="标注高校"))

    assert result.success is False
    assert result.error_code == "validation_error"
    assert result.data["next_action"] == "adjust_tool_arguments"
