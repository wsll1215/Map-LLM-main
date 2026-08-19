from langchain_core.messages import AIMessage

from gis_mapping_agent.agent.conversational import ConversationalMappingAgent


class DummyRenderer:
    def __init__(self, result):
        self.result = result
        self.calls = 0

    def render_map(self, _state):
        self.calls += 1
        return self.result


def make_agent(renderer=None):
    agent = ConversationalMappingAgent.__new__(ConversationalMappingAgent)
    agent.session_id = "s1"
    agent.map_renderer = renderer
    return agent


def test_graph_error_node_asks_for_data_path_clarification():
    agent = make_agent()
    state = {
        "messages": [],
        "task_type": "create",
        "error": "No such file: data/missing.shp",
        "render_result": None,
        "clarification_questions": [],
    }

    result = agent._handle_error(state)

    assert result["clarification_questions"]
    assert isinstance(result["messages"][-1], AIMessage)
    assert "数据文件路径" in result["messages"][-1].content


def test_graph_error_node_retries_render_and_keeps_state():
    renderer = DummyRenderer({"success": True, "file_path": "out.png"})
    agent = make_agent(renderer)
    map_state = object()
    state = {
        "messages": [],
        "task_type": "modify",
        "current_map_state": map_state,
        "error": None,
        "render_result": {"success": False, "error": "temporary render failure"},
    }

    result = agent._handle_error(state)

    assert renderer.calls == 1
    assert result["current_map_state"] is map_state
    assert result["render_result"]["success"] is True
    assert result["error"] is None
