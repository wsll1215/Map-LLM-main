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
    stream_llm_with_trace,
    trace_lifecycle_names,
)
from tests.api_auth import login_client


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


def test_conversation_intent_gateway_persists_nested_recognition_phases():
    from gis_mapping_agent.agent.conversational import ConversationalMappingAgent

    class BoundLLM:
        def invoke(self, _messages):
            return type(
                "Response",
                (),
                {
                    "tool_calls": [{
                        "name": "parse_map_intent",
                        "args": {
                            "task": "create_map",
                            "location": {"text": "天津市", "precision": "city"},
                            "layers": [{"role": "road"}],
                        },
                    }]
                },
            )()

    class LLM:
        def bind_tools(self, _tools, **_kwargs):
            return BoundLLM()

    request, run = _run("intent-trace-owner")
    agent = object.__new__(ConversationalMappingAgent)
    agent.session_id = f"web_session_{request.id}"
    agent.llm = LLM()

    result = agent._recognize_intent_with_trace(
        "请显示主要道路", current_state=None
    )

    assert result.status == "accepted"
    events = list(ProcessLog.objects.filter(run=run).order_by("event_seq", "id"))
    assert [event.event_type for event in events] == [
        "intent_parse",
        "intent_rule_parse",
        "intent_llm_parse",
        "intent_merge",
        "intent_validate",
    ]
    assert all(event.parent_event_id == events[0].event_id for event in events[1:])


def test_trace_lifecycle_uses_only_protocol_event_names():
    assert trace_lifecycle_names("tool_call") == ("tool_started", "tool_finished")
    assert trace_lifecycle_names("llm_generation") == ("llm_started", "llm_finished")
    assert trace_lifecycle_names("data_fetch") == ("data_fetch_started", "data_fetch_finished")
    assert trace_lifecycle_names("render") == ("render_started", "render_finished")
    assert trace_lifecycle_names("source_plan") is None


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

    embedded = record_trace_event(
        run=run,
        event_type="tool_call",
        output_data={"observation": '{"api_key":"embedded-secret","value":"ok"}'},
    )
    assert "embedded-secret" not in embedded.output_data["observation"]
    assert "[REDACTED]" in embedded.output_data["observation"]


def test_agent_phase_trace_records_one_complete_span():
    request, run = _run("phase-owner")
    from gis_mapping_agent.agent.thinking import ThinkingGISMappingAgent

    agent = ThinkingGISMappingAgent.__new__(ThinkingGISMappingAgent)
    agent.session_id = f"web_session_{request.id}"

    result = agent._run_trace_phase(
        event_type="source_plan",
        phase="data_source",
        summary="规划数据源",
        input_data={"roles": ["road"]},
        operation=lambda: {"status": "available", "feature_count": 3},
    )

    assert result["status"] == "available"
    event = ProcessLog.objects.get(run=run, event_type="source_plan")
    assert event.status == "success"
    assert event.input_data == {"roles": ["road"]}
    assert event.output_data["feature_count"] == 3
    assert event.finished_at is not None


def test_agent_phase_trace_closes_span_when_output_serialization_fails():
    request, run = _run("phase-serializer-owner")
    from gis_mapping_agent.agent.thinking import ThinkingGISMappingAgent

    agent = ThinkingGISMappingAgent.__new__(ThinkingGISMappingAgent)
    agent.session_id = f"web_session_{request.id}"

    result = agent._run_trace_phase(
        event_type="source_plan",
        phase="data_source",
        summary="规划数据源",
        input_data={},
        operation=lambda: {"status": "available"},
        output_serializer=lambda _value: (_ for _ in ()).throw(TypeError("不可序列化")),
    )

    event = ProcessLog.objects.get(run=run, event_type="source_plan")
    assert result == {"status": "available"}
    assert event.status == "error"
    assert event.error["error_code"] == "trace_serialization_error"
    assert event.finished_at is not None


def test_base_gis_tool_declares_trace_span_ownership():
    from gis_mapping_agent.tools.base import BaseGISTool

    assert BaseGISTool.owns_trace_span is True


