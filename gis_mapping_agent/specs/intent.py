"""Contracts for side-effect-free natural-language intent recognition."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


TaskType = Literal[
    "create_map",
    "modify_map",
    "query_map",
    "retry",
    "cancel",
    "clarification",
]

LayerRole = Literal[
    "boundary",
    "road",
    "railway",
    "river",
    "school",
    "primary_school",
    "university",
    "hospital",
    "park",
    "poi",
]

OperationType = Literal[
    "add_layer",
    "remove_layer",
    "style_layer",
    "reorder_layers",
    "update_map_config",
    "add_annotation",
    "remove_annotation",
    "update_annotation",
    "add_scalebar",
    "update_scalebar",
    "remove_scalebar",
    "add_compass",
    "update_compass",
    "remove_compass",
    "update_legend",
    "update_title",
    "update_extent",
    "update_generalization_params",
    "toggle_layer_visibility",
    "undo",
]

RecognitionStatus = Literal[
    "accepted",
    "partial",
    "needs_llm",
    "needs_clarification",
    "schema_invalid",
    "domain_invalid",
    "failed",
]


class IntentModel(BaseModel):
    """Base model that rejects fields outside the semantic contract."""

    model_config = ConfigDict(extra="forbid")


class LocationSlot(IntentModel):
    text: Optional[str] = None
    precision: Optional[Literal["province", "city", "district", "place"]] = None


class LayerSlot(IntentModel):
    role: LayerRole
    required: bool = True


class OperationSlot(IntentModel):
    action: OperationType
    target: Optional[str] = None
    parameters: Dict[str, Any] = Field(default_factory=dict)


class Intent(IntentModel):
    """User intent only; source selection and execution stay downstream."""

    task: TaskType
    location: LocationSlot = Field(default_factory=LocationSlot)
    layers: List[LayerSlot] = Field(default_factory=list)
    operations: List[OperationSlot] = Field(default_factory=list)
    style: Dict[str, Any] = Field(default_factory=dict)
    explicit_sources: List[str] = Field(default_factory=list)
    unknown_fields: List[str] = Field(default_factory=list)


class FieldEvidence(IntentModel):
    field: str
    source: Literal["user", "rule", "llm", "backend"]
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: Optional[str] = None
    value: Any = None
    locked: bool = False


class IntentIssue(IntentModel):
    code: str
    field: Optional[str] = None
    severity: Literal["info", "warning", "error"] = "error"
    message: str
    recoverable: bool = False
    retryable: bool = False
    next_action: str
    details: Dict[str, Any] = Field(default_factory=dict)


class IntentRecognitionResult(IntentModel):
    status: RecognitionStatus
    intent: Optional[Intent] = None
    field_evidence: Dict[str, FieldEvidence] = Field(default_factory=dict)
    missing_fields: List[str] = Field(default_factory=list)
    conflicts: List[str] = Field(default_factory=list)
    issues: List[IntentIssue] = Field(default_factory=list)
    attempt: int = Field(default=1, ge=1)
    llm_used: bool = False
