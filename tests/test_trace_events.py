from datetime import timedelta
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from mapping.models import MapRequest, MapRun, ProcessLog
from mapping.trace import (
    finish_trace_event,
    invoke_llm_with_trace,
    record_trace_event,
    start_trace_event,
)


pytestmark = pytest.mark.usefixtures("django_test_database")


def _run(username="trace-owner"):
    username = f"{username}-{uuid4().hex[:8]}"
    user = get_user_model().objects.create_user(username=username, password="secret")
    request = MapRequest.objects.create(user=user, request_text="绘制地图")
    run = MapRun.objects.create(
        request=request,
        idempotency_key=f"trace-{username}",
        trace_id=f"trace-{username}",
    )
    return request, run


def test_record_trace_event_assigns_sequence_and_parent_relationship():
    request, run = _run()
    root = record_trace_event(
        run=run,
        event_type="run",
        phase="lifecycle",
        actor="system",
        status="running",
        summary="任务执行",
        input_data={"authorization": "Bearer secret"},
    )
    child = record_trace_event(
        run=run,
        event_type="tool_call",
        phase="data_source",
        actor="agent",
        status="success",
        summary="执行工具",
        parent_event_id=root.event_id,
        input_data={"api_key": "sk-secret", "location": "北京"},
        output_data={"feature_count": 2},
    )

    assert root.request_id == request.id
    assert root.event_seq == 1
    assert child.event_seq == 2
    assert child.parent_event_id == root.event_id
    assert child.trace_id == run.trace_id
    assert child.input_data == {"api_key": "[REDACTED]", "location": "北京"}


def test_record_trace_event_persists_timing_and_structured_error():
    _request, run = _run("timing-owner")
    started = timezone.now() - timedelta(seconds=1)
    finished = timezone.now()

    event = record_trace_event(
        run=run,
        event_type="error",
        phase="data_fetch",
        actor="system",
        status="error",
        summary="远程数据获取失败",
        started_at=started,
        finished_at=finished,
        error={
            "error_code": "network_error",
            "retryable": True,
            "next_action": "retry_with_backoff",
            "internal_path": "F:/private/service.py",
        },
    )

    assert event.duration_ms is not None
    assert event.duration_ms >= 900
    assert event.error["error_code"] == "network_error"
    assert event.error["retryable"] is True
    assert event.error["next_action"] == "retry_with_backoff"
    assert event.error["internal_path"] == "[REDACTED]"


def test_trace_event_does_not_store_sensitive_nested_values():
    _request, run = _run("nested-owner")

    event = record_trace_event(
        run=run,
        event_type="llm_generation",
        input_data={
            "messages": [{"content": "绘制北京"}],
            "headers": {"Authorization": "secret", "Cookie": "session"},
        },
        output_data={"text": "完成", "token": "should-not-be-kept"},
        attributes={"source_url": "https://example.test/map", "password": "secret"},
    )

    assert event.input_data["headers"] == {
        "Authorization": "[REDACTED]",
        "Cookie": "[REDACTED]",
    }
    assert event.output_data["token"] == "[REDACTED]"
    assert event.attributes["password"] == "[REDACTED]"


def test_tool_trace_event_has_one_identity_from_start_to_finish():
    _request, run = _run("tool-lifecycle-owner")
    started = start_trace_event(
        run=run,
        event_type="tool_call",
        phase="data_source",
        actor="agent",
        summary="执行数据工具",
        input_data={"location": "北京"},
        attributes={"tool_name": "fetch_roads"},
    )

    finished = finish_trace_event(
        started,
        status="success",
        output_data={"feature_count": 4},
        attributes={"validated_input": {"location": "北京"}},
    )

    assert finished.event_id == started.event_id
    assert finished.event_seq == started.event_seq
    assert finished.status == "success"
    assert finished.finished_at is not None
    assert finished.duration_ms is not None
    assert finished.output_data == {"feature_count": 4}
    assert finished.attributes["tool_name"] == "fetch_roads"
    assert finished.attributes["validated_input"] == {"location": "北京"}


