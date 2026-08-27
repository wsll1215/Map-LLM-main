"""Versioned REST resources for the map workbench."""

import json
import base64
import hashlib
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

from django.contrib.auth.decorators import login_required
from django.conf import settings
from django.db import IntegrityError, connection
from django.db.models import Q
from django.core.exceptions import ValidationError
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_http_methods

from gis_mapping_agent.state import get_state_manager
from gis_mapping_agent.utils.data_loader import DataLoader
from gis_mapping_agent.data_sources.metadata import source_metadata_from_path
from gis_mapping_agent.rendering.mvt import encode_tile, parse_tile_coordinates

from .models import ChatMessage, Dataset, DatasetFeature, MapRequest, MapRun, ProcessLog
from .task_dispatch import dispatch_map_request
from .trace import repair_legacy_trace_events, trace_event_to_dict


@lru_cache(maxsize=8)
def _load_projected_mvt_data(data_source, data_hash):
    """Cache immutable tile input after one disk read and reprojection."""
    data = DataLoader().load_shapefile(data_source)
    if data is None:
        raise FileNotFoundError(f"图层数据读取失败: {data_source}")
    return data.to_crs("EPSG:3857")


def _json_body(request):
    try:
        value = json.loads(request.body or "{}")
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _request_resource(request, map_request):
    detail_url = reverse("mapping:map-request-detail", args=[map_request.id])
    latest_run = map_request.runs.order_by("-created_at", "-id").first()
    latest_successful_run = (
        map_request.runs
        .filter(status=MapRun.STATUS_COMPLETED)
        .order_by("-created_at", "-id")
        .first()
    )
    latest_available_run = (
        map_request.runs
        .filter(status__in=[MapRun.STATUS_COMPLETED, MapRun.STATUS_PARTIAL])
        .order_by("-created_at", "-id")
        .first()
    )
    latest_artifact = map_request.generated_maps.order_by("-version", "-created_at", "-id").first()
    return {
        "id": map_request.id,
        "title": map_request.title,
        "request_text": map_request.request_text,
        "status": map_request.status,
        "result_message": map_request.result_message,
        "error_message": map_request.error_message,
        "clarification": map_request.clarification_data or None,
        "latest_run": _run_resource(latest_run) if latest_run else None,
        "latest_successful_run": _run_resource(latest_successful_run) if latest_successful_run else None,
        "latest_available_run": _run_resource(latest_available_run) if latest_available_run else None,
        "completion_report": map_request.completion_report or {},
        "has_available_result": latest_artifact is not None,
        "latest_map_version": latest_artifact.version if latest_artifact else None,
        "created_at": map_request.created_at.isoformat(),
        "updated_at": map_request.updated_at.isoformat(),
        "urls": {
            "self": detail_url,
            "messages": f"{detail_url}messages/",
            "runs": f"{detail_url}runs/",
            "snapshots": f"{detail_url}snapshots/",
            "artifacts": f"{detail_url}artifacts/",
        },
    }


def _run_resource(run):
    return {
        "id": run.id,
        "request_id": run.request_id,
        "status": run.status,
        "idempotency_key": run.idempotency_key,
        "trace_id": run.trace_id,
        "map_version": run.map_version,
        "attempt": run.attempt,
        "heartbeat_at": run.heartbeat_at.isoformat() if run.heartbeat_at else None,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "error_code": run.error_code,
        "error_message": run.error_message,
        "completion_report": run.completion_report or {},
        "created_at": run.created_at.isoformat(),
        "updated_at": run.updated_at.isoformat(),
    }


def _trace_event_resource(event, *, include_payload=False):
    """Expose one ProcessLog as the stable TraceEvent wire shape."""
    return trace_event_to_dict(event, include_payload=include_payload)


def _trace_cursor(value):
    if value in (None, ""):
        return 0
    try:
        cursor = int(value)
    except (TypeError, ValueError):
        return None
    return cursor if cursor >= 0 else None


