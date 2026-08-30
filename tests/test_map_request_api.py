import os
import json
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "xy_neo4j.settings")

import django
import pytest
from django.contrib.auth import get_user_model

django.setup()

from gis_mapping_agent.models.schemas import GeometryType, LayerConfig, MapConfig, MapState, SessionInfo
from gis_mapping_agent.state import MapStateManager
from mapping.models import ChatMessage, Dataset, GeneratedMap, MapRequest, MapRun, ProcessLog
from mapping import rest_api
from mapping.views import _build_clarification_context
from tests.api_auth import login_client

pytestmark = pytest.mark.usefixtures("django_test_database")


def make_user(username):
    return get_user_model().objects.create_user(username=username, password="secret")


def test_map_request_collection_creates_request_without_running_agent():
    user = make_user("collection-owner")
    client = login_client(user)

    response = client.post(
        "/mapping/api/map-requests/",
        data='{"request_text":"绘制北京道路图"}',
        content_type="application/json",
    )

    assert response.status_code == 201
    payload = response.json()
    created = MapRequest.objects.get(pk=payload["id"])
    assert created.user_id == user.id
    assert created.request_text == "绘制北京道路图"
    assert created.status == MapRequest.STATUS_CHOICES[0][0]
    assert created.completion_report == {}


def test_process_failure_preserves_source_plan_for_run_diagnostics(monkeypatch):
    user = make_user("source-plan-failure-owner")
    request = MapRequest.objects.create(
        user=user,
        request_text="绘制定州小学",
        status="pending",
    )
    source_plan = {
        "location": {"text": "定州", "bbox": [114.2, 38.4, 114.8, 38.9]},
        "layers": [{"role": "primary_school", "status": "failed", "error_code": "network_error"}],
    }

    class FailedAgent:
        def chat(self, *_args, **_kwargs):
            return {
                "success": False,
                "message": "远程数据暂时不可用",
                "source_plan": source_plan,
            }

    monkeypatch.setattr(
        "mapping.views.get_or_create_conversation_agent",
        lambda *_args, **_kwargs: FailedAgent(),
    )
    monkeypatch.setattr("mapping.views._publish_lifecycle_event", lambda *_args, **_kwargs: None)

    from mapping.views import _process_with_map_llm

    result = _process_with_map_llm(request)

    assert result["source_plan"] == source_plan


def test_process_failure_uses_finalizer_for_terminal_status(monkeypatch):
    user = make_user("finalizer-failure-owner")
    request = MapRequest.objects.create(
        user=user,
        request_text="绘制未知区域",
        status="pending",
    )
    calls = []

    class FailedAgent:
        def chat(self, *_args, **_kwargs):
            return {
                "success": False,
                "status": "failed",
                "message": "地点无法解析",
                "source_plan": {"issues": ["location_not_resolved"], "layers": []},
            }

    class FinalResult:
        status = "failed"
        error_code = "location_not_resolved"
        error_message = "地点无法解析"
        completion_report = {"missing_layers": ["boundary"]}

    monkeypatch.setattr(
        "mapping.views.get_or_create_conversation_agent",
        lambda *_args, **_kwargs: FailedAgent(),
    )
    monkeypatch.setattr(
        "mapping.views._finalize_map_request",
        lambda *_args, **_kwargs: calls.append(True) or FinalResult(),
    )
    monkeypatch.setattr("mapping.views._publish_lifecycle_event", lambda *_args, **_kwargs: None)

    from mapping.views import _process_with_map_llm

    result = _process_with_map_llm(request)

    assert calls == [True]
    assert result["status"] == "failed"
    assert result["error_code"] == "location_not_resolved"