def test_llm_invocation_records_input_output_and_model_metadata():
    request, run = _run("llm-owner")

    response = invoke_llm_with_trace(
        session_id=f"web_session_{request.id}",
        invoke=lambda messages: {"content": "调用工具", "tool_calls": ["fetch"]},
        messages=[{"role": "user", "content": "绘制地图"}],
        attributes={"model": "test-model"},
    )

    assert response["content"] == "调用工具"
    event = ProcessLog.objects.get(run=run, event_type="llm_generation")
    assert event.status == "success"
    assert event.attributes["model"] == "test-model"
    assert event.output_data["tool_calls"] == ["fetch"]


def test_trace_event_collection_returns_filtered_summaries_with_cursor():
    request, run = _run("api-owner")
    record_trace_event(
        run=run,
        event_type="run",
        phase="lifecycle",
        summary="任务开始",
        input_data={"prompt": "绘制地图"},
    )
    record_trace_event(
        run=run,
        event_type="error",
        phase="data_fetch",
        status="error",
        summary="请求失败",
        error={"error_code": "network_error", "retryable": True},
    )

    from django.test import Client

    client = Client()
    client.force_login(request.user)
    response = client.get(
        f"/mapping/api/map-requests/{request.id}/runs/{run.id}/events/"
        "?event_type=error&errors_only=true&limit=1"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["items"][0]["event_type"] == "error"
    assert payload["items"][0]["event_seq"] == 2
    assert "input" not in payload["items"][0]
    assert payload["items"][0]["has_details"] is True
    assert payload["next_cursor"] is None
    assert payload["total_count"] == 1


def test_trace_event_collection_repairs_legacy_logs_without_run_binding():
    request, run = _run("legacy-trace-owner")
    legacy_log = ProcessLog.objects.create(
        request=request,
        message="旧版本日志",
        step="数据源规划",
    )

    from django.test import Client

    client = Client()
    client.force_login(request.user)
    response = client.get(
        f"/mapping/api/map-requests/{request.id}/runs/{run.id}/events/"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["items"][0]["event_id"] == legacy_log.event_id
    assert payload["items"][0]["trace_id"] == run.trace_id
    legacy_log.refresh_from_db()
    assert legacy_log.run_id == run.id
    assert legacy_log.event_seq == 1


def test_trace_event_detail_returns_structured_payload_and_error():
    request, run = _run("detail-owner")
    event = record_trace_event(
        run=run,
        event_type="tool_call",
        phase="data_source",
        summary="执行数据工具",
        input_data={"api_key": "secret", "bbox": [115, 39, 117, 41]},
        output_data={"feature_count": 12},
        attributes={"provider": "OpenStreetMap/Overpass"},
        error={"error_code": "validation_error", "next_action": "retry"},
    )

    from django.test import Client

    client = Client()
    client.force_login(request.user)
    response = client.get(
        f"/mapping/api/map-requests/{request.id}/runs/{run.id}/events/{event.event_id}/"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["input"] == {"api_key": "[REDACTED]", "bbox": [115, 39, 117, 41]}
    assert payload["output"] == {"feature_count": 12}
    assert payload["attributes"]["provider"] == "OpenStreetMap/Overpass"
    assert payload["error"]["error_code"] == "validation_error"


def test_trace_event_detail_repairs_legacy_log_before_lookup():
    request, run = _run("legacy-detail-owner")
    legacy_log = ProcessLog.objects.create(
        request=request,
        message="旧版本日志详情",
        step="渲染地图",
    )

    from django.test import Client

    client = Client()
    client.force_login(request.user)
    response = client.get(
        f"/mapping/api/map-requests/{request.id}/runs/{run.id}/events/{legacy_log.event_id}/"
    )

    assert response.status_code == 200
    assert response.json()["event_id"] == legacy_log.event_id


def test_trace_event_detail_does_not_cross_request_ownership():
    request, run = _run("private-trace-owner")
    event = record_trace_event(run=run, event_type="run", summary="私有 trace")
    other_user = get_user_model().objects.create_user(
        username="private-trace-other", password="secret"
    )

    from django.test import Client

    client = Client()
    client.force_login(other_user)
    response = client.get(
        f"/mapping/api/map-requests/{request.id}/runs/{run.id}/events/{event.event_id}/"
    )

    assert response.status_code == 404