def test_tool_span_keeps_raw_validated_and_actual_inputs_separate():
    from gis_mapping_agent.tools.base import BaseGISTool, GISToolInput, GISToolOutput

    class Input(GISToolInput):
        value: str

    class Tool(BaseGISTool):
        name: str = "trace_input_tool"
        description: str = "验证工具参数并执行地图操作"
        args_schema: type = Input

        def _execute_tool(self, input_data, run_manager=None):
            return GISToolOutput(
                success=True,
                message="执行完成",
                data={"value": input_data.value},
            )

    request, run = _run("tool-input-owner")
    result = Tool()._run(value="北京", session_id=f"web_session_{request.id}")

    assert '"success": true' in result
    event = ProcessLog.objects.get(run=run, event_type="tool_call")
    assert event.attributes["tool_description"] == "验证工具参数并执行地图操作"
    assert event.attributes["validated_input"] == {"value": "北京"}
    assert event.attributes["actual_input"] == {"value": "北京"}
    assert event.attributes["map_state_changed"] is False
    assert event.attributes["retry_count"] == 0
    assert event.output_data["tool_result"]["success"] is True


def test_agent_detects_structured_tool_failure_instead_of_marking_success():
    from gis_mapping_agent.agent.thinking import tool_observation_error

    details = tool_observation_error(
        '{"tool_result":{"success":false,"error_code":"resource_not_found",'
        '"retryable":true,"next_action":"select_valid_resource"}}'
    )

    assert details == {
        "error_code": "resource_not_found",
        "retryable": True,
        "next_action": "select_valid_resource",
    }


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


def test_llm_invocation_publishes_lifecycle_events_for_one_span(monkeypatch):
    request, _run_obj = _run("llm-lifecycle-owner")
    lifecycle_events = []

    monkeypatch.setattr(
        "mapping.trace.publish_trace_lifecycle",
        lambda event, lifecycle: lifecycle_events.append((event.event_id, lifecycle)),
    )

    invoke_llm_with_trace(
        session_id=f"web_session_{request.id}",
        invoke=lambda _messages: {"content": "完成", "tool_calls": []},
        messages=[{"role": "user", "content": "绘制地图"}],
        attributes={"model": "test-model"},
    )

    assert [lifecycle for _span_id, lifecycle in lifecycle_events] == [
        "llm_started",
        "llm_finished",
    ]
    assert lifecycle_events[0][0] == lifecycle_events[1][0]


def test_stream_llm_with_trace_emits_text_deltas_and_returns_aggregated_response():
    request, run = _run("stream-owner")
    emitted = []

    class Chunk:
        def __init__(self, content, tool_calls=None):
            self.content = content
            self.tool_calls = tool_calls or []

        def __add__(self, other):
            return Chunk(self.content + other.content, self.tool_calls + other.tool_calls)

    response = stream_llm_with_trace(
        session_id=f"web_session_{request.id}",
        stream=lambda _messages: iter([Chunk("正在"), Chunk("获取数据")]),
        messages=[{"role": "user", "content": "绘制地图"}],
        attributes={"model": "test-model", "phase": "intent"},
        on_text=emitted.append,
    )

    assert emitted == ["正在", "获取数据"]
    assert response.content == "正在获取数据"
    event = ProcessLog.objects.get(run=run, event_type="llm_generation")
    assert event.status == "success"
    assert event.output_data["content"] == "正在获取数据"


def test_stream_llm_with_trace_publishes_lifecycle_events_for_one_span(monkeypatch):
    request, _run_obj = _run("stream-lifecycle-owner")
    lifecycle_events = []

    monkeypatch.setattr(
        "mapping.trace.publish_trace_lifecycle",
        lambda event, lifecycle: lifecycle_events.append((event.event_id, lifecycle)),
    )

    stream_llm_with_trace(
        session_id=f"web_session_{request.id}",
        stream=lambda _messages: iter([{"content": "完成"}]),
        messages=[{"role": "user", "content": "绘制地图"}],
        attributes={"model": "test-model"},
    )

    assert [lifecycle for _span_id, lifecycle in lifecycle_events] == [
        "llm_started",
        "llm_finished",
    ]
    assert lifecycle_events[0][0] == lifecycle_events[1][0]


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

    client = login_client(request.user)
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

    client = login_client(request.user)
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

    client = login_client(request.user)
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

    client = login_client(request.user)
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

    client = login_client(other_user)
    response = client.get(
        f"/mapping/api/map-requests/{request.id}/runs/{run.id}/events/{event.event_id}/"
    )

    assert response.status_code == 404
