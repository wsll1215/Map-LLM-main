import os
import json

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "xy_neo4j.settings")

import django
import pytest
from django.contrib.auth import get_user_model
from django.test import Client

django.setup()

from gis_mapping_agent.models.schemas import GeometryType, LayerConfig, MapConfig, MapState, SessionInfo
from gis_mapping_agent.state import MapStateManager
from mapping.models import ChatMessage, GeneratedMap, MapRequest, MapRun
from mapping import rest_api
from mapping.views import _build_clarification_context

pytestmark = pytest.mark.usefixtures("django_test_database")


def make_user(username):
    return get_user_model().objects.create_user(username=username, password="secret")


def login_client(user):
    client = Client()
    client.force_login(user)
    return client


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
    monkeypatch.setattr(
        rest_api,
        "DataLoader",
        lambda: type(
            "Loader",
            (),
            {
                "load_shapefile": lambda self, source: object(),
                "create_geojson_from_gdf": lambda self, data: {
                    "type": "FeatureCollection",
                    "features": [],
                },
            },
        )(),
    )

    response = login_client(user).get(
        f"/mapping/api/map-requests/{map_request.id}/snapshots/1/layers/roads/data/"
    )

    assert response.status_code == 200
    assert response.json()["type"] == "FeatureCollection"
    assert response["Cache-Control"].startswith("private")


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


def test_current_layer_data_route_resolves_latest_snapshot(tmp_path, monkeypatch):
    user = make_user("current-layer-owner")
    map_request = MapRequest.objects.create(user=user, request_text="current layer", status="completed")
    manager = seed_snapshot(tmp_path, map_request)
    monkeypatch.setattr(rest_api, "get_state_manager", lambda: manager)
    monkeypatch.setattr(
        rest_api,
        "DataLoader",
        lambda: type(
            "Loader",
            (),
            {
                "load_shapefile": lambda self, source: object(),
                "create_geojson_from_gdf": lambda self, data: {
                    "type": "FeatureCollection",
                    "features": [],
                },
            },
        )(),
    )

    response = login_client(user).get(
        f"/mapping/api/map-requests/{map_request.id}/snapshots/current/layers/roads/data/"
    )

    assert response.status_code == 200
    assert response.json()["type"] == "FeatureCollection"


def test_request_detail_exposes_available_result_after_latest_run_failed(tmp_path, monkeypatch):
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
