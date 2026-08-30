"""Single rule-first gateway for map intent recognition."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

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


def _notify(
    callback: Optional[Callable[..., None]],
    *,
    event_type: str,
    status: str,
    input_data: Any = None,
    output_data: Any = None,
    error: Any = None,
) -> None:
    """Notify observability code without coupling recognition to persistence."""
    if callback is None:
        return
    try:
        callback(
            event_type=event_type,
            status=status,
            input_data=input_data or {},
            output_data=output_data or {},
            error=error,
        )
    except Exception:
        return


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
    layers_locked = bool(
        rule_result.field_evidence.get("layers")
        and rule_result.field_evidence["layers"].locked
    )
    if not layers_locked:
        known_roles = {layer.role for layer in layers}
        for layer in llm_intent.layers:
            if layer.role not in known_roles:
                layers.append(layer)
                known_roles.add(layer.role)

    # Source paths are user evidence only. The LLM can never introduce a
    # dataset reference into the downstream source planner.
    explicit_sources = list(dict.fromkeys(rule_intent.explicit_sources))
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
    trace_callback: Optional[Callable[..., None]] = None,
) -> IntentRecognitionResult:
    """Recognize one request without selecting data or executing tools."""
    rule_result = RuleParser().parse(text, current_state)
    _notify(
        trace_callback,
        event_type="intent_rule_parse",
        status="warning" if rule_result.conflicts else "success",
        input_data={"request_text": text},
        output_data={
            "decision": rule_result.decision,
            "intent": rule_result.intent.model_dump(mode="json"),
            "missing_fields": rule_result.missing_fields,
            "conflicts": rule_result.conflicts,
        },
        error=(
            {"error_code": "multiple_locations", "next_action": "ask_user"}
            if rule_result.conflicts
            else None
        ),
    )

    if rule_result.conflicts:
        issues = [
            _issue(
                conflict,
                "请求包含无法自动选择的语义冲突",
                next_action="ask_user",
            )
            for conflict in rule_result.conflicts
        ]
        result = _clarification_result(rule_result, issues=issues)
        _notify(
            trace_callback,
            event_type="intent_validate",
            status="warning",
            output_data={
                "status": result.status,
                "missing_fields": result.missing_fields,
                "conflicts": result.conflicts,
            },
            error={"error_code": "clarification_required", "next_action": "ask_user"},
        )
        return result

    # Missing map state is a domain fact, not an LLM-completable semantic slot.
    if "current_map_state" in rule_result.missing_fields:
        result = _clarification_result(
            rule_result,
            issues=[
                _issue(
                    "current_map_state_missing",
                    "当前没有可供修改或查询的地图",
                    next_action="ask_user",
                )
            ],
        )
        _notify(
            trace_callback,
            event_type="intent_validate",
            status="warning",
            output_data={"status": result.status, "missing_fields": result.missing_fields},
            error={"error_code": "current_map_state_missing", "next_action": "ask_user"},
        )
        return result

    if not rule_result.llm_required and rule_result.decision == "complete":
        missing = _missing_fields(rule_result.intent, current_state)
        if missing:
            result = _clarification_result(
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
            _notify(
                trace_callback,
                event_type="intent_validate",
                status="warning",
                output_data={"status": result.status, "missing_fields": result.missing_fields},
                error={"error_code": "clarification_required", "next_action": "ask_user"},
            )
            return result
        result = IntentRecognitionResult(
            status="accepted",
            intent=rule_result.intent,
            field_evidence=rule_result.field_evidence,
            attempt=1,
            llm_used=False,
        )
        _notify(
            trace_callback,
            event_type="intent_validate",
            status="success",
            output_data={"status": result.status, "intent": result.intent.model_dump(mode="json")},
        )
        return result

    if llm is None:
        missing_fields = list(rule_result.missing_fields)
        issue_code = "clarification_required" if missing_fields else "llm_unavailable"
        issue_message = (
            "缺少继续制图所需的信息：" + "、".join(missing_fields)
            if missing_fields
            else "规则无法完整理解请求，语义补全服务不可用"
        )
        result = _clarification_result(
            rule_result,
            issues=[
                _issue(
                    issue_code,
                    issue_message,
                    next_action="ask_user",
                    retryable=not missing_fields,
                )
            ],
        )
        _notify(
            trace_callback,
            event_type="intent_llm_parse",
            status="warning" if missing_fields else "error",
            input_data={"request_text": text},
            output_data={},
            error={"error_code": issue_code, "next_action": "ask_user"},
        )
        _notify(
            trace_callback,
            event_type="intent_validate",
            status="warning",
            output_data={"status": result.status, "missing_fields": result.missing_fields},
            error={"error_code": issue_code, "next_action": "ask_user"},
        )
        return result

    llm_result = LlmIntentParser(llm).parse(text, rule_result, current_state)
    _notify(
        trace_callback,
        event_type="intent_llm_parse",
        status="success" if llm_result.status == "accepted" else "error",
        input_data={"request_text": text},
        output_data={
            "status": llm_result.status,
            "attempts": llm_result.attempts,
            "intent": (
                llm_result.intent.model_dump(mode="json")
                if llm_result.intent is not None
                else None
            ),
        },
        error=(
            llm_result.issues[0].model_dump(mode="json")
            if llm_result.issues
            else None
        ),
    )
    if llm_result.status != "accepted" or llm_result.intent is None:
        result = _clarification_result(
            rule_result,
            issues=llm_result.issues,
            llm_used=True,
            attempt=max(1, llm_result.attempts),
            status=llm_result.status,
        )
        _notify(
            trace_callback,
            event_type="intent_validate",
            status="warning",
            output_data={"status": result.status, "missing_fields": result.missing_fields},
            error=(
                result.issues[0].model_dump(mode="json")
                if result.issues
                else None
            ),
        )
        return result

    intent, evidence, conflicts = _merge_intents(rule_result, llm_result.intent)
    _notify(
        trace_callback,
        event_type="intent_merge",
        status="warning" if conflicts else "success",
        input_data={"rule_intent": rule_result.intent.model_dump(mode="json")},
        output_data={"intent": intent.model_dump(mode="json"), "conflicts": conflicts},
        error=(
            {"error_code": "intent_conflict", "next_action": "ask_user"}
            if conflicts
            else None
        ),
    )
    missing = _missing_fields(intent, current_state)
    if conflicts:
        result = IntentRecognitionResult(
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
            attempt=max(1, llm_result.attempts),
            llm_used=True,
        )
        _notify(
            trace_callback,
            event_type="intent_validate",
            status="warning",
            output_data={"status": result.status, "conflicts": result.conflicts},
            error={"error_code": "intent_conflict", "next_action": "ask_user"},
        )
        return result

    if missing:
        result = IntentRecognitionResult(
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
            attempt=max(1, llm_result.attempts),
            llm_used=True,
        )
        _notify(
            trace_callback,
            event_type="intent_validate",
            status="warning",
            output_data={"status": result.status, "missing_fields": result.missing_fields},
            error={"error_code": "clarification_required", "next_action": "ask_user"},
        )
        return result

    result = IntentRecognitionResult(
        status="accepted",
        intent=intent,
        field_evidence=evidence,
        attempt=max(1, llm_result.attempts),
        llm_used=True,
    )
    _notify(
        trace_callback,
        event_type="intent_validate",
        status="success",
        output_data={"status": result.status, "intent": result.intent.model_dump(mode="json")},
    )
    return result