def test_unhandled_agent_exception_uses_finalizer_for_terminal_status(monkeypatch):
    from types import SimpleNamespace
    from mapping.views import _process_with_map_llm

    user = make_user("unhandled-agent-error-owner")
    request = MapRequest.objects.create(
        user=user,
        request_text="绘制异常区域",
        status="processing",
    )
    calls = []

    def raise_agent(*_args, **_kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr("mapping.views.get_or_create_conversation_agent", raise_agent)
    monkeypatch.setattr(
        "mapping.views._finalize_map_request",
        lambda *_args, **_kwargs: calls.append(True)
        or SimpleNamespace(
            status="failed",
            error_code="internal_error",
            error_message="处理过程中发生错误: provider unavailable",
            completion_report={},
        ),
    )
    monkeypatch.setattr("mapping.views._publish_lifecycle_event", lambda *_args, **_kwargs: None)

    result = _process_with_map_llm(request)

    assert calls == [True]
    assert result["status"] == "failed"


def test_background_agent_exception_uses_finalizer_for_terminal_status(monkeypatch):
    from types import SimpleNamespace
    from mapping.views import _process_map_request_in_background

    user = make_user("background-agent-error-owner")
    request = MapRequest.objects.create(
        user=user,
        request_text="绘制后台异常区域",
        status="processing",
    )
    run = MapRun.objects.create(
        request=request,
        idempotency_key="background-agent-error",
        trace_id="trace-background-error",
    )
    calls = []

    monkeypatch.setattr(
        "mapping.views._process_with_map_llm",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("background provider unavailable")
        ),
    )

    def fake_finalize(map_request, *_args, **_kwargs):
        calls.append(map_request.id)
        map_request.status = "failed"
        map_request.error_message = "后台制图失败"
        map_request.result_message = "后台制图失败"
        map_request.save(update_fields=["status", "error_message", "result_message", "updated_at"])
        return SimpleNamespace(
            status="failed",
            error_code="internal_error",
            error_message="后台制图失败",
            completion_report={},
        )

    monkeypatch.setattr("mapping.views._finalize_map_request", fake_finalize)
    monkeypatch.setattr("mapping.views._publish_lifecycle_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("mapping.views._record_error_event", lambda *_args, **_kwargs: None)

    _process_map_request_in_background(request.id, run.id)

    assert calls == [request.id]


def test_dispatch_failure_uses_finalizer_for_terminal_status(monkeypatch):
    from types import SimpleNamespace
    from mapping.views import _record_dispatch_failure

    user = make_user("dispatch-error-owner")
    request = MapRequest.objects.create(
        user=user,
        request_text="绘制提交失败区域",
        status="processing",
    )
    run = MapRun.objects.create(
        request=request,
        idempotency_key="dispatch-error",
        trace_id="trace-dispatch-error",
    )
    calls = []

    def fake_finalize(map_request, *_args, **_kwargs):
        calls.append(map_request.id)
        map_request.status = "failed"
        map_request.error_message = "任务提交失败"
        map_request.result_message = "任务提交失败"
        map_request.save(update_fields=["status", "error_message", "result_message", "updated_at"])
        return SimpleNamespace(
            status="failed",
            error_code="worker_unavailable",
            error_message="任务提交失败",
            completion_report={},
        )

    monkeypatch.setattr("mapping.views._finalize_map_request", fake_finalize)
    monkeypatch.setattr("mapping.views._record_error_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("mapping.views._publish_lifecycle_event", lambda *_args, **_kwargs: None)

    _record_dispatch_failure(request, run, RuntimeError("queue unavailable"))

    assert calls == [request.id]


def test_background_conversation_exception_uses_finalizer_for_terminal_status(monkeypatch):
    from types import SimpleNamespace
    from mapping.views import _continue_conversation_in_background

    user = make_user("background-conversation-error-owner")
    request = MapRequest.objects.create(
        user=user,
        request_text="绘制连续调整区域",
        status="processing",
    )
    run = MapRun.objects.create(
        request=request,
        idempotency_key="conversation-error",
        trace_id="trace-conversation-error",
    )
    calls = []

    class FailedAgent:
        def chat(self, *_args, **_kwargs):
            raise RuntimeError("conversation provider unavailable")

    monkeypatch.setattr(
        "mapping.views.get_or_create_conversation_agent",
        lambda *_args, **_kwargs: FailedAgent(),
    )

    def fake_finalize(map_request, *_args, **_kwargs):
        calls.append(map_request.id)
        map_request.status = "failed"
        map_request.error_message = "继续对话失败"
        map_request.result_message = "继续对话失败"
        map_request.save(update_fields=["status", "error_message", "result_message", "updated_at"])
        return SimpleNamespace(
            status="failed",
            error_code="internal_error",
            error_message="继续对话失败",
            completion_report={},
        )

    monkeypatch.setattr("mapping.views._finalize_map_request", fake_finalize)
    monkeypatch.setattr("mapping.views._publish_lifecycle_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("mapping.views._record_error_event", lambda *_args, **_kwargs: None)

    _continue_conversation_in_background(request.id, "继续调整", run.id)

    assert calls == [request.id]


def test_unavailable_agent_does_not_mark_request_completed_without_artifact(monkeypatch):
    from types import SimpleNamespace
    from mapping.views import _handle_map_llm_unavailable

    user = make_user("unavailable-agent-owner")
    request = MapRequest.objects.create(
        user=user,
        request_text="绘制依赖不可用区域",
        status="pending",
    )
    calls = []

    def fake_finalize(map_request, *_args, **_kwargs):
        calls.append(map_request.id)
        map_request.status = "failed"
        map_request.result_message = "Map-LLM 不可用"
        map_request.error_message = "Map-LLM 不可用"
        map_request.save(update_fields=["status", "result_message", "error_message", "updated_at"])
        return SimpleNamespace(
            status="failed",
            error_code="internal_error",
            error_message="Map-LLM 不可用",
            completion_report={},
        )

    monkeypatch.setattr("mapping.views._finalize_map_request", fake_finalize)
    monkeypatch.setattr("mapping.views._publish_lifecycle_event", lambda *_args, **_kwargs: None)

    _handle_map_llm_unavailable(request)

    assert calls == [request.id]


def test_finalizer_rejects_path_inferred_source_without_registered_dataset(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from django.test import override_settings
    from PIL import Image

    from mapping.finalization import SpatialValidation
    from mapping.views import _finalize_map_request

    user = make_user("unregistered-source-finalizer-owner")
    request = MapRequest.objects.create(
        user=user,
        request_text="绘制甲市道路",
        status="processing",
    )
    output = tmp_path / "map.png"
    Image.new("RGB", (2, 2), "white").save(output)
    GeneratedMap.objects.create(
        request=request,
        filename="map.png",
        file_path="map.png",
        version=1,
    )
    state = SimpleNamespace(
        config=SimpleNamespace(extent=[120, 30, 121, 31]),
        layers=[
            SimpleNamespace(
                name="道路",
                data_source="data_cache/remote_roads/road.geojson",
                data_source_meta={},
                data=None,
                feature_count=4,
                extent=[120, 30, 121, 31],
            )
        ],
    )

    monkeypatch.setattr(
        "gis_mapping_agent.state.get_state_manager",
        lambda: SimpleNamespace(load_state=lambda _session_id: state),
    )
    monkeypatch.setattr(
        "mapping.finalization.validate_source_spatial",
        lambda *_args, **_kwargs: SpatialValidation(
            role="road",
            feature_count=4,
            geometry_valid=True,
            spatial_valid=True,
        ),
    )

    with override_settings(GENERATED_MAPS_DIR=tmp_path):
        result = _finalize_map_request(
            request,
            {
                "success": True,
                "response": "地图已生成",
                "source_plan": {
                    "layers": [{
                        "role": "road",
                        "status": "available",
                        "dataset_id": "missing-road-dataset",
                    }],
                    "location": {"bbox": [120, 30, 121, 31]},
                },
            },
        )

    assert result.status == "failed"
    assert "road" in result.completion_report["missing_layers"]


def test_runtime_dataset_lookup_returns_registered_available_dataset(monkeypatch):
    from types import SimpleNamespace
    from mapping.views import _runtime_dataset_for_layer

    dataset = SimpleNamespace(
        dataset_id="registered-road",
        source_type=Dataset.SOURCE_LOCAL,
        feature_count=3,
    )
    manager = SimpleNamespace(
        filter=lambda **_kwargs: SimpleNamespace(first=lambda: dataset)
    )
    monkeypatch.setattr(
        "mapping.views.Dataset",
        SimpleNamespace(STATUS_AVAILABLE=Dataset.STATUS_AVAILABLE, objects=manager),
    )

    resolved = _runtime_dataset_for_layer({"dataset_id": dataset.dataset_id})

    assert resolved is not None
    assert resolved.dataset_id == dataset.dataset_id


def test_runtime_dataset_lookup_fails_closed_when_feature_count_query_fails(monkeypatch):
    from mapping.views import _runtime_dataset_for_layer

    class Features:
        def count(self):
            raise RuntimeError("database connection lost")

    dataset = SimpleNamespace(
        dataset_id="registered-road-db-error",
        source_type=Dataset.SOURCE_LOCAL,
        feature_count=3,
        features=Features(),
    )
    manager = SimpleNamespace(
        filter=lambda **_kwargs: SimpleNamespace(first=lambda: dataset)
    )
    monkeypatch.setattr(
        "mapping.views.Dataset",
        SimpleNamespace(STATUS_AVAILABLE=Dataset.STATUS_AVAILABLE, objects=manager),
    )

    assert _runtime_dataset_for_layer({"dataset_id": dataset.dataset_id}) is None


def test_map_request_creation_normalizes_null_completion_report():
    user = make_user("null-completion-report-owner")

    created = MapRequest.objects.create(
        user=user,
        request_text="绘制定州道路和小学",
        completion_report=None,
    )

    created.refresh_from_db()
    assert created.completion_report == {}


def test_legacy_create_request_initializes_completion_report():
    user = make_user("legacy-create-owner")

    response = login_client(user).post(
        "/mapping/api/create-request/",
        data=json.dumps({"request_text": "绘制定州市地图"}),
        content_type="application/json",
    )

    assert response.status_code == 200
    created = MapRequest.objects.get(pk=response.json()["request_id"])
    assert created.completion_report == {}


def test_request_detail_exposes_needs_clarification_payload():
    user = make_user("clarification-owner-regression")
    request = MapRequest.objects.create(
        user=user,
        request_text="北京",
        status="needs_clarification",
        result_message="你想绘制哪里的哪类地图？",
        clarification_data={
            "missing_fields": ["map_scope", "layer_type"],
            "suggestions": ["北京行政区划图"],
        },
    )

    response = login_client(user).get(f"/mapping/api/map-requests/{request.id}/")

    assert response.status_code == 200
    assert response.json()["status"] == "needs_clarification"
    assert response.json()["clarification"]["missing_fields"] == ["map_scope", "layer_type"]


def test_process_logs_include_the_current_run_trace_id():
    user = make_user("process-log-trace-owner")
    request = MapRequest.objects.create(user=user, request_text="绘制北京道路图", status="processing")
    run = MapRun.objects.create(
        request=request,
        idempotency_key="process-log-trace",
        trace_id="trace-process-log-1",
    )
    ProcessLog.objects.create(request=request, run=run, step="数据源规划", message="开始规划")

    response = login_client(user).get(f"/mapping/api/process-logs/{request.id}/")

    assert response.status_code == 200
    assert response.json()["logs"][0]["trace_id"] == run.trace_id


def test_process_logs_keep_trace_ids_for_multiple_runs():
    user = make_user("process-log-multi-run-owner")
    request = MapRequest.objects.create(user=user, request_text="连续调整地图", status="completed")
    first_run = MapRun.objects.create(request=request, idempotency_key="process-log-run-1", trace_id="trace-1")
    second_run = MapRun.objects.create(request=request, idempotency_key="process-log-run-2", trace_id="trace-2")
    ProcessLog.objects.create(request=request, run=first_run, step="第一次", message="旧日志")
    ProcessLog.objects.create(request=request, run=second_run, step="第二次", message="新日志")

    response = login_client(user).get(f"/mapping/api/process-logs/{request.id}/")

    assert response.status_code == 200
    assert [item["trace_id"] for item in response.json()["logs"]] == ["trace-1", "trace-2"]


def test_process_logs_can_be_scoped_to_one_run():
    user = make_user("process-log-scoped-owner")
    request = MapRequest.objects.create(user=user, request_text="查看当前执行")
    first_run = MapRun.objects.create(request=request, idempotency_key="scoped-run-1", trace_id="trace-old")
    second_run = MapRun.objects.create(request=request, idempotency_key="scoped-run-2", trace_id="trace-current")
    ProcessLog.objects.create(request=request, run=first_run, step="旧步骤", message="旧日志")
    ProcessLog.objects.create(request=request, run=second_run, step="当前步骤", message="当前日志")

    response = login_client(user).get(
        f"/mapping/api/process-logs/{request.id}/?run_id={second_run.id}"
    )

    assert response.status_code == 200
    assert [item["message"] for item in response.json()["logs"]] == ["当前日志"]
    assert response.json()["logs"][0]["run_id"] == second_run.id


def test_process_logs_rejects_a_run_from_another_request():
    owner = make_user("process-log-scoped-private-owner")
    other = make_user("process-log-scoped-private-other")
    request = MapRequest.objects.create(user=owner, request_text="私有执行")
    foreign_request = MapRequest.objects.create(user=other, request_text="另一条执行")
    foreign_run = MapRun.objects.create(request=foreign_request, idempotency_key="foreign-run")

    response = login_client(owner).get(
        f"/mapping/api/process-logs/{request.id}/?run_id={foreign_run.id}"
    )

    assert response.status_code == 404


def test_realtime_process_log_event_contains_the_bound_run_context(monkeypatch):
    user = make_user("realtime-process-log-trace-owner")
    request = MapRequest.objects.create(user=user, request_text="绘制北京道路图", status="processing")
    run = MapRun.objects.create(
        request=request,
        idempotency_key="realtime-process-log-trace",
        trace_id="trace-realtime-1",
    )
    published = []
    monkeypatch.setattr(
        "mapping.views.publish_map_build_event",
        lambda request_id, payload: published.append((request_id, payload)),
    )

    from mapping.views import _publish_process_log_event

    _publish_process_log_event(request, "开始规划", step="数据源规划", run=run)

    assert published[0][0] == request.id
    assert published[0][1]["run_id"] == run.id
    assert published[0][1]["trace_id"] == run.trace_id


def test_lifecycle_done_does_not_duplicate_terminal_trace_event(monkeypatch):
    user = make_user("terminal-trace-owner")
    request = MapRequest.objects.create(
        user=user,
        request_text="绘制北京道路图",
        status="completed",
    )
    run = MapRun.objects.create(
        request=request,
        idempotency_key="terminal-trace",
        trace_id="trace-terminal",
    )
    monkeypatch.setattr("mapping.views.publish_map_build_event", lambda *_args: "1")

    from mapping.views import _publish_lifecycle_event

    _publish_lifecycle_event(request, "request_completed", message="地图已完成")
    _publish_lifecycle_event(request, "done", status="completed", message="地图已完成")

    events = list(run.process_logs.order_by("event_seq"))
    assert len(events) == 1
    assert events[0].event_type == "run_finished"
    assert events[0].status == "success"


def test_continue_conversation_returns_new_stream_cursor(monkeypatch):
    user = make_user("continue-owner")
    request = MapRequest.objects.create(
        user=user,
        request_text="绘制石家庄地图",
        status="completed",
    )
    monkeypatch.setattr("mapping.views.MAP_LLM_AVAILABLE", True)
    monkeypatch.setattr(
        "mapping.views._publish_lifecycle_event",
        lambda *_args, **_kwargs: "stream-42",
    )
    monkeypatch.setattr("mapping.views.dispatch_conversation", lambda *_args: None)

    response = login_client(user).post(
        "/mapping/api/continue-conversation/",
        data='{"request_id": %d, "message": "把高铁路线画出来"}' % request.id,
        content_type="application/json",
    )

    assert response.status_code == 200
    assert response.json()["stream_after_id"] == "stream-42"


def test_process_request_marks_run_failed_when_dispatch_raises(monkeypatch):
    user = make_user("legacy-dispatch-failure-owner")
    request = MapRequest.objects.create(user=user, request_text="绘制北京道路图")
    monkeypatch.setattr("mapping.views.MAP_LLM_AVAILABLE", True)
    monkeypatch.setattr(
        "mapping.views.dispatch_map_request",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("Redis unavailable")),
    )

    response = login_client(user).post(
        "/mapping/api/process-request/",
        data=json.dumps({"request_id": request.id}),
        content_type="application/json",
    )

    request.refresh_from_db()
    run = request.runs.get()
    assert response.status_code == 503
    assert request.status == "failed"
    assert "Redis unavailable" in request.error_message
    assert run.status == MapRun.STATUS_FAILED
    assert "Redis unavailable" in run.error_message


def test_process_request_assigns_trace_id_before_dispatch(monkeypatch):
    user = make_user("initial-trace-owner")
    request = MapRequest.objects.create(user=user, request_text="绘制北京道路图")
    monkeypatch.setattr("mapping.views.MAP_LLM_AVAILABLE", True)
    monkeypatch.setattr("mapping.views.dispatch_map_request", lambda *_args: None)

    response = login_client(user).post(
        "/mapping/api/process-request/",
        data=json.dumps({"request_id": request.id}),
        content_type="application/json",
    )

    assert response.status_code == 200
    assert request.runs.get().trace_id == f"web_session_{request.id}:create"


def test_legacy_run_creation_uses_admission_lock_for_process_and_continue(monkeypatch):
    user = make_user("admission-lock-owner")
    process_request = MapRequest.objects.create(
        user=user, request_text="绘制北京道路图"
    )
    continue_request = MapRequest.objects.create(
        user=user, request_text="绘制北京道路图", status="completed"
    )
    admissions = []

    @contextmanager
    def admission():
        admissions.append(True)
        yield

    monkeypatch.setattr("mapping.views.active_run_admission", admission)
    monkeypatch.setattr("mapping.views.MAP_LLM_AVAILABLE", True)
    monkeypatch.setattr("mapping.views.dispatch_map_request", lambda *_args: None)
    monkeypatch.setattr("mapping.views.dispatch_conversation", lambda *_args: None)

    client = login_client(user)
    process_response = client.post(
        "/mapping/api/process-request/",
        data=json.dumps({"request_id": process_request.id}),
        content_type="application/json",
    )
    continue_response = client.post(
        "/mapping/api/continue-conversation/",
        data=json.dumps(
            {"request_id": continue_request.id, "message": "补充道路"}
        ),
        content_type="application/json",
    )

    assert process_response.status_code == 200
    assert continue_response.status_code == 200
    assert admissions == [True, True]


def test_continue_conversation_marks_run_failed_when_dispatch_raises(monkeypatch):
    user = make_user("legacy-continue-dispatch-failure-owner")
    request = MapRequest.objects.create(
        user=user,
        request_text="绘制北京道路图",
        status="completed",
    )
    monkeypatch.setattr("mapping.views.MAP_LLM_AVAILABLE", True)
    monkeypatch.setattr(
        "mapping.views.dispatch_conversation",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("Redis unavailable")),
    )

    response = login_client(user).post(
        "/mapping/api/continue-conversation/",
        data=json.dumps(
            {"request_id": request.id, "message": "标注清华大学的位置"}
        ),
        content_type="application/json",
    )

    request.refresh_from_db()
    run = request.runs.get()
    assert response.status_code == 503
    assert request.status == "failed"
    assert "Redis unavailable" in request.error_message
    assert run.status == MapRun.STATUS_FAILED
    assert "Redis unavailable" in run.error_message


def test_background_conversation_failure_persists_current_result_message(monkeypatch):
    user = make_user("conversation-failure-result-owner")
    request = MapRequest.objects.create(
        user=user,
        request_text="绘制北京道路图",
        status="completed",
        result_message="上一轮地图已生成",
    )
    run = MapRun.objects.create(request=request, idempotency_key="failure-result")

    class FailedAgent:
        def chat(self, *_args, **_kwargs):
            return {
                "success": False,
                "response": "本轮调整失败：数据源不可用",
                "message": "数据源不可用",
            }

    monkeypatch.setattr(
        "mapping.views.get_or_create_conversation_agent",
        lambda *_args, **_kwargs: FailedAgent(),
    )
    monkeypatch.setattr("mapping.views._clear_realtime_previews", lambda *_args: None)
    monkeypatch.setattr("mapping.views._publish_lifecycle_event", lambda *_args, **_kwargs: None)

    from mapping.views import _continue_conversation_in_background

    _continue_conversation_in_background(request.id, "标注清华大学的位置", run.id)

    request.refresh_from_db()
    assert request.status == "failed"
    assert request.result_message == "本轮调整失败：数据源不可用"
    assert request.error_message == "本轮调整失败：数据源不可用"


def test_background_conversation_uses_finalizer_for_partial_result(monkeypatch, tmp_path):
    user = make_user("conversation-finalizer-owner")
    request = MapRequest.objects.create(
        user=user,
        request_text="绘制北京道路图",
        status="completed",
        result_message="上一轮地图已生成",
    )
    run = MapRun.objects.create(request=request, idempotency_key="partial-adjustment")
    events = []

    class SuccessfulAgent:
        def chat(self, *_args, **_kwargs):
            return {
                "success": True,
                "response": "已添加道路图层",
                "agent_output": "已添加道路图层",
            }

    class FinalResult:
        status = "partial"
        completion_report = {
            "missing_layers": ["road"],
            "available_layers": ["boundary"],
        }
        error_message = "缺少必需图层：road"
        error_code = None
        map_version = 2

    monkeypatch.setattr(
        "mapping.views.get_or_create_conversation_agent",
        lambda *_args, **_kwargs: SuccessfulAgent(),
    )
    monkeypatch.setattr("mapping.views._save_generated_map_info", lambda *_args: None)
    def fake_finalize(map_request, _response, **_kwargs):
        final_result = FinalResult()
        map_request.status = final_result.status
        map_request.completion_report = final_result.completion_report
        map_request.error_message = ""
        map_request.result_message = final_result.error_message
        map_request.save(
            update_fields=[
                "status",
                "completion_report",
                "error_message",
                "result_message",
                "updated_at",
            ]
        )
        return final_result

    monkeypatch.setattr("mapping.views._finalize_map_request", fake_finalize)
    monkeypatch.setattr(
        "mapping.views._publish_lifecycle_event",
        lambda _request, event, **payload: events.append((event, payload)),
    )
    monkeypatch.setattr("mapping.views._schedule_realtime_preview_cleanup", lambda *_args: None)

    from mapping.views import _continue_conversation_in_background

    _continue_conversation_in_background(request.id, "把道路画出来", run.id)

    request.refresh_from_db()
    run.refresh_from_db()
    assert request.status == "partial"
    assert request.completion_report["missing_layers"] == ["road"]
    assert run.status == MapRun.STATUS_PARTIAL
    assert run.completion_report["missing_layers"] == ["road"]
    assert any(event == "request_partial" for event, _payload in events)
    assert not any(event == "request_completed" for event, _payload in events)


def test_clarification_continuation_passes_all_user_turns_to_agent(monkeypatch):
    user = make_user("clarification-context-owner")
    request = MapRequest.objects.create(
        user=user,
        request_text="帮我画个图",
        status="needs_clarification",
        clarification_data={"missing_fields": ["map_scope", "layer_type"]},
    )
    ChatMessage.objects.create(request=request, message_type="user", content="帮我画个图")
    ChatMessage.objects.create(request=request, message_type="user", content="北京")
    captured = {}
    monkeypatch.setattr("mapping.views.MAP_LLM_AVAILABLE", True)
    monkeypatch.setattr(
        "mapping.views._publish_lifecycle_event", lambda *_args, **_kwargs: "stream-43"
    )
    monkeypatch.setattr(
        "mapping.views.dispatch_conversation",
        lambda *args, **kwargs: captured.update(args=args, kwargs=kwargs),
    )

    response = login_client(user).post(
        "/mapping/api/continue-conversation/",
        data=json.dumps({"request_id": request.id, "message": "道路图"}),
        content_type="application/json",
    )

    assert response.status_code == 200
    assert captured["args"][3] is True
    request.refresh_from_db()
    context = _build_clarification_context(request, "道路图")
    assert "帮我画个图" in context
    assert "北京" in context
    assert "道路图" in context


def test_map_request_collection_lists_only_current_users_requests():
    owner = make_user("list-owner")
    other = make_user("list-other")
    own_request = MapRequest.objects.create(user=owner, request_text="own")
    MapRequest.objects.create(user=other, request_text="other")

    response = login_client(owner).get("/mapping/api/map-requests/")

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == [own_request.id]


def test_map_request_collection_uses_cursor_for_next_page():
    user = make_user("cursor-owner")
    first = MapRequest.objects.create(user=user, request_text="first")
    second = MapRequest.objects.create(user=user, request_text="second")
    client = login_client(user)

    first_page = client.get("/mapping/api/map-requests/?limit=1")
    assert first_page.status_code == 200
    assert first_page.json()["items"][0]["id"] == second.id
    cursor = first_page.json()["next_cursor"]
    assert cursor

    second_page = client.get(f"/mapping/api/map-requests/?limit=1&cursor={cursor}")

    assert second_page.status_code == 200
    assert [item["id"] for item in second_page.json()["items"]] == [first.id]
    assert second_page.json()["next_cursor"] is None


def test_map_request_collection_rejects_invalid_cursor():
    user = make_user("invalid-cursor-owner")

    response = login_client(user).get("/mapping/api/map-requests/?cursor=not-valid")

    assert response.status_code == 400


def test_map_request_detail_hides_other_users_request():
    owner = make_user("detail-owner")
    other = make_user("detail-other")
    request = MapRequest.objects.create(user=other, request_text="private")

    response = login_client(owner).get(f"/mapping/api/map-requests/{request.id}/")

    assert response.status_code == 404


def test_map_request_detail_includes_latest_run_and_terminal_messages():
    user = make_user("detail-status-owner")
    map_request = MapRequest.objects.create(
        user=user,
        request_text="标注清华大学",
        status="failed",
        result_message="",
        error_message="数据源不可用",
    )
    run = MapRun.objects.create(request=map_request, idempotency_key="detail-status")
    run.transition_to(MapRun.STATUS_RUNNING)
    run.transition_to(MapRun.STATUS_FAILED, error_message="数据源不可用")

    response = login_client(user).get(f"/mapping/api/map-requests/{map_request.id}/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["error_message"] == "数据源不可用"
    assert payload["latest_run"]["id"] == run.id
    assert payload["latest_run"]["status"] == MapRun.STATUS_FAILED
    assert payload["latest_run"]["error_message"] == "数据源不可用"


def test_map_request_patch_updates_request_fields_but_not_status():
    user = make_user("patch-owner")
    map_request = MapRequest.objects.create(user=user, request_text="old")

    response = login_client(user).patch(
        f"/mapping/api/map-requests/{map_request.id}/",
        data='{"title":"北京道路","request_text":"new","status":"completed"}',
        content_type="application/json",
    )

    assert response.status_code == 400
    map_request.refresh_from_db()
    assert map_request.title == ""
    assert map_request.request_text == "old"


def test_map_request_delete_returns_no_content():
    user = make_user("delete-owner")
    map_request = MapRequest.objects.create(user=user, request_text="delete me")

    response = login_client(user).delete(f"/mapping/api/map-requests/{map_request.id}/")

    assert response.status_code == 204
    assert not MapRequest.objects.filter(pk=map_request.id).exists()


def test_run_creation_requires_idempotency_key():
    user = make_user("run-key-owner")
    map_request = MapRequest.objects.create(user=user, request_text="run")

    response = login_client(user).post(
        f"/mapping/api/map-requests/{map_request.id}/runs/",
        data="{}",
        content_type="application/json",
    )

    assert response.status_code == 400
    assert not MapRun.objects.filter(request=map_request).exists()


def test_run_creation_is_idempotent_for_same_request_and_key():
    user = make_user("run-idempotent-owner")
    map_request = MapRequest.objects.create(user=user, request_text="run")
    client = login_client(user)
    headers = {"HTTP_IDEMPOTENCY_KEY": "run-once"}

    first = client.post(
        f"/mapping/api/map-requests/{map_request.id}/runs/",
        data="{}",
        content_type="application/json",
        **headers,
    )
    second = client.post(
        f"/mapping/api/map-requests/{map_request.id}/runs/",
        data="{}",
        content_type="application/json",
        **headers,
    )

    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert MapRun.objects.filter(request=map_request).count() == 1


def test_run_detail_allows_cancellation_but_not_client_completion():
    user = make_user("run-state-owner")
    map_request = MapRequest.objects.create(user=user, request_text="run")
    run = MapRun.objects.create(request=map_request, idempotency_key="state-run")
    client = login_client(user)

    cancel = client.patch(
        f"/mapping/api/map-requests/{map_request.id}/runs/{run.id}/",
        data='{"status":"cancel_requested"}',
        content_type="application/json",
    )
    complete = client.patch(
        f"/mapping/api/map-requests/{map_request.id}/runs/{run.id}/",
        data='{"status":"completed"}',
        content_type="application/json",
    )

    assert cancel.status_code == 200
    assert cancel.json()["status"] == MapRun.STATUS_CANCEL_REQUESTED
    assert complete.status_code == 400
    run.refresh_from_db()
    assert run.status == MapRun.STATUS_CANCEL_REQUESTED


def test_run_creation_dispatches_the_created_run(monkeypatch):
    user = make_user("run-dispatch-owner")
    map_request = MapRequest.objects.create(user=user, request_text="run")
    dispatched = []
    monkeypatch.setattr(
        rest_api,
        "dispatch_map_request",
        lambda request_id, run_id: dispatched.append((request_id, run_id)),
    )

    response = login_client(user).post(
        f"/mapping/api/map-requests/{map_request.id}/runs/",
        data="{}",
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY="dispatch-run",
    )

    run = MapRun.objects.get(request=map_request)
    assert response.status_code == 201
    assert dispatched == [(map_request.id, run.id)]


def test_run_creation_reports_worker_submission_failure(monkeypatch):
    user = make_user("run-submit-failure-owner")
    map_request = MapRequest.objects.create(user=user, request_text="run")

    def fail_dispatch(*args):
        raise RuntimeError("Redis unavailable")

    monkeypatch.setattr(rest_api, "dispatch_map_request", fail_dispatch)
    response = login_client(user).post(
        f"/mapping/api/map-requests/{map_request.id}/runs/",
        data="{}",
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY="failed-submit",
    )

    run = MapRun.objects.get(request=map_request)
    assert response.status_code == 503
    assert response.json()["error"] == "任务提交失败，请稍后重试"
    assert run.status == MapRun.STATUS_FAILED


def test_run_detail_hides_run_from_other_request_owner():
    owner = make_user("run-private-owner")
    other = make_user("run-private-other")
    map_request = MapRequest.objects.create(user=other, request_text="private")
    run = MapRun.objects.create(request=map_request, idempotency_key="private-run")

    response = login_client(owner).get(
        f"/mapping/api/map-requests/{map_request.id}/runs/{run.id}/"
    )

    assert response.status_code == 404


def test_request_detail_exposes_agent_trace_id():
    user = make_user("trace-detail-owner")
    map_request = MapRequest.objects.create(user=user, request_text="trace")
    MapRun.objects.create(
        request=map_request,
        idempotency_key="trace-detail",
        trace_id="web_session_7:create",
    )

    response = login_client(user).get(f"/mapping/api/map-requests/{map_request.id}/")

    assert response.status_code == 200
    assert response.json()["latest_run"]["trace_id"] == "web_session_7:create"


def seed_snapshot(tmp_path, map_request):
    manager = MapStateManager(str(tmp_path / "map_states.db"))
    state = MapState(
        config=MapConfig(map_id="map-1", title="Beijing", extent=[115, 39, 117, 41]),
        session_info=SessionInfo(session_id=f"web_session_{map_request.id}"),
        spec_json={"schema_version": 1, "map_id": "map-1", "version": 1},
        spec_hash="sha256:map-1",
        latest_event_seq=4,
        layers=[
            LayerConfig(
                layer_id="roads",
                name="Roads",
                geometry_type=GeometryType.LINE,
                data_source="data/roads.shp",
                feature_count=10,
                extent=[115, 39, 117, 41],
                render_mode="geojson",
                data_url="/mapping/api/map-requests/1/snapshots/1/layers/roads/",
                data_source_meta={"dataset_id": "local-roads"},
            )
        ],
    )
    assert manager.save_state(state)
    return manager


def test_snapshot_current_returns_spec_and_layer_manifests_without_geojson(tmp_path, monkeypatch):
    user = make_user("snapshot-owner")
    map_request = MapRequest.objects.create(user=user, request_text="snapshot")
    manager = seed_snapshot(tmp_path, map_request)
    monkeypatch.setattr(rest_api, "get_state_manager", lambda: manager)

    response = login_client(user).get(
        f"/mapping/api/map-requests/{map_request.id}/snapshots/current/"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["version"] == 1
    assert payload["spec_hash"] == "sha256:map-1"
    assert payload["layers"][0]["id"] == "roads"
    assert "geojson" not in payload["layers"][0]
    etag = response["ETag"]
    assert etag

    cached = login_client(user).get(
        f"/mapping/api/map-requests/{map_request.id}/snapshots/current/",
        HTTP_IF_NONE_MATCH=etag,
    )

    assert cached.status_code == 304


def test_layer_manifest_does_not_infer_remote_source_from_cache_path():
    layer = SimpleNamespace(
        layer_id="unregistered",
        name="道路",
        geometry_type="line",
        feature_count=1,
        extent=[120, 30, 121, 31],
        data_hash="hash",
        render_mode="geojson",
        data_url=None,
        data_source="data_cache/remote_roads/road.geojson",
        data_source_meta={},
        render_spec=None,
        visible=True,
        z_order=1,
    )

    payload = rest_api._layer_manifest(layer, 1)

    assert payload["data_source_meta"]["source_type"] is None
    assert payload["data_source_meta"]["status"] == "unavailable"


def test_snapshot_version_and_layer_are_user_scoped(tmp_path, monkeypatch):
    owner = make_user("snapshot-private-owner")
    other = make_user("snapshot-private-other")
    map_request = MapRequest.objects.create(user=owner, request_text="snapshot")
    manager = seed_snapshot(tmp_path, map_request)
    monkeypatch.setattr(rest_api, "get_state_manager", lambda: manager)

    version = login_client(owner).get(
        f"/mapping/api/map-requests/{map_request.id}/snapshots/1/"
    )
    layer = login_client(owner).get(
        f"/mapping/api/map-requests/{map_request.id}/snapshots/1/layers/roads/"
    )
    forbidden = login_client(other).get(
        f"/mapping/api/map-requests/{map_request.id}/snapshots/current/"
    )

    assert version.status_code == 200
    assert layer.status_code == 200
    assert layer.json()["feature_count"] == 10
    assert forbidden.status_code == 404


def test_layer_data_returns_geojson_on_demand_without_sse_payload(tmp_path, monkeypatch):
    user = make_user("layer-data-owner")
    map_request = MapRequest.objects.create(user=user, request_text="layer data")
    manager = seed_snapshot(tmp_path, map_request)
    monkeypatch.setattr(rest_api, "get_state_manager", lambda: manager)
    class Frame:
        def to_json(self):
            return json.dumps({"type": "FeatureCollection", "features": []})

    monkeypatch.setattr(rest_api, "read_dataset_features", lambda *_args: Frame())

    response = login_client(user).get(
        f"/mapping/api/map-requests/{map_request.id}/snapshots/1/layers/roads/data/"
    )

    assert response.status_code == 200
    assert response.json()["type"] == "FeatureCollection"
    assert response["Cache-Control"].startswith("private")


def test_layer_data_passes_source_scope_geometry_to_postgis_reader(tmp_path, monkeypatch):
    user = make_user("scoped-layer-data-owner")
    map_request = MapRequest.objects.create(user=user, request_text="scoped layer")
    manager = seed_snapshot(tmp_path, map_request)
    state = manager.load_state(f"web_session_{map_request.id}")
    state.layers[0].data_source_meta = {
        "dataset_id": "local-roads",
        "scope_geometry": {
            "type": "Polygon",
            "coordinates": [[[120, 30], [121, 30], [121, 31], [120, 31], [120, 30]]],
        },
    }
    assert manager.save_state(state)
    monkeypatch.setattr(rest_api, "get_state_manager", lambda: manager)
    calls = []

    class Frame:
        def to_json(self):
            return json.dumps({"type": "FeatureCollection", "features": []})

    def reader(dataset_id, bbox=None, limit=None, clip_geometry=None):
        calls.append((dataset_id, bbox, limit, clip_geometry))
        return Frame()

    monkeypatch.setattr(rest_api, "read_dataset_features", reader)

    response = login_client(user).get(
        f"/mapping/api/map-requests/{map_request.id}/snapshots/1/layers/roads/data/"
    )

    assert response.status_code == 200
    assert calls[0][3]["type"] == "Polygon"


def test_layer_data_reports_pending_until_processing_snapshot_is_ready():
    user = make_user("pending-layer-owner")
    map_request = MapRequest.objects.create(
        user=user,
        request_text="pending layer",
        status="processing",
    )

    response = login_client(user).get(
        f"/mapping/api/map-requests/{map_request.id}/snapshots/1/layers/roads/data/"
    )

    assert response.status_code == 202
    assert response.json()["status"] == "pending"


def test_mvt_tile_endpoint_returns_cached_pbf_and_enforces_snapshot_ownership(tmp_path, monkeypatch):
    owner = make_user("mvt-owner")
    other = make_user("mvt-other")
    map_request = MapRequest.objects.create(user=owner, request_text="mvt")
    manager = MapStateManager(str(Path(tmp_path) / "mvt.db"))
    state = MapState(
        config=MapConfig(map_id="mvt-map", title="MVT", extent=[-1, -1, 2, 2]),
        session_info=SessionInfo(session_id=f"web_session_{map_request.id}"),
        layers=[LayerConfig(
            layer_id="roads",
            name="Roads",
            geometry_type=GeometryType.LINE,
            data_source="remote-cache/roads.geojson",
            data_source_meta={"dataset_id": "remote-roads"},
            feature_count=30001,
            render_mode="mvt",
            data_hash="roads-v1",
        )],
    )
    assert manager.save_state(state)
    monkeypatch.setattr(rest_api, "get_state_manager", lambda: manager)
    monkeypatch.setattr(rest_api, "read_dataset_tile", lambda *_args: b"pbf")

    response = login_client(owner).get(
        f"/mapping/api/map-requests/{map_request.id}/snapshots/1/layers/roads/tiles/2/2/1.pbf"
    )
    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/vnd.mapbox-vector-tile")
    assert response["ETag"]
    assert response.content

    cached = login_client(owner).get(
        f"/mapping/api/map-requests/{map_request.id}/snapshots/1/layers/roads/tiles/2/2/1.pbf",
        HTTP_IF_NONE_MATCH=response["ETag"],
    )
    assert cached.status_code == 304

    assert login_client(other).get(
        f"/mapping/api/map-requests/{map_request.id}/snapshots/1/layers/roads/tiles/2/2/1.pbf"
    ).status_code == 404
    assert login_client(owner).get(
        f"/mapping/api/map-requests/{map_request.id}/snapshots/1/layers/roads/tiles/2/99/1.pbf"
    ).status_code == 400


def test_mvt_tile_endpoint_rejects_unregistered_file_fallback(tmp_path, monkeypatch):
    user = make_user("mvt-no-file-fallback-owner")
    map_request = MapRequest.objects.create(user=user, request_text="mvt no fallback")
    manager = MapStateManager(str(Path(tmp_path) / "mvt-no-fallback.db"))
    state = MapState(
        config=MapConfig(map_id="mvt-no-fallback", title="MVT", extent=[-1, -1, 2, 2]),
        session_info=SessionInfo(session_id=f"web_session_{map_request.id}"),
        layers=[LayerConfig(
            layer_id="roads",
            name="Roads",
            geometry_type=GeometryType.LINE,
            data_source=str(Path(tmp_path) / "roads.geojson"),
            feature_count=30001,
            render_mode="mvt",
        )],
    )
    assert manager.save_state(state)
    monkeypatch.setattr(rest_api, "get_state_manager", lambda: manager)

    response = login_client(user).get(
        f"/mapping/api/map-requests/{map_request.id}/snapshots/1/layers/roads/tiles/2/2/1.pbf"
    )

    assert response.status_code == 422
    assert response.json()["error_code"] == "dataset_not_registered"


def test_mvt_tile_endpoint_reports_pending_before_snapshot_is_saved():
    user = make_user("mvt-pending-owner")
    map_request = MapRequest.objects.create(
        user=user,
        request_text="mvt pending",
        status="processing",
    )

    response = login_client(user).get(
        f"/mapping/api/map-requests/{map_request.id}/snapshots/1/layers/roads/tiles/2/2/1.pbf"
    )

    assert response.status_code == 202
    assert response["Retry-After"] == "1"
    assert response.json()["retryable"] is True


def test_current_layer_data_route_resolves_latest_snapshot(tmp_path, monkeypatch):
    user = make_user("current-layer-owner")
    map_request = MapRequest.objects.create(user=user, request_text="current layer", status="completed")
    manager = seed_snapshot(tmp_path, map_request)
    monkeypatch.setattr(rest_api, "get_state_manager", lambda: manager)
    class Frame:
        def to_json(self):
            return json.dumps({"type": "FeatureCollection", "features": []})

    monkeypatch.setattr(rest_api, "read_dataset_features", lambda *_args: Frame())

    response = login_client(user).get(
        f"/mapping/api/map-requests/{map_request.id}/snapshots/current/layers/roads/data/"
    )

    assert response.status_code == 200
    assert response.json()["type"] == "FeatureCollection"


def test_request_detail_exposes_available_result_after_latest_run_failed(tmp_path, monkeypatch):
    from django.test import override_settings
    from PIL import Image

    user = make_user("failed-after-success-owner")
    map_request = MapRequest.objects.create(
        user=user,
        request_text="标注清华大学",
        status="failed",
        error_message="添加图层需要指定数据源",
    )
    completed_run = MapRun.objects.create(
        request=map_request,
        idempotency_key="successful-adjustment",
        status=MapRun.STATUS_COMPLETED,
        map_version=2,
    )
    failed_run = MapRun.objects.create(
        request=map_request,
        idempotency_key="failed-adjustment",
        status=MapRun.STATUS_FAILED,
        error_message="添加图层需要指定数据源",
    )
    GeneratedMap.objects.create(
        request=map_request,
        filename="v2_map.png",
        file_path="user_1/session_1/v2_map.png",
        file_size=100,
        version=2,
    )
    artifact_path = tmp_path / "user_1" / "session_1" / "v2_map.png"
    artifact_path.parent.mkdir(parents=True)
    Image.new("RGB", (2, 2), "white").save(artifact_path)

    with override_settings(GENERATED_MAPS_DIR=tmp_path):
        response = login_client(user).get(f"/mapping/api/map-requests/{map_request.id}/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "failed"
    assert payload["has_available_result"] is True
    assert payload["latest_map_version"] == 2
    assert payload["latest_successful_run"]["id"] == completed_run.id
    assert payload["latest_run"]["id"] == failed_run.id


def test_request_detail_exposes_clarification_without_marking_it_as_failure():
    user = make_user("clarification-owner")
    map_request = MapRequest.objects.create(
        user=user,
        request_text="帮我画个图",
        status="needs_clarification",
        result_message="请补充地图范围和图层类型。",
        clarification_data={
            "question": "你想绘制哪里的哪类地图？",
            "missing_fields": ["map_scope", "layer_type"],
            "suggestions": ["北京道路图"],
        },
    )

    response = login_client(user).get(f"/mapping/api/map-requests/{map_request.id}/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "needs_clarification"
    assert payload["error_message"] == ""
    assert payload["clarification"]["missing_fields"] == ["map_scope", "layer_type"]


def test_mvt_layer_accepts_only_viewport_limited_fallback(tmp_path, monkeypatch):
    user = make_user("mvt-fallback-owner")
    map_request = MapRequest.objects.create(user=user, request_text="mvt fallback")
    manager = seed_snapshot(tmp_path, map_request)
    state = manager.load_state(f"web_session_{map_request.id}")
    state.layers[0].render_mode = "mvt"
    manager.save_state(state)
    monkeypatch.setattr(rest_api, "get_state_manager", lambda: manager)

    without_bbox = login_client(user).get(
        f"/mapping/api/map-requests/{map_request.id}/snapshots/1/layers/roads/data/"
    )
    with_bbox = login_client(user).get(
        f"/mapping/api/map-requests/{map_request.id}/snapshots/1/layers/roads/data/?bbox=115,39,117,41"
    )

    assert without_bbox.status_code == 409
    assert with_bbox.status_code in {200, 422}


def test_artifact_collection_is_user_scoped_and_returns_file_metadata():
    owner = make_user("artifact-owner")
    other = make_user("artifact-other")
    map_request = MapRequest.objects.create(user=owner, request_text="artifact")
    GeneratedMap.objects.create(
        request=map_request,
        filename="beijing.png",
        file_path="user_1/session_1/beijing.png",
        file_size=128,
        version=2,
    )

    response = login_client(owner).get(
        f"/mapping/api/map-requests/{map_request.id}/artifacts/"
    )
    forbidden = login_client(other).get(
        f"/mapping/api/map-requests/{map_request.id}/artifacts/"
    )

    assert response.status_code == 200
    assert response.json()["items"][0]["filename"] == "beijing.png"
    assert response.json()["items"][0]["version"] == 2
    assert forbidden.status_code == 404


def test_artifact_collection_does_not_expose_unsafe_file_path():
    user = make_user("artifact-path-owner")
    map_request = MapRequest.objects.create(user=user, request_text="artifact")
    GeneratedMap.objects.create(
        request=map_request,
        filename="unsafe.png",
        file_path="../outside/unsafe.png",
    )

    response = login_client(user).get(
        f"/mapping/api/map-requests/{map_request.id}/artifacts/"
    )

    artifact = response.json()["items"][0]
    assert artifact["url"] is None
    assert artifact["file_exists"] is False

    empty = GeneratedMap.objects.create(
        request=map_request,
        filename="empty.png",
        file_path="",
    )
    empty_resource = rest_api._artifact_resource(empty)
    assert empty_resource["url"] is None
    assert empty_resource["file_exists"] is False


def test_message_collection_creates_user_message_and_lists_messages():
    user = make_user("message-owner")
    map_request = MapRequest.objects.create(user=user, request_text="message")
    client = login_client(user)

    created = client.post(
        f"/mapping/api/map-requests/{map_request.id}/messages/",
        data='{"content":"继续绘制道路"}',
        content_type="application/json",
    )
    listed = client.get(
        f"/mapping/api/map-requests/{map_request.id}/messages/"
    )

    assert created.status_code == 201
    assert created.json()["message_type"] == "user"
    assert ChatMessage.objects.filter(request=map_request, message_type="user").count() == 1
    assert listed.status_code == 200
    assert listed.json()["items"][0]["content"] == "继续绘制道路"


def test_message_collection_rejects_client_authored_assistant_message():
    user = make_user("message-role-owner")
    map_request = MapRequest.objects.create(user=user, request_text="message")

    response = login_client(user).post(
        f"/mapping/api/map-requests/{map_request.id}/messages/",
        data='{"content":"fake","message_type":"assistant"}',
        content_type="application/json",
    )

    assert response.status_code == 400
    assert not ChatMessage.objects.filter(request=map_request).exists()
