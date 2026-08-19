from gis_mapping_agent.models.schemas import GeometryType, LayerConfig, MapConfig, MapState, SessionInfo
from gis_mapping_agent.specs import AdjustmentPatch, PatchOperation
from gis_mapping_agent.adjustment import ModificationEngine
from gis_mapping_agent.utils.intent_classifier_v2 import BatchOperation, IntentAnalysisV2, IntentClassifierV2

import pytest


def make_state():
    return MapState(
        config=MapConfig(map_id="m1", title="old", extent=[0, 0, 1, 1]),
        session_info=SessionInfo(session_id="s1"),
        layers=[
            LayerConfig(layer_id="l1", name="roads", geometry_type=GeometryType.LINE, data={"type": "FeatureCollection"}),
            LayerConfig(layer_id="l2", name="railway", geometry_type=GeometryType.LINE, data={"type": "FeatureCollection"}),
        ],
        is_generalization_task=True,
        generalization_params={"algorithm": "stroke", "target_scale": 1000, "keep_ratio": 0.5},
    )


def test_adjustment_patch_executes_dynamic_operations():
    patch = AdjustmentPatch(
        operations=[
            PatchOperation(action="remove_layer", target="railway"),
            PatchOperation(action="toggle_layer_visibility", target="roads", parameters={"visible": False}),
            PatchOperation(action="style_layer", target="roads", parameters={"color": "red", "linewidth": 2, "alpha": 0.4}),
            PatchOperation(action="update_map_config", target="title", parameters={"title": "new"}),
            PatchOperation(action="update_generalization_params", target="generalization", parameters={"retention_ratio": 0.3, "target_scale": 2000, "algorithm": "hierarchy"}),
        ]
    )

    result = ModificationEngine().apply_modifications(make_state(), patch, "change map")
    state, records = result
    roads = state.layers[0]

    assert len(records) == 5
    assert [layer.name for layer in state.layers] == ["roads"]
    assert roads.visible is False
    assert roads.style.color == "red"
    assert roads.style.linewidth == 2
    assert roads.style.alpha == 0.4
    assert state.config.title == "new"
    assert state.generalization_params["keep_ratio"] == 0.3
    assert state.generalization_params["target_scale"] == 2000
    assert state.generalization_params["algorithm"] == "hierarchy"
    assert result.diff["layers"]["removed"] == ["railway"]
    assert result.diff["layers"]["visibility"]["roads"]["after"] is False


def test_remove_layer_requires_existing_target():
    patch = AdjustmentPatch(operations=[PatchOperation(action="remove_layer", target="Railway")])

    with pytest.raises(ValueError, match="未找到图层"):
        ModificationEngine().apply_modifications(make_state(), patch, "删除不存在的铁路图层")


def test_intent_validation_rejects_llm_target_when_user_reference_is_missing():
    state = MapState(
        config=MapConfig(map_id="m2", title="data5", extent=[0, 0, 1, 1]),
        session_info=SessionInfo(session_id="s2"),
        layers=[
            LayerConfig(layer_id="l1", name="Wuhan", geometry_type=GeometryType.POLYGON, data_source="data5/Wuhan.shp"),
            LayerConfig(layer_id="l2", name="Skating Rink", geometry_type=GeometryType.POINT, data_source="data5/Skating Rink.shp"),
            LayerConfig(layer_id="l3", name="Racecourse", geometry_type=GeometryType.POINT, data_source="data5/Racecourse.shp"),
        ],
    )
    analysis = IntentAnalysisV2(
        request="删除铁路图层",
        intent="remove_layer",
        confidence=0.9,
        target="Wuhan",
        requires_confirmation=False,
        reasoning="mocked wrong LLM target",
    )

    validated = IntentClassifierV2.__new__(IntentClassifierV2).validate_intent_with_state(analysis, state)

    assert validated.clarification_questions
    assert "铁路" in validated.clarification_questions[0]
    assert "Wuhan" in validated.clarification_questions[0]


def test_intent_validation_rejects_extra_batch_layer_not_mentioned_by_user():
    state = MapState(
        config=MapConfig(map_id="m3", title="data5", extent=[0, 0, 1, 1]),
        session_info=SessionInfo(session_id="s3"),
        layers=[
            LayerConfig(layer_id="l1", name="Wuhan", geometry_type=GeometryType.POLYGON, data_source="data5/Wuhan.shp"),
            LayerConfig(layer_id="l2", name="Skating Rink", geometry_type=GeometryType.POINT, data_source="data5/Skating Rink.shp"),
            LayerConfig(layer_id="l3", name="Racecourse", geometry_type=GeometryType.POINT, data_source="data5/Racecourse.shp"),
        ],
    )
    analysis = IntentAnalysisV2(
        request="删除Skating Rink",
        intent="remove_layer",
        confidence=0.9,
        target="multiple",
        batch_operations=[
            BatchOperation(type="remove_layer", layer_name="Skating Rink"),
            BatchOperation(type="remove_layer", layer_name="Wuhan"),
        ],
        requires_confirmation=False,
        reasoning="mocked extra LLM target",
    )

    validated = IntentClassifierV2.__new__(IntentClassifierV2).validate_intent_with_state(analysis, state)

    assert validated.clarification_questions
    assert "额外目标" in validated.clarification_questions[0]
    assert "Wuhan" in validated.clarification_questions[0]


def test_intent_analysis_allows_missing_reasoning_from_llm_tool_call():
    analysis = IntentAnalysisV2(
        request="修改铁路图层颜色为红色",
        intent="style_layer",
        target="Railway",
        color="#FF0000",
    )

    assert analysis.reasoning == ""
    assert analysis.confidence == 0.8


def test_chinese_layer_alias_style_request_generates_patch():
    state = MapState(
        config=MapConfig(map_id="m4", title="roads", extent=[0, 0, 1, 1]),
        session_info=SessionInfo(session_id="s4"),
        layers=[
            LayerConfig(layer_id="railway", name="Railway", geometry_type=GeometryType.LINE, data_source="data1/Railway.shp"),
        ],
    )
    analysis = IntentAnalysisV2(
        request="将铁路的线变成红色",
        intent="style_layer",
        target="铁路",
        color="#FF0000",
    )

    classifier = IntentClassifierV2.__new__(IntentClassifierV2)
    validated = classifier.validate_intent_with_state(analysis, state)
    patch = ModificationEngine().generate_modification_plan(validated)

    assert not validated.clarification_questions
    assert validated.target == "Railway"
    assert patch.operations[0].action == "style_layer"
    assert patch.operations[0].target == "Railway"
    assert patch.operations[0].parameters["color"] == "#FF0000"
