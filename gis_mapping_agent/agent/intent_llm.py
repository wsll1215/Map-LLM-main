"""Constrained LLM completion for semantic map intent fields."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import ValidationError

from ..models.schemas import MapState
from ..specs.intent import FieldEvidence, Intent, IntentIssue
from .intent_rules import RuleParseResult


LlmParseStatus = Literal["accepted", "schema_invalid", "failed"]

_INTENT_TOOL_SCHEMA = convert_to_openai_tool(Intent)
_INTENT_TOOL_SCHEMA["function"]["name"] = "parse_map_intent"


@dataclass(frozen=True)
class LlmParseResult:
    intent: Optional[Intent]
    field_evidence: Dict[str, FieldEvidence]
    issues: List[IntentIssue]
    status: LlmParseStatus
    attempts: int
    tool_name: str = "parse_map_intent"


def _issue(
    code: str,
    message: str,
    *,
    retryable: bool,
    next_action: str,
    details: Optional[Dict[str, Any]] = None,
) -> IntentIssue:
    return IntentIssue(
        code=code,
        message=message,
        retryable=retryable,
        recoverable=retryable,
        next_action=next_action,
        details=details or {},
    )


class LlmIntentParser:
    """Use Function Calling only to complete semantic fields."""

    def __init__(self, llm: Any, *, max_schema_retries: int = 1):
        self.llm = llm
        self.max_schema_retries = max(0, int(max_schema_retries))

    def _messages(
        self,
        text: str,
        rule_result: RuleParseResult,
        current_state: Optional[MapState],
        correction: Optional[str] = None,
    ) -> List[Any]:
        locked_fields = {
            name: evidence.value
            for name, evidence in rule_result.field_evidence.items()
            if evidence.locked
        }
        system = (
            "你是地图意图结构化解析器。只能调用 parse_map_intent 返回语义字段。"
            "不要生成数据源、文件路径、bbox、dataset_id、provider 或任务完成状态。"
            "规则已锁定的字段不能覆盖；无法确定的字段返回 null 或空数组，不能猜测。"
            "图层 role 只能使用已注册角色。"
        )
        context = {
            "request": text,
            "rule_locked_fields": locked_fields,
            "missing_fields": rule_result.missing_fields,
            "conflicts": rule_result.conflicts,
            "has_current_map": current_state is not None,
        }
        if correction:
            context["previous_validation_error"] = correction
        return [
            SystemMessage(content=system),
            HumanMessage(content=json.dumps(context, ensure_ascii=False)),
        ]

    @staticmethod
    def _tool_args(response: Any) -> Optional[Dict[str, Any]]:
        calls = getattr(response, "tool_calls", None) or []
        if not calls:
            return None
        call = calls[0]
        args = call.get("args") if isinstance(call, dict) else getattr(call, "args", None)
        if isinstance(args, str):
            args = json.loads(args)
        return args if isinstance(args, dict) else None

    @staticmethod
    def _evidence(intent: Intent) -> Dict[str, FieldEvidence]:
        values = intent.model_dump(mode="json")
        return {
            field: FieldEvidence(
                field=field,
                source="llm",
                confidence=0.7,
                value=value,
                locked=False,
            )
            for field, value in values.items()
        }

    def parse(
        self,
        text: str,
        rule_result: RuleParseResult,
        current_state: Optional[MapState] = None,
    ) -> LlmParseResult:
        correction: Optional[str] = None
        max_attempts = self.max_schema_retries + 1

        try:
            bound_llm = self.llm.bind_tools(
                [_INTENT_TOOL_SCHEMA],
                tool_choice={
                    "type": "function",
                    "function": {"name": "parse_map_intent"},
                },
            )
        except Exception as exc:
            return LlmParseResult(
                intent=None,
                field_evidence={},
                issues=[
                    _issue(
                        "llm_bind_failed",
                        "无法绑定语义解析函数",
                        retryable=False,
                        next_action="ask_user",
                        details={"exception_type": type(exc).__name__},
                    )
                ],
                status="failed",
                attempts=0,
            )

        for attempt in range(1, max_attempts + 1):
            messages = self._messages(text, rule_result, current_state, correction)
            try:
                response = bound_llm.invoke(messages)
                args = self._tool_args(response)
                if args is None:
                    correction = "必须调用 parse_map_intent 函数，不能返回普通文本。"
                    issue = _issue(
                        "llm_no_tool_call",
                        "模型没有返回 parse_map_intent 函数调用",
                        retryable=attempt < max_attempts,
                        next_action="retry_llm" if attempt < max_attempts else "ask_user",
                    )
                    if attempt < max_attempts:
                        continue
                    return LlmParseResult(None, {}, [issue], "schema_invalid", attempt)

                intent = Intent.model_validate(args)
                return LlmParseResult(
                    intent=intent,
                    field_evidence=self._evidence(intent),
                    issues=[],
                    status="accepted",
                    attempts=attempt,
                )
            except (ValidationError, ValueError, TypeError, json.JSONDecodeError) as exc:
                correction = "Function Call 参数校验失败：" + str(exc)
                issue = _issue(
                    "intent_schema_invalid",
                    "模型返回的意图参数不符合 Schema",
                    retryable=attempt < max_attempts,
                    next_action="retry_llm" if attempt < max_attempts else "ask_user",
                    details={"exception_type": type(exc).__name__},
                )
                if attempt < max_attempts:
                    continue
                return LlmParseResult(None, {}, [issue], "schema_invalid", attempt)
            except Exception as exc:
                return LlmParseResult(
                    None,
                    {},
                    [
                        _issue(
                            "llm_call_failed",
                            "语义解析服务调用失败",
                            retryable=True,
                            next_action="retry_llm",
                            details={"exception_type": type(exc).__name__},
                        )
                    ],
                    "failed",
                    attempt,
                )

        return LlmParseResult(
            None,
            {},
            [_issue("llm_parse_failed", "语义解析失败", retryable=False, next_action="ask_user")],
            "failed",
            max_attempts,
        )
