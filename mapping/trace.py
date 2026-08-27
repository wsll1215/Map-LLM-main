"""Structured trace events shared by the REST and realtime protocols."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Mapping, Optional

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from .models import MapRun, ProcessLog


REDACTED = "[REDACTED]"
SENSITIVE_KEY_PARTS = (
    "api_key",
    "access_token",
    "refresh_token",
    "token",
    "authorization",
    "cookie",
    "password",
    "secret",
    "private_key",
    "internal_path",
)


def _is_sensitive_key(key: Any) -> bool:
    normalized = str(key).lower().replace("-", "_")
    return any(part in normalized for part in SENSITIVE_KEY_PARTS)


def sanitize_trace_value(value: Any, *, key: Any = None) -> Any:
    """Return JSON-safe trace data without credentials or internal paths."""
    if key is not None and _is_sensitive_key(key):
        return REDACTED
    if isinstance(value, Mapping):
        return {
            str(item_key): sanitize_trace_value(item_value, key=item_key)
            for item_key, item_value in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return [sanitize_trace_value(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _duration_ms(started_at: datetime, finished_at: datetime) -> int:
    return max(0, int((finished_at - started_at).total_seconds() * 1000))


def record_trace_event(
    *,
    run: MapRun,
    event_type: str,
    phase: str = "",
    actor: str = "system",
    status: str = "success",
    summary: str = "",
    parent_event_id: Optional[str] = None,
    input_data: Any = None,
    output_data: Any = None,
    attributes: Any = None,
    error: Optional[Mapping[str, Any]] = None,
    started_at: Optional[datetime] = None,
    finished_at: Optional[datetime] = None,
    progress: Optional[int] = None,
) -> ProcessLog:
    """Persist one trace event and assign its sequence within the run."""
    started = started_at or timezone.now()
    finished = finished_at
    if finished is not None and finished < started:
        raise ValueError("finished_at 不能早于 started_at")

    with transaction.atomic():
        # SQLite cannot lock a row for update, but the aggregate still gives
        # deterministic ordering in normal request execution and in Postgres
        # the run row lock serializes concurrent writers.
        MapRun.objects.select_for_update().get(pk=run.pk)
        last_seq = (
            ProcessLog.objects.filter(run_id=run.pk).aggregate(last=Max("event_seq"))["last"]
            or 0
        )
        event = ProcessLog.objects.create(
            request_id=run.request_id,
            run=run,
            level="error" if status == "error" else "warning" if status == "warning" else "info",
            message=str(summary or event_type),
            step=phase,
            progress=progress,
            event_seq=last_seq + 1,
            trace_id=run.trace_id or "",
            parent_event_id=parent_event_id or "",
            event_type=event_type,
            phase=phase,
            actor=actor,
            status=status,
            started_at=started,
            finished_at=finished,
            duration_ms=_duration_ms(started, finished) if finished else None,
            input_data=sanitize_trace_value(input_data or {}),
            output_data=sanitize_trace_value(output_data or {}),
            attributes=sanitize_trace_value(attributes or {}),
            error=sanitize_trace_value(error) if error is not None else None,
        )
    return event


def start_trace_event(**kwargs: Any) -> ProcessLog:
    """Create a running event; ``finish_trace_event`` closes the same row."""
    kwargs["status"] = "running"
    kwargs["finished_at"] = None
    return record_trace_event(**kwargs)


def finish_trace_event(
    event: ProcessLog,
    *,
    status: str,
    output_data: Any = None,
    attributes: Any = None,
    error: Optional[Mapping[str, Any]] = None,
    finished_at: Optional[datetime] = None,
) -> ProcessLog:
    """Close a previously started event without creating a duplicate span."""
    finished = finished_at or timezone.now()
    started = event.started_at or finished
    event.status = status
    event.finished_at = finished
    event.duration_ms = _duration_ms(started, finished)
    event.output_data = sanitize_trace_value(output_data or {})
    if attributes:
        current = dict(event.attributes or {})
        current.update(sanitize_trace_value(attributes))
        event.attributes = current
    event.error = sanitize_trace_value(error) if error is not None else None
    event.level = "error" if status == "error" else "warning" if status == "warning" else "info"
    event.save(update_fields=[
        "status", "finished_at", "duration_ms", "output_data", "attributes", "error", "level"
    ])
    return event


def run_for_session(session_id: Optional[str]) -> Optional[MapRun]:
    """Resolve a web session to its latest run without making GIS code depend on views."""
    if not session_id:
        return None
    import re

    match = re.search(r"web_session_(\d+)", str(session_id))
    if not match:
        return None
    try:
        return MapRun.objects.filter(request_id=int(match.group(1))).order_by("-created_at", "-id").first()
    except Exception:
        return None


def repair_legacy_trace_events(run: MapRun) -> None:
    """Bind pre-MapRun process logs to a run so historical traces remain usable.

    Older deployments created ``ProcessLog`` rows without a foreign key to
    ``MapRun``.  There is no reliable run boundary in those rows, so the
    latest run is the only honest compatibility target.  The operation is
    idempotent and only touches orphaned rows for this request.
    """
    with transaction.atomic():
        locked_run = MapRun.objects.select_for_update().get(pk=run.pk)
        if not locked_run.trace_id:
            locked_run.trace_id = f"web_session_{locked_run.request_id}:legacy"
            locked_run.save(update_fields=["trace_id", "updated_at"])

        orphaned = list(
            ProcessLog.objects.filter(
                request_id=locked_run.request_id,
                run__isnull=True,
            ).order_by("created_at", "id")
        )
        if not orphaned:
            return

        last_seq = (
            ProcessLog.objects.filter(run_id=locked_run.pk)
            .aggregate(last=Max("event_seq"))
            .get("last")
            or 0
        )
        for offset, event in enumerate(orphaned, start=1):
            event.run_id = locked_run.pk
            event.trace_id = locked_run.trace_id
            event.event_seq = last_seq + offset
            event.phase = event.phase or event.step
            event.started_at = event.started_at or event.created_at
        ProcessLog.objects.bulk_update(
            orphaned,
            ["run", "trace_id", "event_seq", "phase", "started_at"],
        )


def publish_trace_event(event: ProcessLog) -> None:
    """Publish only a sanitized summary; payload details remain REST-only."""
    try:
        from .realtime import publish_map_build_event

        publish_map_build_event(
            event.request_id,
            {"type": "trace_event", "request_id": event.request_id, "trace_event": trace_event_to_dict(event)},
        )
    except Exception:
        # Observability must never break the map tool boundary.
        return


def invoke_llm_with_trace(*, session_id: Optional[str], invoke: Any, messages: Any, attributes: Any = None) -> Any:
    """Invoke an LLM while recording a single start/finish generation event."""
    run = run_for_session(session_id)
    event = None
    if run:
        event = start_trace_event(
            run=run,
            event_type="llm_generation",
            phase="intent" if not attributes or attributes.get("phase") is None else str(attributes.get("phase")),
            actor="agent",
            summary="模型推理",
            input_data=messages,
            attributes=attributes or {},
        )
        publish_trace_event(event)
    try:
        result = invoke(messages)
    except Exception as exc:
        if event:
            event = finish_trace_event(
                event,
                status="error",
                output_data={},
                error={"error_code": "llm_error", "retryable": True, "next_action": "retry_llm"},
            )
            publish_trace_event(event)
        raise
    if event:
        output = result if isinstance(result, Mapping) else {
            "content": getattr(result, "content", str(result)),
            "tool_calls": getattr(result, "tool_calls", []),
        }
        event = finish_trace_event(event, status="success", output_data=output)
        publish_trace_event(event)
    return result


def trace_event_to_dict(event: ProcessLog, *, include_payload: bool = False) -> Dict[str, Any]:
    """Serialize a ProcessLog without exposing internal storage details."""
    status = event.status or event.level or "success"
    if event.level == "error":
        status = "error"
    started_at = event.started_at or event.created_at
    payload: Dict[str, Any] = {
        "event_id": event.event_id,
        "event_seq": event.event_seq,
        "trace_id": event.trace_id or (event.run.trace_id if event.run_id and event.run else None),
        "request_id": event.request_id,
        "run_id": event.run_id,
        "parent_event_id": event.parent_event_id or None,
        "event_type": event.event_type or "process_log",
        "phase": event.phase or event.step or "",
        "actor": event.actor or "system",
        "status": status,
        "started_at": started_at.isoformat() if started_at else None,
        "finished_at": event.finished_at.isoformat() if event.finished_at else None,
        "duration_ms": event.duration_ms,
        "summary": event.message,
        "has_details": bool(
            event.input_data
            or event.output_data
            or event.attributes
            or event.error is not None
        ),
    }
    if include_payload:
        payload.update(
            {
                "input": event.input_data or {},
                "output": event.output_data or {},
                "attributes": event.attributes or {},
                "error": event.error,
            }
        )
    return payload