@login_required
@require_http_methods(["GET"])
def map_trace_event_collection(request, request_id, run_id):
    """List trace summaries; full payloads are available from the detail resource."""
    map_request = get_object_or_404(MapRequest, id=request_id, user=request.user)
    run = get_object_or_404(MapRun, id=run_id, request=map_request)
    repair_legacy_trace_events(run)
    try:
        limit = min(max(int(request.GET.get("limit", 50)), 1), 100)
    except (TypeError, ValueError):
        return _bad_request("limit 必须是 1 到 100 之间的整数")
    cursor = _trace_cursor(request.GET.get("cursor"))
    if cursor is None:
        return _bad_request("cursor 必须是非负整数")

    events = ProcessLog.objects.filter(run=run)
    event_type = request.GET.get("event_type", "").strip()
    status = request.GET.get("status", "").strip()
    phase = request.GET.get("phase", "").strip()
    query = request.GET.get("q", "").strip()
    errors_only = request.GET.get("errors_only", "").lower() in {"1", "true", "yes"}
    if cursor:
        events = events.filter(event_seq__gt=cursor)
    if event_type:
        events = events.filter(event_type=event_type)
    if status:
        events = events.filter(status=status)
    if phase:
        events = events.filter(phase=phase)
    if query:
        events = events.filter(Q(message__icontains=query) | Q(step__icontains=query))
    if errors_only:
        events = events.filter(Q(status="error") | Q(level="error") | Q(error__isnull=False))

    total_count = events.count()
    rows = list(events.select_related("run").order_by("event_seq", "id")[: limit + 1])
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = rows[-1].event_seq if has_more else None
    return JsonResponse(
        {
            "items": [_trace_event_resource(event) for event in rows],
            "limit": limit,
            "next_cursor": next_cursor,
            "total_count": total_count,
            "trace_id": run.trace_id or None,
            "run_id": run.id,
        }
    )


@login_required
@require_http_methods(["GET"])
def map_trace_event_detail(request, request_id, run_id, event_id):
    map_request = get_object_or_404(MapRequest, id=request_id, user=request.user)
    run = get_object_or_404(MapRun, id=run_id, request=map_request)
    repair_legacy_trace_events(run)
    event = get_object_or_404(ProcessLog.objects.select_related("run"), run=run, event_id=event_id)
    return JsonResponse(_trace_event_resource(event, include_payload=True))


def _dataset_resource(dataset):
    detail_url = reverse("mapping:dataset-detail", args=[dataset.dataset_id])
    return {
        "id": dataset.dataset_id,
        "name": dataset.name,
        "aliases": dataset.aliases or [],
        "source_type": dataset.source_type,
        "source_url": dataset.source_url or None,
        "local_path": dataset.local_path or None,
        "geometry_type": dataset.geometry_type,
        "crs": dataset.crs,
        "bbox": dataset.bbox,
        "feature_count": dataset.feature_count,
        "license": dataset.license,
        "version": dataset.version,
        "status": dataset.status,
        "metadata": dataset.metadata or {},
        "urls": {
            "self": detail_url,
            "features": f"{detail_url}features/",
        },
    }


def _normalize_dataset_query(value):
    import re

    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", str(value or "").lower())


def _dataset_match_score(dataset, query):
    if not query:
        return 0
    values = [dataset.name, dataset.local_path, *(dataset.aliases or [])]
    normalized = [_normalize_dataset_query(value) for value in values]
    if query in normalized:
        return 100
    if any(query in value for value in normalized):
        return 70
    if any(value and value in query for value in normalized):
        return 50
    return 0


@login_required
@require_http_methods(["GET"])
def dataset_collection(request):
    """Search the catalog without exposing arbitrary filesystem paths."""
    try:
        limit = min(max(int(request.GET.get("limit", 20)), 1), 100)
    except (TypeError, ValueError):
        return _bad_request("limit 必须是 1 到 100 之间的整数")

    query = _normalize_dataset_query(request.GET.get("query", ""))
    source_type = request.GET.get("source_type", "").strip()
    geometry_type = request.GET.get("geometry_type", "").strip().lower()
    datasets = Dataset.objects.filter(status=Dataset.STATUS_AVAILABLE)
    if source_type:
        datasets = datasets.filter(source_type=source_type)
    if geometry_type:
        datasets = datasets.filter(geometry_type__iexact=geometry_type)

    ranked = []
    for dataset in datasets:
        score = _dataset_match_score(dataset, query) if query else 1
        if score:
            ranked.append((score, dataset.name.lower(), dataset.dataset_id, dataset))
    ranked.sort(key=lambda item: (-item[0], item[1], item[2]))
    items = [_dataset_resource(item[3]) for item in ranked[:limit]]
    return JsonResponse(
        {
            "items": items,
            "query": request.GET.get("query", ""),
            "limit": limit,
            "count": len(items),
        }
    )


