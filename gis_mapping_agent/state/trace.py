"""Minimal JSONL trace for tool calls."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Any, Dict, Optional

from ..utils.config import Config


def _json_default(value: Any) -> str:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "model_dump"):
        return value.model_dump()
    return str(value)


def summarize_value(value: Any, max_length: int = 400) -> Any:
    if value is None or isinstance(value, (int, float, bool)):
        return value
    if isinstance(value, str):
        return value if len(value) <= max_length else value[: max_length - 3] + "..."
    if isinstance(value, dict):
        result = {}
        for key, item in list(value.items())[:12]:
            if key in {"gdf", "input_gdf", "output_gdf", "figure", "ax", "image", "bytes"}:
                result[key] = "<omitted>"
            else:
                result[key] = summarize_value(item, max_length=max_length)
        return result
    if isinstance(value, (list, tuple, set)):
        return [summarize_value(item, max_length=max_length) for item in list(value)[:10]]
    return summarize_value(json.dumps(value, ensure_ascii=False, default=_json_default), max_length)


@dataclass
class ToolTraceRecord:
    session_id: Optional[str]
    task_id: Optional[str]
    tool_name: str
    args: Dict[str, Any]
    result_summary: Any
    success: bool
    error: Optional[str]
    duration_ms: int
    created_at: str


class ToolTraceStore:
    def __init__(self, trace_path: Optional[Path] = None) -> None:
        self.trace_path = trace_path or (Config.OUTPUT_DIR / "traces" / "tool_trace.jsonl")
        self.trace_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()

    def append(self, record: ToolTraceRecord) -> None:
        with self._lock:
            with self.trace_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(asdict(record), ensure_ascii=False, default=_json_default) + "\n")


_TRACE_STORE = ToolTraceStore()


def record_tool_trace(
    *,
    session_id: Optional[str],
    task_id: Optional[str],
    tool_name: str,
    args: Optional[Dict[str, Any]] = None,
    result_summary: Any = None,
    success: bool = True,
    error: Optional[str] = None,
    duration_ms: int = 0,
    created_at: Optional[str] = None,
) -> None:
    _TRACE_STORE.append(
        ToolTraceRecord(
            session_id=session_id,
            task_id=task_id,
            tool_name=tool_name,
            args=summarize_value(args or {}),
            result_summary=summarize_value(result_summary),
            success=success,
            error=error,
            duration_ms=duration_ms,
            created_at=created_at or datetime.utcnow().isoformat(),
        )
    )
