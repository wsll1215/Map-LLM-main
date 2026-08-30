"""Single rule-first gateway for map intent recognition."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..models.schemas import MapState
from ..specs.intent import (
    FieldEvidence,
    Intent,
    IntentIssue,
    IntentRecognitionResult,
    LayerSlot,
    LocationSlot,
)
from .intent_llm import LlmIntentParser
from .intent_rules import RuleParseResult, RuleParser


def _issue(
    code: str,
    message: str,
    *,
    next_action: str,
    recoverable: bool = True,
    retryable: bool = False,
) -> IntentIssue:
    return IntentIssue(
        code=code,
        message=message,
        next_action=next_action,
        recoverable=recoverable,
        retryable=retryable,
    )


def _clarification_result(
    rule_result: RuleParseResult,
    *,
    issues: Optional[List[IntentIssue]] = None,
    llm_used: bool = False,
    attempt: int = 1,
    status: str = "needs_clarification",
) -> IntentRecognitionResult:
    return IntentRecognitionResult(
        status=status,
        intent=rule_result.intent,
        field_evidence=rule_result.field_evidence,
        missing_fields=list(dict.fromkeys(rule_result.missing_fields)),
        conflicts=list(rule_result.conflicts),
        issues=issues or [],
        attempt=attempt,
        llm_used=llm_used,
    )


def _missing_fields(intent: Intent, current_state: Optional[MapState]) -> List[str]:
    missing: List[str] = []
    if intent.task == "create_map" and not intent.location.text and not intent.explicit_sources:
        missing.append("location")
    if intent.task == "modify_map":
        if current_state is None:
            missing.append("current_map_state")
        if not intent.operations:
            missing.append("operations")
    if intent.task == "query_map" and current_state is None:
        missing.append("current_map_state")
    if intent.task == "clarification":
        missing.append("task")
    return list(dict.fromkeys(missing))


def _merge_intents(
    rule_result: RuleParseResult,
    llm_intent: Intent,
) -> tuple[Intent, Dict[str, FieldEvidence], List[str]]:
    rule_intent = rule_result.intent
    conflicts: List[str] = list(rule_result.conflicts)

    task = rule_intent.task
    task_evidence = rule_result.field_evidence.get("task")
    if task_evidence and task_evidence.locked:
        if llm_intent.task != task and llm_intent.task != "clarification":
            conflicts.append("task_mismatch")
    else:
        task = llm_intent.task

    location = rule_intent.location
    location_evidence = rule_result.field_evidence.get("location")
    if location_evidence and location_evidence.locked:
        llm_location = llm_intent.location.text
        if llm_location and llm_location != location.text:
            conflicts.append("location_mismatch")
    elif llm_intent.location.text:
        location = llm_intent.location

    layers: List[LayerSlot] = list(rule_intent.layers)
    known_roles = {layer.role for layer in layers}
    for layer in llm_intent.layers:
        if layer.role not in known_roles:
            layers.append(layer)
            known_roles.add(layer.role)

    explicit_sources = list(dict.fromkeys(rule_intent.explicit_sources + llm_intent.explicit_sources))
    operations = llm_intent.operations or rule_intent.operations
    style = dict(rule_intent.style)
    style.update(llm_intent.style)
    unknown_fields = list(dict.fromkeys(rule_intent.unknown_fields + llm_intent.unknown_fields))
    evidence = dict(rule_result.field_evidence)
    for name, value in llm_intent.model_dump(mode="json").items():
        if name not in evidence:
            evidence[name] = FieldEvidence(
                field=name,
                source="llm",
                confidence=0.7,
                value=value,
                locked=False,
            )

    return (
        Intent(
            task=task,
            location=location,
            layers=layers,
            operations=operations,
            style=style,
            explicit_sources=explicit_sources,
            unknown_fields=unknown_fields,
        ),
        evidence,
        list(dict.fromkeys(conflicts)),
    )


def recognize_intent(
    text: str,
    current_state: Optional[MapState] = None,
    llm: Optional[Any] = None,
) -> IntentRecognitionResult:
    """Recognize one request without selecting data or executing tools."""
    rule_result = RuleParser().parse(text, current_state)

    if rule_result.conflicts:
        issues = [
            _issue(
                conflict,
                "请求包含无法自动选择的语义冲突",
                next_action="ask_user",
            )
            for conflict in rule_result.conflicts
        ]
        return _clarification_result(rule_result, issues=issues)

    # Missing map state is a domain fact, not an LLM-completable semantic slot.
    if "current_map_state" in rule_result.missing_fields:
        return _clarification_result(
            rule_result,
            issues=[
                _issue(
                    "current_map_state_missing",
                    "当前没有可供修改或查询的地图",
                    next_action="ask_user",
                )
            ],
        )

    if not rule_result.llm_required and rule_result.decision == "complete":
        missing = _missing_fields(rule_result.intent, current_state)
        if missing:
            return _clarification_result(
                rule_result,
                issues=[
                    _issue(
                        f"{field}_missing",
                        f"缺少必需字段：{field}",
                        next_action="ask_user",
                    )
                    for field in missing
                ],
            )
        return IntentRecognitionResult(
            status="accepted",
            intent=rule_result.intent,
            field_evidence=rule_result.field_evidence,
            attempt=1,
            llm_used=False,
        )

    if llm is None:
        return _clarification_result(
            rule_result,
            issues=[
                _issue(
                    "llm_unavailable",
                    "规则无法完整理解请求，语义补全服务不可用",
                    next_action="ask_user",
                    retryable=True,
                )
            ],
        )

    llm_result = LlmIntentParser(llm).parse(text, rule_result, current_state)
    if llm_result.status != "accepted" or llm_result.intent is None:
        return _clarification_result(
            rule_result,
            issues=llm_result.issues,
            llm_used=True,
            attempt=llm_result.attempts,
            status=llm_result.status,
        )

    intent, evidence, conflicts = _merge_intents(rule_result, llm_result.intent)
    missing = _missing_fields(intent, current_state)
    if conflicts:
        return IntentRecognitionResult(
            status="needs_clarification",
            intent=intent,
            field_evidence=evidence,
            missing_fields=missing,
            conflicts=conflicts,
            issues=[
                _issue(
                    conflict,
                    "规则和模型对请求的理解不一致",
                    next_action="ask_user",
                )
                for conflict in conflicts
            ],
            attempt=llm_result.attempts,
            llm_used=True,
        )

    if missing:
        return IntentRecognitionResult(
            status="needs_clarification",
            intent=intent,
            field_evidence=evidence,
            missing_fields=missing,
            issues=[
                _issue(
                    f"{field}_missing",
                    f"缺少必需字段：{field}",
                    next_action="ask_user",
                )
                for field in missing
            ],
            attempt=llm_result.attempts,
            llm_used=True,
        )

    return IntentRecognitionResult(
        status="accepted",
        intent=intent,
        field_evidence=evidence,
        attempt=llm_result.attempts,
        llm_used=True,
    )