@login_required
@require_http_methods(["GET"])
def dataset_detail(request, dataset_id):
    dataset = get_object_or_404(
        Dataset,
        dataset_id=dataset_id,
        status=Dataset.STATUS_AVAILABLE,
    )
    return JsonResponse(_dataset_resource(dataset))


@login_required
@require_http_methods(["GET"])
def dataset_feature_collection(request, dataset_id):
    """Return a bounded GeoJSON subset selected by a PostGIS bbox query."""
    if connection.vendor != "postgresql":
        return JsonResponse({"error": "空间要素查询需要 PostgreSQL/PostGIS"}, status=503)
    dataset = get_object_or_404(
        Dataset,
        dataset_id=dataset_id,
        status=Dataset.STATUS_AVAILABLE,
    )
    try:
        limit = min(max(int(request.GET.get("limit", 2000)), 1), 10000)
    except (TypeError, ValueError):
        return _bad_request("limit 必须是 1 到 10000 之间的整数")
    bbox_text = request.GET.get("bbox", "").strip()
    if not bbox_text:
        return _bad_request("bbox 必须是 minx,miny,maxx,maxy")
    try:
        bbox = [float(value) for value in bbox_text.split(",")]
        if len(bbox) != 4 or bbox[0] >= bbox[2] or bbox[1] >= bbox[3]:
            raise ValueError
    except ValueError:
        return _bad_request("bbox 必须是 minx,miny,maxx,maxy")

    from django.contrib.gis.geos import Polygon

    query = DatasetFeature.objects.filter(
        dataset=dataset,
        geom__intersects=Polygon.from_bbox(bbox),
    ).only("id", "source_fid", "geom", "properties")[:limit]
    features = []
    for item in query:
        features.append(
            {
                "type": "Feature",
                "id": item.source_fid,
                "geometry": json.loads(item.geom.geojson),
                "properties": item.properties or {},
            }
        )
    return _cached_json(
        request,
        {"type": "FeatureCollection", "features": features, "limit": limit},
        dataset.dataset_id,
        bbox_text,
        len(features),
    )


def _message_resource(message):
    return {
        "id": message.id,
        "request_id": message.request_id,
        "message_type": message.message_type,
        "type": message.message_type,
        "content": message.content,
        "extra_data": message.extra_data,
        "created_at": message.created_at.isoformat(),
    }


def _state_session_id(request_id):
    return f"web_session_{request_id}"


def _layer_manifest(layer, version):
    return {
        "id": layer.layer_id,
        "version": version,
        "name": layer.name,
        "geometry_type": layer.geometry_type.value
        if hasattr(layer.geometry_type, "value")
        else str(layer.geometry_type),
        "feature_count": layer.feature_count,
        "extent": layer.extent,
        "data_hash": layer.data_hash,
        "render_mode": _effective_render_mode(layer),
        "data_url": layer.data_url,
        "data_source_meta": source_metadata_from_path(
            layer.data_source, layer.data_source_meta
        ),
        "render_spec": layer.render_spec,
        "visible": layer.visible,
        "z_order": layer.z_order,
    }


def _snapshot_resource(state):
    version = state.get_current_version()
    spec = dict(state.spec_json or {})
    spec.update(
        {
            "schema_version": state.schema_version,
            "map_id": state.config.map_id,
            "version": version,
            "title": state.config.title,
            "crs": state.config.crs.value
            if hasattr(state.config.crs, "value")
            else str(state.config.crs),
            "extent": state.config.extent,
        }
    )
    return {
        "version": version,
        "schema_version": state.schema_version,
        "spec": spec,
        "spec_hash": state.spec_hash,
        "source_fingerprints": state.source_fingerprints,
        "latest_event_seq": state.latest_event_seq,
        "layers": [_layer_manifest(layer, version) for layer in state.layers],
    }


def _bad_request(message):
    return JsonResponse({"error": message}, status=400)


def _cached_json(request, payload, *cache_parts):
    digest_input = "|".join(str(part or "") for part in cache_parts).encode("utf-8")
    etag = '"' + hashlib.sha256(digest_input).hexdigest() + '"'
    if request.headers.get("If-None-Match") == etag:
        response = HttpResponse(status=304)
    else:
        response = JsonResponse(payload)
    response["ETag"] = etag
    response["Cache-Control"] = "private, max-age=0, must-revalidate"
    return response


