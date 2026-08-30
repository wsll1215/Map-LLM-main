from gis_mapping_agent.agent.intent_gateway import recognize_intent


class FakeResponse:
    def __init__(self, args):
        self.tool_calls = [{"name": "parse_map_intent", "args": args}]


class FakeBoundLLM:
    def __init__(self, response):
        self.response = response

    def invoke(self, messages):
        return self.response


class FakeLLM:
    def __init__(self, args):
        self.bound = FakeBoundLLM(FakeResponse(args))
        self.bind_count = 0

    def bind_tools(self, tools, **kwargs):
        self.bind_count += 1
        return self.bound


def test_complete_rule_result_is_accepted_without_llm():
    result = recognize_intent("给我天津市的地图，并且要有道路跟河流")

    assert result.status == "accepted"
    assert result.llm_used is False
    assert result.intent.location.text == "天津市"


def test_partial_rules_are_completed_by_function_call():
    llm = FakeLLM(
        {
            "task": "create_map",
            "location": {"text": "天津市", "precision": "city"},
            "layers": [{"role": "road"}, {"role": "river"}],
        }
    )

    result = recognize_intent("请显示主要道路和河流", llm=llm)

    assert result.status == "accepted"
    assert result.llm_used is True
    assert result.intent.location.text == "天津市"
    assert {layer.role for layer in result.intent.layers} == {"road", "river"}


def test_rule_conflict_requires_clarification_without_calling_llm():
    llm = FakeLLM(
        {
            "task": "create_map",
            "location": {"text": "天津市"},
            "layers": [{"role": "road"}],
        }
    )

    result = recognize_intent("制作天津市和北京市的道路地图", llm=llm)

    assert result.status == "needs_clarification"
    assert result.llm_used is False
    assert result.conflicts == ["multiple_locations"]
    assert llm.bind_count == 0


def test_missing_location_after_llm_completion_stays_clarification():
    llm = FakeLLM(
        {
            "task": "create_map",
            "location": {"text": None},
            "layers": [{"role": "road"}],
        }
    )

    result = recognize_intent("请显示主要道路", llm=llm)

    assert result.status == "needs_clarification"
    assert "location" in result.missing_fields
    assert result.issues[0].code == "location_missing"


def test_modify_request_without_current_map_is_blocked_before_execution():
    result = recognize_intent("删除道路图层")

    assert result.status == "needs_clarification"
    assert "current_map_state" in result.missing_fields


def test_gateway_reports_recognition_phases_for_trace_in_order():
    events = []
    llm = FakeLLM(
        {
            "task": "create_map",
            "location": {"text": "天津市", "precision": "city"},
            "layers": [{"role": "road"}],
        }
    )

    result = recognize_intent(
        "请显示主要道路",
        llm=llm,
        trace_callback=lambda **event: events.append(event),
    )

    assert result.status == "accepted"
    assert [event["event_type"] for event in events] == [
        "intent_rule_parse",
        "intent_llm_parse",
        "intent_merge",
        "intent_validate",
    ]
    assert all(event["status"] in {"success", "warning", "error"} for event in events)


def test_llm_cannot_add_to_locked_layers_or_invent_explicit_sources():
    llm = FakeLLM(
        {
            "task": "create_map",
            "location": {"text": "天津市", "precision": "city"},
            "layers": [{"role": "road"}, {"role": "river"}],
            "explicit_sources": ["secret.geojson"],
        }
    )

    result = recognize_intent("请显示主要道路", llm=llm)

    assert result.status == "accepted"
    assert [layer.role for layer in result.intent.layers] == ["road"]
    assert result.intent.explicit_sources == []


def test_llm_bind_failure_returns_structured_failure_instead_of_raising():
    class BindFailureLLM:
        def bind_tools(self, *_args, **_kwargs):
            raise RuntimeError("provider unavailable")

    result = recognize_intent("请显示主要道路", llm=BindFailureLLM())

    assert result.status == "failed"
    assert result.attempt == 1
    assert result.issues[0].code == "llm_bind_failed"
