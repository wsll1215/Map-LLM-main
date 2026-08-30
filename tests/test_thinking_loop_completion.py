from types import SimpleNamespace

from gis_mapping_agent.agent.thinking import ThinkingGISMappingAgent


def test_thinking_loop_does_not_claim_success_without_a_tool_call(monkeypatch):
    agent = ThinkingGISMappingAgent.__new__(ThinkingGISMappingAgent)
    agent.max_iterations = 1
    agent.verbose = False
    agent.logger = SimpleNamespace(
        info=lambda *args, **kwargs: None,
        warning=lambda *args, **kwargs: None,
    )
    agent._stream_llm_response = lambda messages, phase, iteration: SimpleNamespace(
        content="我已经完成了", tool_calls=[]
    )

    result = agent._execute_thinking_loop("绘制甲市地图")

    assert result["success"] is False
    assert result["error_code"] == "agent_no_tool_call"


def test_tool_failure_is_not_lost_when_model_stops_without_retry(monkeypatch):
    agent = ThinkingGISMappingAgent.__new__(ThinkingGISMappingAgent)
    agent.max_iterations = 2
    agent.verbose = False
    agent.logger = SimpleNamespace(
        info=lambda *args, **kwargs: None,
        warning=lambda *args, **kwargs: None,
    )
    responses = iter([
        SimpleNamespace(
            content="调用工具",
            tool_calls=[{"id": "call-1", "name": "add_layer", "args": {"name": "道路"}}],
        ),
        SimpleNamespace(content="我已经完成了", tool_calls=[]),
    ])
    agent._stream_llm_response = lambda messages, phase, iteration: next(responses)
    agent._execute_tool = lambda tool_name, tool_input: (
        '{"tool_result":{"success":false,"error_code":"validation_error",'
        '"retryable":false,"next_action":"adjust_tool_arguments"}}'
    )
    agent.tool_dict = {}

    result = agent._execute_thinking_loop("绘制甲市道路")

    assert result["success"] is False
    assert result["error_code"] == "validation_error"
    assert result["next_action"] == "adjust_tool_arguments"
