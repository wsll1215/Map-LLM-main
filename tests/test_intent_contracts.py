import pytest
from pydantic import ValidationError

from gis_mapping_agent.specs.intent import (
    FieldEvidence,
    Intent,
    IntentIssue,
    IntentRecognitionResult,
    LayerSlot,
    LocationSlot,
)


def test_intent_accepts_finite_task_and_layer_roles():
    intent = Intent(
        task="create_map",
        location=LocationSlot(text="天津市", precision="city"),
        layers=[
            LayerSlot(role="road", required=True),
            LayerSlot(role="river", required=True),
        ],
    )

    assert intent.task == "create_map"
    assert [layer.role for layer in intent.layers] == ["road", "river"]


def test_intent_rejects_unregistered_layer_role():
    with pytest.raises(ValidationError):
        LayerSlot(role="my_custom_layer")


def test_recognition_result_preserves_field_provenance_and_issues():
    intent = Intent(
        task="create_map",
        location=LocationSlot(text=None),
        layers=[LayerSlot(role="road")],
    )
    result = IntentRecognitionResult(
        status="needs_clarification",
        intent=intent,
        field_evidence={
            "layers": FieldEvidence(
                field="layers",
                source="rule",
                confidence=1.0,
                evidence="道路",
                locked=True,
            )
        },
        missing_fields=["location"],
        issues=[
            IntentIssue(
                code="location_missing",
                field="location",
                message="缺少地点",
                recoverable=True,
                next_action="ask_user",
            )
        ],
    )

    payload = result.model_dump(mode="json")
    assert payload["status"] == "needs_clarification"
    assert payload["field_evidence"]["layers"]["source"] == "rule"
    assert payload["issues"][0]["next_action"] == "ask_user"


def test_intent_does_not_accept_source_planning_fields():
    with pytest.raises(ValidationError):
        Intent(
            task="create_map",
            location=LocationSlot(text="天津市"),
            layers=[LayerSlot(role="road")],
            bbox=[117.0, 38.0, 118.0, 39.0],
        )
