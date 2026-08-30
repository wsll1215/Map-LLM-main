from gis_mapping_agent.agent.intent_llm import LlmIntentParser
from gis_mapping_agent.agent.intent_rules import RuleParser


class FakeResponse:
    def __init__(self, tool_calls=None, content=""):
        self.tool_calls = tool_calls or []
        self.content = content


class FakeBoundLLM:
    def __init__(self, responses):
        self.responses = iter(responses)

    def invoke(self, messages):
        return next(self.responses)


class FakeLLM:
    def __init__(self, responses):
        self.bound = FakeBoundLLM(responses)
        self.bind_calls = []

    def bind_tools(self, tools, **kwargs):
        self.bind_calls.append((tools, kwargs))
        return self.bound


def _call(args):
    return FakeResponse(tool_calls=[{"name": "parse_map_intent", "args": args}])


def test_llm_parser_accepts_structured_semantic_function_call():
    llm = FakeLLM(
        [
            _call(
                {
                    "task": "create_map",
                    "location": {"text": "天津市", "precision": "city"},
                    "layers": [{"role": "road"}, {"role": "river"}],
                }
            )
        ]
    )

    result = LlmIntentParser(llm).parse(
        "给我天津市的图，要有路和河",
        RuleParser().parse("给我天津市的图，要有路和河"),
    )

    assert result.status == "accepted"
    assert result.intent.location.text == "天津市"
    assert {layer.role for layer in result.intent.layers} == {"road", "river"}
    assert result.attempts == 1
    assert result.tool_name == "parse_map_intent"


def test_llm_parser_rejects_free_text_without_tool_call_after_one_retry():
    llm = FakeLLM([FakeResponse(content="我认为这是创建地图"), FakeResponse(content="仍然无法解析")])

    result = LlmIntentParser(llm).parse(
        "请显示道路",
        RuleParser().parse("请显示道路"),
    )

    assert result.status == "schema_invalid"
    assert result.intent is None
    assert result.attempts == 2
    assert result.issues[0].code == "llm_no_tool_call"


def test_llm_parser_retries_schema_error_once_and_accepts_corrected_result():
    llm = FakeLLM(
        [
            _call(
                {
                    "task": "create_map",
                    "location": {"text": "天津市"},
                    "layers": [{"role": "unregistered"}],
                }
            ),
            _call(
                {
                    "task": "create_map",
                    "location": {"text": "天津市", "precision": "city"},
                    "layers": [{"role": "road"}],
                }
            ),
        ]
    )

    result = LlmIntentParser(llm).parse(
        "做天津市道路图",
        RuleParser().parse("做天津市道路图"),
    )

    assert result.status == "accepted"
    assert result.attempts == 2
    assert result.intent.layers[0].role == "road"


def test_llm_parser_does_not_allow_source_planning_fields():
    llm = FakeLLM(
        [
            _call(
                {
                    "task": "create_map",
                    "location": {"text": "天津市"},
                    "layers": [{"role": "road"}],
                    "bbox": [117, 38, 118, 39],
                }
            ),
            _call(
                {
                    "task": "create_map",
                    "location": {"text": "天津市"},
                    "layers": [{"role": "road"}],
                    "source_url": "https://example.invalid/data",
                }
            ),
        ]
    )

    result = LlmIntentParser(llm).parse(
        "做天津市道路图",
        RuleParser().parse("做天津市道路图"),
    )

    assert result.status == "schema_invalid"
    assert result.attempts == 2