def _encode_cursor(map_request):
    value = json.dumps(
        {"created_at": map_request.created_at.isoformat(), "id": map_request.id},
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode_cursor(value):
    try:
        padding = "=" * (-len(value) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(value + padding).decode("utf-8"))
        created_at = parse_datetime(decoded["created_at"])
        request_id = int(decoded["id"])
    except (KeyError, TypeError, ValueError, UnicodeError):
        return None
    if created_at is None or request_id < 1:
        return None
    return created_at, request_id


@login_required
@require_http_methods(["GET", "POST"])
def map_request_collection(request):
    if request.method == "GET":
        try:
            limit = min(max(int(request.GET.get("limit", 20)), 1), 100)
        except (TypeError, ValueError):
            return _bad_request("limit 必须是 1 到 100 之间的整数")

        query = MapRequest.objects.filter(user=request.user)
        cursor = request.GET.get("cursor")
        if cursor:
            decoded_cursor = _decode_cursor(cursor)
            if decoded_cursor is None:
                return _bad_request("cursor 无效")
            created_at, request_id = decoded_cursor
            query = query.filter(
                Q(created_at__lt=created_at)
                | Q(created_at=created_at, id__lt=request_id)
            )
        rows = list(query.order_by("-created_at", "-id")[: limit + 1])
        has_more = len(rows) > limit
        rows = rows[:limit]
        items = [_request_resource(request, item) for item in rows]
        next_cursor = _encode_cursor(rows[-1]) if has_more else None
        return JsonResponse({"items": items, "limit": limit, "next_cursor": next_cursor})

    data = _json_body(request)
    if data is None:
        return _bad_request("请求体必须是 JSON 对象")
    request_text = data.get("request_text")
    if not isinstance(request_text, str) or not request_text.strip():
        return _bad_request("request_text 不能为空")
    title = data.get("title", "")
    if not isinstance(title, str):
        return _bad_request("title 必须是字符串")

    map_request = MapRequest.objects.create(
        user=request.user,
        title=title.strip(),
        request_text=request_text.strip(),
        completion_report={},
    )
    return JsonResponse(_request_resource(request, map_request), status=201)


@login_required
@require_http_methods(["GET", "PATCH", "DELETE"])
def map_request_detail(request, request_id):
    map_request = get_object_or_404(MapRequest, id=request_id, user=request.user)

    if request.method == "GET":
        return JsonResponse(_request_resource(request, map_request))

    if request.method == "DELETE":
        map_request.delete()
        return HttpResponse(status=204)

    data = _json_body(request)
    if data is None:
        return _bad_request("请求体必须是 JSON 对象")
    unsupported = set(data) - {"title", "request_text"}
    if unsupported:
        return _bad_request("不允许修改字段: " + ", ".join(sorted(unsupported)))

    update_fields = []
    if "title" in data:
        if not isinstance(data["title"], str):
            return _bad_request("title 必须是字符串")
        map_request.title = data["title"].strip()
        update_fields.append("title")
    if "request_text" in data:
        if not isinstance(data["request_text"], str) or not data["request_text"].strip():
            return _bad_request("request_text 不能为空")
        map_request.request_text = data["request_text"].strip()
        update_fields.append("request_text")
    if not update_fields:
        return _bad_request("至少提供一个可修改字段")

    update_fields.append("updated_at")
    map_request.save(update_fields=update_fields)
    return JsonResponse(_request_resource(request, map_request))


@login_required
@require_http_methods(["GET", "POST"])
def map_message_collection(request, request_id):
    map_request = get_object_or_404(MapRequest, id=request_id, user=request.user)
    if request.method == "GET":
        try:
            limit = min(max(int(request.GET.get("limit", 100)), 1), 100)
        except (TypeError, ValueError):
            return _bad_request("limit 必须是 1 到 100 之间的整数")
        query = map_request.chat_messages.all()
        cursor = request.GET.get("cursor")
        if cursor:
            decoded_cursor = _decode_cursor(cursor)
            if decoded_cursor is None:
                return _bad_request("cursor 无效")
            created_at, message_id = decoded_cursor
            query = query.filter(
                Q(created_at__gt=created_at)
                | Q(created_at=created_at, id__gt=message_id)
            )
        rows = list(query.order_by("created_at", "id")[: limit + 1])
        has_more = len(rows) > limit
        rows = rows[:limit]
        return JsonResponse(
            {
                "items": [_message_resource(item) for item in rows],
                "limit": limit,
                "next_cursor": _encode_cursor(rows[-1]) if has_more else None,
            }
        )

    data = _json_body(request)
    if data is None or set(data) - {"content", "message_type"}:
        return _bad_request("只允许提交 content 和 message_type 字段")
    content = data.get("content")
    if not isinstance(content, str) or not content.strip():
        return _bad_request("content 不能为空")
    if data.get("message_type", "user") != "user":
        return _bad_request("客户端只能创建 user 消息")
    message = ChatMessage.objects.create(
        request=map_request,
        message_type="user",
        content=content.strip(),
    )
    return JsonResponse(_message_resource(message), status=201)


@login_required
@require_http_methods(["POST"])
def map_run_collection(request, request_id):
    map_request = get_object_or_404(MapRequest, id=request_id, user=request.user)
    idempotency_key = request.headers.get("Idempotency-Key", "").strip()
    if not idempotency_key:
        return _bad_request("必须提供 Idempotency-Key 请求头")
    if len(idempotency_key) > 255:
        return _bad_request("Idempotency-Key 不能超过 255 个字符")

    try:
        run, created = MapRun.objects.get_or_create(
            request=map_request,
            idempotency_key=idempotency_key,
        )
    except IntegrityError:
        run = MapRun.objects.get(
            request=map_request,
            idempotency_key=idempotency_key,
        )
        created = False
    if created:
        try:
            dispatch_map_request(map_request.id, run.id)
        except Exception:
            run.transition_to(
                MapRun.STATUS_FAILED,
                error_code="WORKER_UNAVAILABLE",
                error_message="任务提交失败，请稍后重试",
            )
            return JsonResponse({"error": "任务提交失败，请稍后重试"}, status=503)
    return JsonResponse(_run_resource(run), status=201 if created else 200)


@login_required
@require_http_methods(["GET", "PATCH"])
def map_run_detail(request, request_id, run_id):
    map_request = get_object_or_404(MapRequest, id=request_id, user=request.user)
    run = get_object_or_404(MapRun, id=run_id, request=map_request)

    if request.method == "GET":
        return JsonResponse(_run_resource(run))

    data = _json_body(request)
    if data is None or set(data) != {"status"}:
        return _bad_request("PATCH 只允许提交 status 字段")
    if data["status"] != MapRun.STATUS_CANCEL_REQUESTED:
        return _bad_request("客户端只能请求取消运行")
    try:
        run.transition_to(MapRun.STATUS_CANCEL_REQUESTED)
    except ValidationError as exc:
        return _bad_request(str(exc.message_dict.get("status", [str(exc)])))
    return JsonResponse(_run_resource(run))


def _snapshot_for_request(map_request, version=None):
    return get_state_manager().load_state(_state_session_id(map_request.id), version)


def _effective_render_mode(layer):
    if layer.render_mode in {"mvt", "pmtiles"}:
        return layer.render_mode
    if layer.feature_count > getattr(settings, "MAP_WORKER_LIMIT", 30000):
        return "mvt" if getattr(settings, "MAP_MVT_ENABLED", True) else "geojson-worker"
    if layer.feature_count > getattr(settings, "MAP_GEOJSON_LIMIT", 5000):
        return "geojson-worker"
    return "geojson"


def _artifact_resource(artifact):
    root = Path(settings.GENERATED_MAPS_DIR).resolve()
    relative_path = Path(artifact.file_path or "")
    valid_path = bool(artifact.file_path) and not relative_path.is_absolute() and ".." not in relative_path.parts
    full_path = (root / relative_path).resolve() if valid_path else root
    valid_path = valid_path and (full_path == root or root in full_path.parents)
    return {
        "id": artifact.id,
        "request_id": artifact.request_id,
        "filename": artifact.filename,
        "version": artifact.version,
        "file_size": artifact.file_size,
        "file_exists": valid_path and full_path.is_file(),
        "url": (
            f"/generated_maps/{quote(relative_path.as_posix(), safe='/')}"
            if valid_path
            else None
        ),
        "created_at": artifact.created_at.isoformat(),
    }


@login_required
@require_http_methods(["GET"])
def map_artifact_collection(request, request_id):
    map_request = get_object_or_404(MapRequest, id=request_id, user=request.user)
    items = [
        _artifact_resource(artifact)
        for artifact in map_request.generated_maps.order_by("-created_at")
    ]
    return JsonResponse({"items": items, "next_cursor": None})


@login_required
@require_http_methods(["GET"])
def map_snapshot_current(request, request_id):
    map_request = get_object_or_404(MapRequest, id=request_id, user=request.user)
    state = _snapshot_for_request(map_request)
    if state is None:
        return JsonResponse({"error": "快照不存在"}, status=404)
    return _cached_json(
        request,
        _snapshot_resource(state),
        map_request.id,
        state.get_current_version(),
        state.spec_hash,
        state.latest_event_seq,
    )


@login_required
@require_http_methods(["GET"])
def map_snapshot_detail(request, request_id, version):
    map_request = get_object_or_404(MapRequest, id=request_id, user=request.user)
    state = _snapshot_for_request(map_request, version)
    if state is None:
        return JsonResponse({"error": "快照不存在"}, status=404)
    return _cached_json(
        request,
        _snapshot_resource(state),
        map_request.id,
        state.get_current_version(),
        state.spec_hash,
        state.latest_event_seq,
    )


@login_required
@require_http_methods(["GET"])
def map_layer_manifest(request, request_id, version, layer_id):
    map_request = get_object_or_404(MapRequest, id=request_id, user=request.user)
    state = _snapshot_for_request(map_request, version)
    if state is None:
        return JsonResponse({"error": "快照不存在"}, status=404)
    layer = next((item for item in state.layers if item.layer_id == layer_id), None)
    if layer is None:
        return JsonResponse({"error": "图层不存在"}, status=404)
    return _cached_json(
        request,
        _layer_manifest(layer, state.get_current_version()),
        map_request.id,
        state.get_current_version(),
        layer.layer_id,
        layer.data_hash,
    )


@login_required
@require_http_methods(["GET"])
def map_layer_data(request, request_id, version, layer_id):
    map_request = get_object_or_404(MapRequest, id=request_id, user=request.user)
    state = _snapshot_for_request(map_request, version)
    if state is None:
        if map_request.status in {"pending", "processing"}:
            return JsonResponse(
                {"status": "pending", "message": "图层快照正在生成"},
                status=202,
                headers={"Retry-After": "1"},
            )
        return JsonResponse({"error": "快照不存在"}, status=404)
    layer = next((item for item in state.layers if item.layer_id == layer_id), None)
    if layer is None:
        if map_request.status in {"pending", "processing"}:
            return JsonResponse(
                {"status": "pending", "message": "图层快照正在生成"},
                status=202,
                headers={"Retry-After": "1"},
            )
        return JsonResponse({"error": "图层不存在"}, status=404)
    render_mode = _effective_render_mode(layer)
    bbox_text = request.GET.get("bbox", "").strip()
    bbox = None
    if bbox_text:
        try:
            bbox = [float(value) for value in bbox_text.split(",")]
            if len(bbox) != 4 or bbox[0] >= bbox[2] or bbox[1] >= bbox[3]:
                raise ValueError
        except ValueError:
            return JsonResponse({"error": "bbox 必须是 minx,miny,maxx,maxy"}, status=400)
    if render_mode in {"mvt", "pmtiles"} and bbox is None:
        return JsonResponse(
            {"error": "该图层必须通过瓦片接口加载", "render_mode": render_mode},
            status=409,
        )
    limit = getattr(settings, "MAP_GEOJSON_LIMIT", 5000)
    if layer.feature_count > limit and bbox is None:
        return JsonResponse(
            {
                "error": "图层要素数量超过 GeoJSON 上限",
                "feature_count": layer.feature_count,
                "limit": limit,
                "render_mode": render_mode,
            },
            status=413,
        )
    if not layer.data_source:
        return JsonResponse({"error": "图层没有可读取的数据源"}, status=404)

    loader = DataLoader()
    data = loader.load_shapefile(layer.data_source)
    if data is None:
        return JsonResponse({"error": "图层数据读取失败"}, status=422)
    if bbox is not None:
        data = loader.filter_data(data, spatial_filter=tuple(bbox))
        worker_limit = getattr(settings, "MAP_WORKER_LIMIT", 30000)
        if len(data) > worker_limit:
            return JsonResponse(
                {
                    "error_code": "data_too_large",
                    "error": "当前视口内要素仍超过 Worker 上限，请使用 MVT 瓦片",
                    "feature_count": len(data),
                    "limit": worker_limit,
                    "render_mode": "mvt",
                    "retryable": False,
                    "next_action": "use_mvt",
                },
                status=413,
            )
        if hasattr(data, "geometry"):
            data = data.copy()
            data["geometry"] = data.geometry.simplify(0.0001, preserve_topology=True)
    geojson = loader.create_geojson_from_gdf(data)
    if isinstance(geojson, dict):
        returned_count = len(geojson.get("features") or [])
        geojson["truncated"] = False
        geojson["feature_count"] = layer.feature_count
        geojson["returned_count"] = returned_count
    return _cached_json(
        request,
        geojson,
        map_request.id,
        state.get_current_version(),
        layer.layer_id,
        layer.data_hash,
    )


@login_required
@require_http_methods(["GET"])
def map_layer_data_current(request, request_id, layer_id):
    """Resolve the current snapshot before serving the layer payload."""
    map_request = get_object_or_404(MapRequest, id=request_id, user=request.user)
    state = _snapshot_for_request(map_request)
    if state is None:
        if map_request.status in {"pending", "processing"}:
            return JsonResponse(
                {"status": "pending", "message": "图层快照正在生成"},
                status=202,
                headers={"Retry-After": "1"},
            )
        return JsonResponse({"error": "快照不存在"}, status=404)
    return map_layer_data(request, request_id, state.get_current_version(), layer_id)


@login_required
@require_http_methods(["GET"])
def map_layer_tile(request, request_id, version, layer_id, z, x, y):
    """Return one versioned MVT tile for a user's snapshot layer."""
    map_request = get_object_or_404(MapRequest, id=request_id, user=request.user)
    try:
        zoom, tile_x, tile_y = parse_tile_coordinates(z, x, y)
    except ValueError as exc:
        return JsonResponse({"error_code": "validation_error", "error": str(exc)}, status=400)

    state = _snapshot_for_request(map_request, version)
    if state is None:
        if map_request.status in {"pending", "processing"}:
            return JsonResponse(
                {
                    "status": "pending",
                    "message": "图层快照正在生成",
                    "retryable": True,
                    "next_action": "retry",
                },
                status=202,
                headers={"Retry-After": "1"},
            )
        return JsonResponse({"error_code": "resource_not_found", "error": "快照不存在"}, status=404)
    layer = next((item for item in state.layers if item.layer_id == layer_id), None)
    if layer is None:
        if map_request.status in {"pending", "processing"}:
            return JsonResponse(
                {
                    "status": "pending",
                    "message": "图层快照正在生成",
                    "retryable": True,
                    "next_action": "retry",
                },
                status=202,
                headers={"Retry-After": "1"},
            )
        return JsonResponse({"error_code": "resource_not_found", "error": "图层不存在"}, status=404)
    if not layer.data_source:
        return JsonResponse({"error_code": "resource_not_found", "error": "图层没有可读取的数据源"}, status=404)

    try:
        data = _load_projected_mvt_data(layer.data_source, layer.data_hash)
    except FileNotFoundError:
        return JsonResponse(
            {"error_code": "resource_not_found", "error": "图层数据读取失败", "retryable": False},
            status=422,
        )
    try:
        payload = encode_tile(
            data,
            layer.name or layer.layer_id,
            zoom,
            tile_x,
            tile_y,
            projected=True,
        )
    except ImportError as exc:
        return JsonResponse(
            {
                "error_code": "render_error",
                "error": f"MVT 渲染依赖不可用: {exc}",
                "retryable": False,
                "next_action": "use_png_fallback",
            },
            status=503,
        )
    except (RuntimeError, TypeError, ValueError) as exc:
        return JsonResponse(
            {"error_code": "render_error", "error": str(exc), "retryable": False},
            status=422,
        )

    etag = '"' + hashlib.sha256(
        f"{map_request.id}:{version}:{layer.layer_id}:{layer.data_hash}:{zoom}:{tile_x}:{tile_y}".encode()
    ).hexdigest() + '"'
    if request.headers.get("If-None-Match") == etag:
        response = HttpResponse(status=304)
    else:
        response = HttpResponse(payload, content_type="application/vnd.mapbox-vector-tile")
    response["ETag"] = etag
    response["Cache-Control"] = "private, max-age=3600, must-revalidate"
    return response
