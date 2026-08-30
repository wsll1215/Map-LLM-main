from gis_mapping_agent.agent.conversational import ConversationalMappingAgent
from gis_mapping_agent.agent.thinking import ThinkingGISMappingAgent
from gis_mapping_agent.models.schemas import GeometryType, LayerConfig, MapConfig, MapState, SessionInfo

from langchain_core.messages import HumanMessage


class FakeLogger:
    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass


class FakeResponse:
    def __init__(self, content):
        self.content = content


class FakeLLM:
    def __init__(self, content):
        self.content = content
        self.calls = 0

    def invoke(self, messages):
        self.calls += 1
        return FakeResponse(self.content)

    def stream(self, messages):
        self.stream_calls = getattr(self, "stream_calls", 0) + 1
        yield FakeResponse(self.content)


class FakeCreationAgent:
    def __init__(self):
        self.current_map_state = None
        self.session_id = None
        self.requests = []

    def create_map(self, request):
        self.requests.append(request)
        return {"success": True, "message": "地图创建完成", "output": "", "map_state": None}


class FakeStateManager:
    def __init__(self):
        self.saved = []

    def save_state(self, state):
        self.saved.append(state)
        return True


class FakeMapRenderer:
    def __init__(self):
        self.rendered = []

    def render_map(self, state):
        self.rendered.append(state)
        return {"success": True, "file_path": "outputs/new-map.png"}


def make_agent_with_fake_llm(content="create"):
    agent = ConversationalMappingAgent.__new__(ConversationalMappingAgent)
    agent.llm = FakeLLM(content)
    agent.logger = FakeLogger()
    return agent


def make_state(user_input, has_map_state=True):
    return {
        "messages": [HumanMessage(content=user_input)],
        "current_map_state": MapState(
            config=MapConfig(map_id="m1", title="old", extent=[0, 0, 1, 1]),
            session_info=SessionInfo(session_id="s1"),
        ) if has_map_state else None,
        "patch": None,
        "render_result": None,
        "error": None,
        "requires_confirmation": False,
    }


def test_complete_rule_intent_skips_llm_classification():
    agent = make_agent_with_fake_llm("create")
    state = make_state(
        "使用data5目录中的数据生成地图: Wuhan.shp, Skating Rink.shp。Wuhan.shp: 根据 地名 属性调整多边形要素的颜色",
        has_map_state=True,
    )

    result = agent._classify_intent(state)

    assert not hasattr(agent.llm, "stream_calls")
    assert agent.llm.calls == 0
    assert result["user_intent"] == "create"
    assert result["task_type"] == "create"


def test_query_intent_is_selected_before_generic_map_word():
    agent = make_agent_with_fake_llm("query")
    result = agent._classify_intent(make_state("查看当前地图状态", has_map_state=True))

    assert result["user_intent"] == "query"
    assert not hasattr(agent.llm, "stream_calls")
    assert agent.llm.calls == 0


def test_thinking_agent_emits_authoritative_assistant_message_after_stream(monkeypatch):
    published = []

    class Chunk:
        def __init__(self, content):
            self.content = content
            self.tool_calls = []

        def __add__(self, other):
            return Chunk(self.content + other.content)

    class StreamingLLM:
        model_name = "test-model"

        def stream(self, _messages):
            return iter([Chunk("正在"), Chunk("获取数据")])

    monkeypatch.setattr(
        "mapping.realtime.publish_assistant_stream_event",
        lambda **payload: published.append(payload),
    )
    agent = ThinkingGISMappingAgent.__new__(ThinkingGISMappingAgent)
    agent.llm = StreamingLLM()
    agent.session_id = None

    response = agent._stream_llm_response([], phase="tool_selection", iteration=1)

    assert response.content == "正在获取数据"
    assert [item["event_type"] for item in published] == [
        "assistant_started",
        "assistant_delta",
        "assistant_message",
    ]
    assert published[-1]["content"] == "正在获取数据"


def test_rule_fallback_prefers_complete_map_creation_request():
    agent = make_agent_with_fake_llm()
    request = "使用data5目录中的数据生成地图: Wuhan.shp, Skating Rink.shp, Racecourse.shp 图层样式要求: 根据 地名 属性调整颜色"

    assert agent._rule_intent_classification(request, has_map_state=True) == "create"


def test_rule_fallback_keeps_explicit_layer_delete_as_modify():
    agent = make_agent_with_fake_llm()

    assert agent._rule_intent_classification("删除Skating Rink图层", has_map_state=True) == "modify"


def test_new_map_request_detection_is_strict():
    agent = make_agent_with_fake_llm()

    assert agent._looks_like_new_map_request(
        "使用data5目录中的数据生成地图: Wuhan.shp, Skating Rink.shp, Racecourse.shp"
    )
    assert not agent._looks_like_new_map_request("使用红色修改铁路图层")


def test_create_map_does_not_fallback_to_old_state_when_no_new_map_is_created():
    old_state = MapState(
        config=MapConfig(map_id="old", title="old", extent=[0, 0, 1, 1]),
        session_info=SessionInfo(session_id="web_session_1"),
    )
    agent = make_agent_with_fake_llm()
    agent.session_id = "web_session_1"
    agent._last_chat_session_id_explicit = True
    agent.creation_agent = FakeCreationAgent()
    agent.state_manager = FakeStateManager()
    state = {
        "messages": [HumanMessage(content="使用data5目录中的数据生成地图: Wuhan.shp, Skating Rink.shp")],
        "current_map_state": old_state,
        "session_id": "web_session_1",
        "user_intent": "create",
        "task_type": "create",
        "last_operation": None,
        "tool_trace_id": None,
        "error": None,
    }

    result = agent._create_map(state)

    assert result["error"]
    assert result["current_map_state"] is None
    assert agent.state_manager.saved == []
    assert "MapSpec:" not in agent.creation_agent.requests[0]


def test_create_map_uses_new_tool_state_and_forces_render_when_model_skips_save(monkeypatch):
    old_state = MapState(
        config=MapConfig(map_id="old", title="old", extent=[0, 0, 1, 1]),
        session_info=SessionInfo(session_id="web_session_2"),
    )
    new_state = MapState(
        config=MapConfig(map_id="new", title="new", extent=[0, 0, 1, 1]),
        session_info=SessionInfo(session_id="web_session_2"),
        layers=[
            LayerConfig(layer_id="wuhan", name="Wuhan", geometry_type=GeometryType.POLYGON, data_source="data/data5/Wuhan.shp"),
        ],
    )

    class FakeUnifiedTools:
        current_map_state = new_state

    monkeypatch.setattr(
        "gis_mapping_agent.tools.unified_mapping_tools.get_unified_tools",
        lambda: FakeUnifiedTools(),
    )

    agent = make_agent_with_fake_llm()
    agent.session_id = "web_session_2"
    agent._last_chat_session_id_explicit = True
    agent.creation_agent = FakeCreationAgent()
    agent.state_manager = FakeStateManager()
    agent.map_renderer = FakeMapRenderer()
    state = {
        "messages": [HumanMessage(content="使用data5目录中的数据生成地图: Wuhan.shp, Skating Rink.shp")],
        "current_map_state": old_state,
        "session_id": "web_session_2",
        "user_intent": "create",
        "task_type": "create",
        "last_operation": None,
        "tool_trace_id": None,
        "error": None,
    }

    result = agent._create_map(state)

    assert result.get("error") is None
    assert result["current_map_state"] is new_state
    assert new_state.output_path == "outputs/new-map.png"
    assert agent.map_renderer.rendered == [new_state]
    assert agent.state_manager.saved == [new_state]
