from types import SimpleNamespace

import pytest

from gis_mapping_agent.utils.intent_classifier_v2 import IntentAnalysisV2, IntentClassifierV2


class _ToolCallResponse:
    tool_calls = [
        {
            "args": {
                "intent": "add_layer",
                "confidence": 0.9,
                "target": "高铁路线",
            }
        }
    ]
    content = ""


class _BoundModel:
    def invoke(self, messages):
        return _ToolCallResponse()


class _ModelThatRequiresAutomaticToolChoice:
    def bind_tools(self, tools):
        assert tools
        return _BoundModel()


class _FailingModel:
    def bind_tools(self, tools):
        raise RuntimeError("Thinking mode does not support this tool_choice")


def test_intent_classifier_uses_provider_compatible_tool_binding():
    classifier = IntentClassifierV2.__new__(IntentClassifierV2)
    classifier.llm = _ModelThatRequiresAutomaticToolChoice()
    classifier.logger = SimpleNamespace(info=lambda *_args: None, warning=lambda *_args: None, error=lambda *_args: None)
    current_state = SimpleNamespace(
        config=SimpleNamespace(title="石家庄市地图"),
        layers=[],
        scalebar=None,
        compass=None,
    )

    result = classifier.classify_intent("把高铁路线画出来", current_state)

    assert result.intent == "add_layer"
    assert result.target == "高铁路线"


def test_intent_classifier_falls_back_for_route_drawing_when_provider_fails():
    classifier = IntentClassifierV2.__new__(IntentClassifierV2)
    classifier.llm = _FailingModel()
    classifier.logger = SimpleNamespace(
        info=lambda *_args: None,
        warning=lambda *_args: None,
        error=lambda *_args: None,
        debug=lambda *_args: None,
    )
    current_state = SimpleNamespace(
        config=SimpleNamespace(title="石家庄市地图"),
        layers=[],
        scalebar=None,
        compass=None,
    )

    result = classifier.classify_intent("把高铁路线画出来", current_state)

    assert result.intent == "add_layer"
    assert result.clarification_questions == []


def test_annotation_place_is_extracted_from_original_request(monkeypatch):
    classifier = IntentClassifierV2.__new__(IntentClassifierV2)
    monkeypatch.setattr(
        "gis_mapping_agent.data_sources.remote.geocode_place",
        lambda place: (116.326, 40.003, place),
    )
    current_state = SimpleNamespace(
        config=SimpleNamespace(extent=[116.025, 39.871, 116.406, 40.173]),
        layers=[],
    )
    analysis = IntentAnalysisV2(
        request="标注清华大学的位置",
        intent="add_annotation",
        clarification_questions=["请提供清华大学的标注位置坐标"],
    )

    result = classifier.validate_intent_with_state(analysis, current_state)

    assert result.position is not None
    assert result.position[0] == pytest.approx(0.7900, abs=0.001)
    assert result.position[1] == pytest.approx(0.4371, abs=0.001)
    assert result.clarification_questions == []
