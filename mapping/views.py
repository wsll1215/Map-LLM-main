import json
import os
import sys
import logging
import locale
import threading
import shutil
from pathlib import Path
from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.middleware.csrf import get_token
from django.views.decorators.http import require_http_methods
from django.conf import settings
from django.utils import timezone
from django.db import close_old_connections

from .models import Dataset, MapRequest, MapRun, GeneratedMap, ChatMessage, ProcessLog
from .realtime import publish_map_build_event
from .task_dispatch import dispatch_conversation, dispatch_map_request
from .finalization import LayerValidation, finalize_execution
from .trace import record_trace_event, trace_event_to_dict
from .run_limits import active_run_admission, active_run_capacity_error

MAP_LLM_DIR = settings.BASE_DIR
if str(MAP_LLM_DIR) not in sys.path:
    sys.path.insert(0, str(MAP_LLM_DIR))

MAP_LLM_EXECUTION_LOCK = threading.RLock()
_PREVIEW_CLEANUP_TIMERS = {}
_PREVIEW_CLEANUP_LOCK = threading.RLock()


def _publish_lifecycle_event(map_request, event_type, **extra):
    """Publish request lifecycle state without coupling generation to SSE."""
    payload = {
        "type": event_type,
        "request_id": map_request.id,
        "status": map_request.status,
        "created_at_ms": int(timezone.now().timestamp() * 1000),
    }
    payload.update(extra)
    run = (
        MapRun.objects.filter(request=map_request)
        .order_by('-created_at', '-id')
        .first()
    )
    if run:
        is_terminal_event = event_type in {
            'request_completed', 'request_partial', 'request_failed',
            'request_needs_clarification', 'done',
        }
        if event_type == 'done' and run.process_logs.filter(event_type='run_finished').exists():
            return publish_map_build_event(map_request.id, payload)
        trace_type = 'run_finished' if event_type in {
            'request_completed', 'request_partial', 'request_failed',
            'request_needs_clarification', 'done',
        } else 'run'
        terminal_status = extra.get('status') or map_request.status
        trace_status = (
            'success' if terminal_status == 'completed'
            else 'error' if terminal_status == 'failed'
            else 'warning' if terminal_status in {'partial', 'needs_clarification'}
            else 'running'
        )
        event = record_trace_event(
            run=run,
            event_type=trace_type,
            phase='lifecycle',
            status=trace_status,
            summary=str(extra.get('message') or event_type),
            output_data={'request_status': terminal_status if is_terminal_event else map_request.status},
            error=extra.get('error') if isinstance(extra.get('error'), dict) else None,
        )
        payload['trace_event'] = trace_event_to_dict(event, include_payload=False)
        stream_id = publish_map_build_event(map_request.id, payload)
        publish_map_build_event(map_request.id, {
            'type': 'trace_event',
            'request_id': map_request.id,
            'trace_event': payload['trace_event'],
        })
        return stream_id
    return publish_map_build_event(map_request.id, payload)


def _current_run_context(map_request, run=None):
    if run is not None:
        return {'run_id': run.id, 'trace_id': run.trace_id or None}
    run = (
        MapRun.objects.filter(request=map_request)
        .only('id', 'trace_id')
        .order_by('-created_at', '-id')
        .first()
    )
    if not run:
        return {'run_id': None, 'trace_id': None}
    return {'run_id': run.id, 'trace_id': run.trace_id or None}


def _publish_process_log_event(map_request, message, *, level='info', step=None, progress=None, run=None):
    payload = {
        'type': 'process_log',
        'request_id': map_request.id,
        'level': level,
        'message': str(message),
        'step': step,
        'progress': progress,
        'created_at_ms': int(timezone.now().timestamp() * 1000),
    }
    payload.update(_current_run_context(map_request, run))
    current_run = run or MapRun.objects.filter(request=map_request).order_by('-created_at', '-id').first()
    if current_run:
        event_type = 'tool_call' if '工具' in str(step or '') else 'process_log'
        event = record_trace_event(
            run=current_run,
            event_type=event_type,
            phase=str(step or 'execution'),
            status='error' if level == 'error' else 'warning' if level == 'warning' else 'success',
            summary=str(message),
            output_data={'progress': progress} if progress is not None else {},
            error={'error_code': 'process_error', 'retryable': False, 'next_action': 'inspect_trace'}
            if level == 'error' else None,
            progress=progress,
        )
        payload['trace_event'] = trace_event_to_dict(event, include_payload=False)
        publish_map_build_event(map_request.id, payload)
        publish_map_build_event(map_request.id, {
            'type': 'trace_event',
            'request_id': map_request.id,
            'trace_event': payload['trace_event'],
        })
        return
    publish_map_build_event(map_request.id, payload)


def _record_error_event(map_request, run, message, step):
    if not run:
        return
    event = record_trace_event(
        run=run,
        event_type='error',
        phase=step or 'error',
        status='error',
        summary=str(message),
        error={
            'error_code': 'internal_error',
            'retryable': False,
            'next_action': 'inspect_trace',
        },
    )
    publish_map_build_event(map_request.id, {
        'type': 'trace_event',
        'request_id': map_request.id,
        'trace_event': trace_event_to_dict(event),
    })


def _map_layer_role(name):
    text = str(name or '').lower()
    if '小学' in text:
        return 'primary_school'
    if '高校' in text or '大学' in text:
        return 'university'
    if '医院' in text:
        return 'hospital'
    if '公园' in text:
        return 'park'
    if any(term in text for term in ('道路', '公路', '高速', 'highway', 'road')):
        return 'road'
    if any(term in text for term in ('铁路', '高铁', 'railway')):
        return 'railway'
    if any(term in text for term in ('河流', '河道', '水系', 'river')):
        return 'river'
    return 'boundary'


def _required_roles_from_intent(intent_payload):
    """Read required semantic roles from the gateway-owned Intent payload."""
    if isinstance(intent_payload, dict):
        layers = intent_payload.get('layers')
        if not isinstance(layers, list):
            return None
        roles = set()
        for layer in layers:
            if not isinstance(layer, dict) or not layer.get('role'):
                return None
            if layer.get('required', True):
                roles.add(str(layer['role']))
        return roles

    layers = getattr(intent_payload, 'layers', None)
    if layers is None:
        return None
    roles = set()
    for layer in layers:
        role = getattr(layer, 'role', None)
        if not role:
            return None
        if getattr(layer, 'required', True):
            roles.add(str(role))
    return roles


def _finalize_map_request(
    map_request,
    response,
    *,
    clarification_required=False,
    intent_text=None,
    use_latest_artifact=True,
):
    """Validate the persisted state and artifact before publishing completion."""
    from gis_mapping_agent.state import get_state_manager

    response = response if isinstance(response, dict) else {}
    intent_payload = response.get('intent_spec')
    if intent_payload is None and isinstance(response.get('intent'), (dict, list)):
        intent_payload = response.get('intent')

    if intent_payload is not None:
        required_roles = _required_roles_from_intent(intent_payload)
        if required_roles is None:
            clarification_required = True
            required_roles = set()
    else:
        # Compatibility path for historical runs that predate Intent. New
        # production callers always pass the gateway result above.
        from gis_mapping_agent.data_sources.planner import parse_intent

        legacy_intent = parse_intent(intent_text or map_request.request_text)
        required_roles = {
            layer.role for layer in legacy_intent.layers if layer.required
        }
    source_plan = response.get('source_plan') or {}
    planned_layers = {
        item.get('role'): item for item in source_plan.get('layers', []) if item.get('role')
    }
    state = get_state_manager().load_state(f'web_session_{map_request.id}')
    layers = []
    if state:
        for layer in state.layers:
            data_source = getattr(layer, 'data_source', None)
            data_source_meta = getattr(layer, 'data_source_meta', None) or {}
            dataset = _runtime_dataset_for_layer(data_source_meta)
            source_type = dataset.source_type if dataset else None
            extent = getattr(layer, 'extent', None)
            from .finalization import validate_source_spatial
            planned = planned_layers.get(_map_layer_role(getattr(layer, 'name', '')), {})
            source_plan_location = source_plan.get('location') or {}
            location_for_validation = type('ResolvedLocation', (), {
                'geometry': source_plan_location.get('geometry'),
                'bbox': source_plan_location.get('bbox') or getattr(state.config, 'extent', None),
            })()
            spatial = validate_source_spatial(layer, location_for_validation, _map_layer_role(getattr(layer, 'name', '')))
            layers.append(
                LayerValidation(
                    role=_map_layer_role(getattr(layer, 'name', '')),
                    required=False,
                    source_type=source_type,
                    feature_count=int(getattr(layer, 'feature_count', 0) or 0),
                    spatial_valid=spatial.spatial_valid,
                    geometry_valid=spatial.geometry_valid,
                    source_valid=bool(
                        dataset
                        and source_type in {'local', 'remote', 'upload'}
                        and int(getattr(dataset, 'feature_count', 0) or 0) > 0
                    )
                    and (not planned or planned.get('status') == 'available')
                    and (
                        not planned.get('dataset_id')
                        or planned.get('dataset_id') == dataset.dataset_id
                    ),
                )
            )

    latest_artifact = (
        map_request.generated_maps.order_by('-version', '-created_at', '-id').first()
        if use_latest_artifact
        else None
    )
    png_path = None
    if latest_artifact:
        png_path = Path(settings.GENERATED_MAPS_DIR) / latest_artifact.file_path
    result = finalize_execution(
        required_roles=required_roles,
        layers=layers,
        png_path=png_path,
        trace_id=response.get('tool_trace_id') or f'web_session_{map_request.id}:create',
        map_version=latest_artifact.version if latest_artifact else None,
        clarification_required=clarification_required,
        execution_error_code=response.get('error_code'),
        execution_error_message=response.get('error_message') or response.get('message'),
    )
    map_request.status = result.status
    map_request.completion_report = result.completion_report
    map_request.error_message = result.error_message or ''
    if result.status == 'partial':
        map_request.result_message = (
            f"地图已生成部分结果，但缺少必需图层："
            f"{', '.join(result.completion_report.get('missing_layers', []))}"
        )
    elif result.status == 'failed':
        map_request.result_message = result.error_message or response.get('response', '地图制作失败')
    elif result.status == 'needs_clarification':
        map_request.result_message = response.get('response', '需要补充制图信息')
    else:
        map_request.result_message = response.get('response', '地图制作完成')
    map_request.save(update_fields=[
        'status', 'completion_report', 'error_message', 'result_message', 'updated_at'
    ])
    return result


def _runtime_dataset_for_layer(data_source_meta):
    """Resolve a layer source from the runtime catalog, never from its path."""
    dataset_id = (data_source_meta or {}).get('dataset_id')
    if not dataset_id:
        return None
    try:
        dataset = Dataset.objects.filter(
            dataset_id=str(dataset_id),
            status=Dataset.STATUS_AVAILABLE,
        ).first()
        if not dataset:
            return None
        related_features = getattr(dataset, 'features', None)
        if related_features is not None:
            dataset.feature_count = related_features.count()
        return dataset if int(getattr(dataset, 'feature_count', 0) or 0) > 0 else None
    except Exception:
        return None


def _record_dispatch_failure(map_request, run, error):
    """Persist a worker submission failure so clients never observe a stuck run."""
    message = f'任务提交失败：{error}'
    final_result = _finalize_map_request(
        map_request,
        {
            'success': False,
            'status': 'failed',
            'response': message,
            'message': message,
            'error_code': 'worker_unavailable',
            'source_plan': run.source_plan if run else {},
        },
        use_latest_artifact=False,
    )
    message = final_result.error_message or message

    if run and run.status in {MapRun.STATUS_PENDING, MapRun.STATUS_RUNNING}:
        run.transition_to(
            MapRun.STATUS_FAILED,
            error_code=final_result.error_code,
            error_message=message,
            completion_report=final_result.completion_report,
        )

    _record_error_event(map_request, run, message, '任务提交')
    ChatMessage.objects.create(
        request=map_request,
        message_type='assistant',
        content=message,
    )
    _publish_lifecycle_event(
        map_request,
        'request_failed',
        message=message,
        completion_report=final_result.completion_report,
    )
    _publish_lifecycle_event(
        map_request,
        'done',
        status=final_result.status,
        message=message,
        completion_report=final_result.completion_report,
    )
    return message


def _record_run_trace(run, response):
    """Persist the agent trace when a run returns one."""
    if not run or not isinstance(response, dict):
        return
    update_fields = set()
    if response.get('tool_trace_id'):
        run.trace_id = str(response['tool_trace_id'])
        update_fields.add('trace_id')
    if response.get('source_plan'):
        run.source_plan = response['source_plan']
        update_fields.add('source_plan')
    if update_fields:
        update_fields.add('updated_at')
        run.save(update_fields=update_fields)


def _stream_encoding(stream):
    """Return the best available encoding for a console-like stream."""
    encoding = getattr(stream, "encoding", None)
    if encoding:
        return encoding

    wrapped_stream = getattr(stream, "wrapped", None)
    encoding = getattr(wrapped_stream, "encoding", None)
    if encoding:
        return encoding

    return locale.getpreferredencoding(False) or "utf-8"


def _write_stream_safely(stream, text):
    """Write diagnostic output without letting console encoding break requests."""
    try:
        stream.write(text)
    except UnicodeEncodeError:
        encoding = _stream_encoding(stream)
        safe_text = text.encode(encoding, errors="replace").decode(encoding, errors="replace")
        try:
            stream.write(safe_text)
        except Exception:
            # Terminal output is best-effort; ProcessLog still receives the full text.
            pass
    except Exception:
        pass


def _flush_stream_safely(stream):
    try:
        stream.flush()
    except Exception:
        pass


def _clear_realtime_previews(request_id):
    """Remove stale realtime preview images for a request before a new run starts."""
    try:
        base_dir = Path(settings.GENERATED_MAPS_DIR).resolve()
        preview_dir = (base_dir / "realtime_previews" / f"request_{request_id}").resolve()
        if preview_dir == base_dir or base_dir not in preview_dir.parents:
            return
        if preview_dir.exists():
            shutil.rmtree(preview_dir)
    except Exception as e:
        logging.getLogger(__name__).warning("清理实时预览目录失败: %s", e)


def _schedule_realtime_preview_cleanup(request_id, delay_seconds=60):
    """Keep terminal previews readable before removing them on a later run."""
    with _PREVIEW_CLEANUP_LOCK:
        old_timer = _PREVIEW_CLEANUP_TIMERS.pop(request_id, None)
        if old_timer:
            old_timer.cancel()

        def cleanup():
            try:
                _clear_realtime_previews(request_id)
            finally:
                with _PREVIEW_CLEANUP_LOCK:
                    _PREVIEW_CLEANUP_TIMERS.pop(request_id, None)

        timer = threading.Timer(delay_seconds, cleanup)
        timer.daemon = True
        _PREVIEW_CLEANUP_TIMERS[request_id] = timer
        timer.start()


def _cancel_realtime_preview_cleanup(request_id):
    with _PREVIEW_CLEANUP_LOCK:
        timer = _PREVIEW_CLEANUP_TIMERS.pop(request_id, None)
        if timer:
            timer.cancel()

try:
    from gis_mapping_agent import ConversationalMappingAgent
    MAP_LLM_AVAILABLE = True
except ImportError as e:
    print(f"Map-LLM 导入失败: {e}")
    MAP_LLM_AVAILABLE = False

def get_or_create_conversation_agent(session_id, user_id=None):
    """创建会话 Agent；地图状态由 session_id 持久化恢复，避免进程级对象串状态。"""
    with MAP_LLM_EXECUTION_LOCK:
        map_llm_dir = MAP_LLM_DIR
        original_cwd = os.getcwd()
        os.chdir(map_llm_dir)

        try:
            return ConversationalMappingAgent(
                session_id=session_id,
                verbose=True
            )
        finally:
            os.chdir(original_cwd)


def mapping_index(request):
    """Render the token-authenticated workbench shell."""

    get_token(request)
    context = {
        'map_llm_available': MAP_LLM_AVAILABLE,
    }
    
    context['debug'] = settings.DEBUG
    context['vite_dev_server_url'] = os.getenv('VITE_DEV_SERVER_URL', 'http://127.0.0.1:5200')
    return render(request, 'mapping/react_index.html', context)


@login_required
@csrf_exempt
@require_http_methods(["POST"])
def create_map_request(request):
    """创建新的地图制作请求"""
    try:
        data = json.loads(request.body)
        request_text = data.get('request_text', '').strip()
        
        if not request_text:
            return JsonResponse({
                'success': False,
                'message': '请输入制图需求描述'
            })

        idempotency_key = request.headers.get('Idempotency-Key', '').strip()
        if len(idempotency_key) > 255:
            return JsonResponse({
                'success': False,
                'error_code': 'invalid_idempotency_key',
                'message': 'Idempotency-Key 不能超过 255 个字符',
            }, status=400)
        if idempotency_key:
            existing = MapRequest.objects.filter(
                user=request.user,
                creation_idempotency_key=idempotency_key,
            ).first()
            if existing:
                return JsonResponse({
                    'success': True,
                    'message': '地图制作请求已存在',
                    'request_id': existing.id,
                }, status=200)
        
        # 创建地图请求
        try:
            map_request = MapRequest.objects.create(
                user=request.user,
                request_text=request_text,
                status='pending',
                completion_report={},
                creation_idempotency_key=idempotency_key or None,
            )
        except IntegrityError:
            if not idempotency_key:
                raise
            existing = MapRequest.objects.get(
                user=request.user,
                creation_idempotency_key=idempotency_key,
            )
            return JsonResponse({
                'success': True,
                'message': '地图制作请求已存在',
                'request_id': existing.id,
            }, status=200)
        
        # 创建用户消息
        ChatMessage.objects.create(
            request=map_request,
            message_type='user',
            content=request_text
        )
        
        return JsonResponse({
            'success': True,
            'message': '地图制作请求已创建',
            'request_id': map_request.id
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'创建请求失败: {str(e)}'
        })


@login_required
@csrf_exempt
@require_http_methods(["POST"])
def process_map_request(request):
    """处理地图制作请求"""
    try:
        data = json.loads(request.body)
        request_id = data.get('request_id')
        
        if not request_id:
            return JsonResponse({
                'success': False,
                'message': '缺少请求ID'
            })

        idempotency_key = request.headers.get('Idempotency-Key', '').strip()
        if len(idempotency_key) > 255:
            return JsonResponse({
                'success': False,
                'error_code': 'invalid_idempotency_key',
                'message': 'Idempotency-Key 不能超过 255 个字符',
                'retryable': False,
                'next_action': 'retry_with_valid_idempotency_key',
            }, status=400)
        
        map_request = get_object_or_404(MapRequest, id=request_id, user=request.user)

        if idempotency_key:
            existing_run = map_request.runs.filter(
                idempotency_key=idempotency_key,
            ).first()
            if existing_run:
                return JsonResponse({
                    'success': True,
                    'processing': existing_run.status in {
                        MapRun.STATUS_PENDING,
                        MapRun.STATUS_RUNNING,
                    },
                    'message': '地图制作任务已提交',
                    'request_id': map_request.id,
                    'run_id': existing_run.id,
                    'trace_id': existing_run.trace_id,
                    'status': existing_run.status,
                })
        
        if not MAP_LLM_AVAILABLE:
            # 如果 Map-LLM 不可用，返回模拟响应
            return _handle_map_llm_unavailable(map_request)

        # Admission is the only serialized section.  Agent execution starts
        # after the run row has been committed and the lock is released.
        with active_run_admission():
            map_request.refresh_from_db()
            if idempotency_key:
                existing_run = map_request.runs.filter(
                    idempotency_key=idempotency_key,
                ).first()
                if existing_run:
                    return JsonResponse({
                        'success': True,
                        'processing': existing_run.status in {
                            MapRun.STATUS_PENDING,
                            MapRun.STATUS_RUNNING,
                        },
                        'message': '地图制作任务已提交',
                        'request_id': map_request.id,
                        'run_id': existing_run.id,
                        'trace_id': existing_run.trace_id,
                        'status': existing_run.status,
                    })
            if map_request.status == 'processing':
                return JsonResponse({
                    'success': False,
                    'error_code': 'request_already_running',
                    'message': '该地图请求正在执行，请等待当前任务结束',
                    'retryable': True,
                    'next_action': 'poll_task_status',
                }, status=409)
            limit_error = active_run_capacity_error(request.user.id)
            if limit_error:
                return JsonResponse({'success': False, **limit_error}, status=429)

            # Update status and create the run in the same admission section.
            map_request.status = 'processing'
            map_request.clarification_data = {}
            map_request.save()

            ChatMessage.objects.create(
                request=map_request,
                message_type='system',
                content='正在处理您的制图请求，请稍候...'
            )

            run = MapRun.objects.create(
                request=map_request,
                idempotency_key=idempotency_key or f"legacy-{map_request.id}-{timezone.now().timestamp()}",
                trace_id=f"web_session_{map_request.id}:create",
            )

        _cancel_realtime_preview_cleanup(map_request.id)
        _clear_realtime_previews(map_request.id)
        _publish_lifecycle_event(map_request, 'request_started', message='地图制作任务已启动')

        # 后台执行制图任务，避免长 HTTP 请求阻塞实时预览/日志轮询。
        try:
            dispatch_map_request(map_request.id, run.id)
        except Exception as exc:
            message = _record_dispatch_failure(map_request, run, exc)
            return JsonResponse(
                {
                    'success': False,
                    'processing': False,
                    'message': message,
                    'error_code': 'worker_unavailable',
                    'retryable': True,
                    'next_action': 'retry_later',
                    'trace_id': run.trace_id if run else None,
                    'request_id': map_request.id,
                },
                status=503,
            )

        return JsonResponse({
            'success': True,
            'processing': True,
            'message': '地图制作任务已启动',
            'request_id': map_request.id,
            'run_id': run.id,
            'trace_id': run.trace_id,
            'status': run.status,
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'处理请求失败: {str(e)}'
        })


def _process_map_request_in_background(map_request_id, run_id=None):
    """在线程中执行制图任务，让前端可以实时轮询中间结果。"""
    close_old_connections()
    try:
        map_request = MapRequest.objects.get(id=map_request_id)
        run = MapRun.objects.get(id=run_id, request=map_request) if run_id else None
        if run:
            run.transition_to(MapRun.STATUS_RUNNING)
        with MAP_LLM_EXECUTION_LOCK:
            response = _process_with_map_llm(map_request, run)
        _record_run_trace(run, response)
        if run:
            run.refresh_from_db()
            if run.status == MapRun.STATUS_RUNNING:
                terminal_status = (
                    MapRun.STATUS_COMPLETED
                    if map_request.status == 'completed'
                    else MapRun.STATUS_PARTIAL
                    if map_request.status == 'partial'
                    else MapRun.STATUS_AWAITING_INPUT
                    if map_request.status == 'needs_clarification'
                    else MapRun.STATUS_FAILED
                )
                run.transition_to(
                    terminal_status,
                    error_message=map_request.error_message,
                    completion_report=map_request.completion_report,
                )
    except Exception as e:
        try:
            map_request = MapRequest.objects.get(id=map_request_id)
            run = MapRun.objects.filter(id=run_id, request=map_request).first() if run_id else None
            error_msg = f'后台制图失败: {str(e)}'
            final_result = _finalize_map_request(
                map_request,
                {
                    'success': False,
                    'status': 'failed',
                    'response': error_msg,
                    'message': error_msg,
                    'error_code': getattr(e, 'error_code', 'internal_error'),
                    'source_plan': run.source_plan if run else {},
            },
                use_latest_artifact=False,
            )
            error_msg = final_result.error_message or error_msg
            if run and run.status in {MapRun.STATUS_PENDING, MapRun.STATUS_RUNNING}:
                if run.status == MapRun.STATUS_PENDING:
                    run.transition_to(MapRun.STATUS_RUNNING)
                terminal_status = {
                    'needs_clarification': MapRun.STATUS_AWAITING_INPUT,
                    'completed': MapRun.STATUS_COMPLETED,
                    'partial': MapRun.STATUS_PARTIAL,
                    'failed': MapRun.STATUS_FAILED,
                }[final_result.status]
                run.transition_to(
                    terminal_status,
                    error_code=final_result.error_code,
                    error_message=final_result.error_message,
                    completion_report=final_result.completion_report,
                )
            _record_error_event(map_request, run, error_msg, '后台任务')
            ChatMessage.objects.create(
                request=map_request,
                message_type='assistant',
                content=error_msg
            )
            _publish_lifecycle_event(
                map_request,
                'request_failed',
                message=error_msg,
                completion_report=final_result.completion_report,
            )
            _publish_lifecycle_event(
                map_request,
                'done',
                status=final_result.status,
                message=error_msg,
                completion_report=final_result.completion_report,
            )
        except Exception:
            pass
    finally:
        _schedule_realtime_preview_cleanup(map_request_id)
        close_old_connections()


@login_required
@csrf_exempt
@require_http_methods(["POST"])
def continue_conversation(request):
    """继续对话 - 在现有会话中发送新消息"""
    try:
        data = json.loads(request.body)
        request_id = data.get('request_id')
        message_text = data.get('message', '').strip()

        if not request_id or not message_text:
            return JsonResponse({
                'success': False,
                'message': '缺少请求ID或消息内容'
            })

        client_message_id = request.headers.get('X-Message-Id', '').strip()
        if len(client_message_id) > 255:
            return JsonResponse({
                'success': False,
                'error_code': 'invalid_message_id',
                'message': 'X-Message-Id 不能超过 255 个字符',
            }, status=400)

        # 获取原始请求
        map_request = get_object_or_404(MapRequest, id=request_id, user=request.user)
        if client_message_id:
            existing_message = map_request.chat_messages.filter(
                client_message_id=client_message_id,
                message_type='user',
            ).first()
            if existing_message:
                latest_run = map_request.runs.order_by('-created_at', '-id').first()
                return JsonResponse({
                    'success': True,
                    'processing': map_request.status == 'processing',
                    'message': '消息已提交',
                    'request_id': map_request.id,
                    'stream_after_id': '',
                    'run_id': latest_run.id if latest_run else None,
                }, status=200)
        if not MAP_LLM_AVAILABLE:
            return JsonResponse({
                'success': False,
                'message': 'Map-LLM 不可用'
            })

        with active_run_admission():
            map_request.refresh_from_db()
            existing_message = map_request.chat_messages.filter(
                client_message_id=client_message_id,
                message_type='user',
            ).first() if client_message_id else None
            if existing_message:
                latest_run = map_request.runs.order_by('-created_at', '-id').first()
                return JsonResponse({
                    'success': True,
                    'processing': map_request.status == 'processing',
                    'message': '消息已提交',
                    'request_id': map_request.id,
                    'stream_after_id': '',
                    'run_id': latest_run.id if latest_run else None,
                }, status=200)
            if map_request.status == 'processing':
                return JsonResponse({
                    'success': False,
                    'error_code': 'request_already_running',
                    'message': '该地图请求正在执行，请等待当前任务结束',
                    'retryable': True,
                    'next_action': 'poll_task_status',
                }, status=409)
            limit_error = active_run_capacity_error(request.user.id)
            if limit_error:
                return JsonResponse({'success': False, **limit_error}, status=429)
            include_clarification_context = map_request.status == 'needs_clarification'

            ChatMessage.objects.create(
                request=map_request,
                message_type='user',
                content=message_text,
                client_message_id=client_message_id or None,
            )

            map_request.status = 'processing'
            map_request.clarification_data = {}
            map_request.save()

            run = MapRun.objects.create(
                request=map_request,
                idempotency_key=f"conversation-{map_request.id}-{timezone.now().timestamp()}",
                trace_id=f"web_session_{map_request.id}:conversation",
            )

        _cancel_realtime_preview_cleanup(map_request.id)
        _clear_realtime_previews(map_request.id)
        stream_after_id = _publish_lifecycle_event(
            map_request, 'request_started', message='地图调整任务已启动'
        )

        try:
            dispatch_conversation(
                map_request.id,
                message_text,
                run.id,
                include_clarification_context,
            )
        except Exception as exc:
            message = _record_dispatch_failure(map_request, run, exc)
            return JsonResponse(
                {
                    'success': False,
                    'processing': False,
                    'message': message,
                    'error_code': 'worker_unavailable',
                    'retryable': True,
                    'next_action': 'retry_later',
                    'trace_id': run.trace_id if run else None,
                    'request_id': map_request.id,
                },
                status=503,
            )

        return JsonResponse({
            'success': True,
            'processing': True,
            'message': '地图调整任务已启动',
            'request_id': map_request.id,
            'stream_after_id': stream_after_id,
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'继续对话失败: {str(e)}'
        })


def _build_clarification_context(map_request, message_text):
    """Combine raw user turns for a clarification retry without changing stored messages."""
    turns = list(
        ChatMessage.objects.filter(request=map_request, message_type='user')
        .order_by('created_at', 'id')
        .values_list('content', flat=True)
    )
    if not turns or turns[0] != map_request.request_text:
        turns.insert(0, map_request.request_text)
    if not turns or turns[-1] != message_text:
        turns.append(message_text)
    return '\n\n'.join(
        f'用户第{index}次制图信息：{turn}' for index, turn in enumerate(turns, start=1)
    )


def _continue_conversation_in_background(
    map_request_id, message_text, run_id=None, include_clarification_context=False
):
    """在线程中继续对话，让后续修改任务也能实时显示中间结果。"""
    close_old_connections()
    original_cwd = os.getcwd()
    original_stdout = sys.stdout
    original_stderr = sys.stderr
    response = None

    try:
        map_request = MapRequest.objects.get(id=map_request_id)
        run = MapRun.objects.get(id=run_id, request=map_request) if run_id else None
        if run:
            run.transition_to(MapRun.STATUS_RUNNING)
        session_id = f"web_session_{map_request.id}"

        with MAP_LLM_EXECUTION_LOCK:
            try:
                os.chdir(MAP_LLM_DIR)

                class StreamingOutputCapture:
                    def __init__(self, original_stream, map_request, run, stream_type='stdout'):
                        self.original_stream = original_stream
                        self.map_request = map_request
                        self.run = run
                        self.stream_type = stream_type

                    def write(self, text):
                        _write_stream_safely(self.original_stream, text)
                        _flush_stream_safely(self.original_stream)

                        if text.strip():
                            try:
                                import re
                                clean_text = re.sub(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])', '', text.strip())
                                clean_text = re.sub(r'\[(\d+)m', '', clean_text)
                                clean_text = re.sub(r'\[0m', '', clean_text)

                                if any(pattern in clean_text for pattern in ['HTTP/1.1', 'GET /mapping/api/', 'POST /mapping/api/', '"GET', '"POST']):
                                    return

                                if clean_text:
                                    step = '执行中'
                                    progress = None
                                    if '🔄 步骤' in clean_text:
                                        match = re.search(r'🔄 步骤 (\d+)/(\d+)', clean_text)
                                        if match:
                                            current_step = int(match.group(1))
                                            total_steps = int(match.group(2))
                                            progress = int((current_step / total_steps) * 100)
                                            step = f'步骤 {current_step}/{total_steps}'
                                    elif '🛠️' in clean_text:
                                        match = re.search(r'🛠️ (\w+)', clean_text)
                                        if match:
                                            step = f'使用工具: {match.group(1)}'

                                    _publish_process_log_event(
                                        self.map_request, clean_text, step=step, progress=progress, run=self.run
                                    )
                            except Exception:
                                pass

                    def flush(self):
                        _flush_stream_safely(self.original_stream)

                sys.stdout = StreamingOutputCapture(original_stdout, map_request, run, 'stdout')
                sys.stderr = StreamingOutputCapture(original_stderr, map_request, run, 'stderr')

                try:
                    from gis_mapping_agent.utils.logger import setup_logger as mapllm_setup_logger
                    mapllm_setup_logger(force_rebind=True)
                except Exception:
                    pass

                agent = get_or_create_conversation_agent(session_id, map_request.user.id)
                agent_input = (
                    _build_clarification_context(map_request, message_text)
                    if include_clarification_context
                    else message_text
                )
                response = agent.chat(agent_input, session_id=session_id)
            finally:
                try:
                    sys.stdout = original_stdout
                    sys.stderr = original_stderr
                    os.chdir(original_cwd)
                except Exception:
                    pass

        _record_run_trace(run, response)
        if isinstance(response, dict):
            response_text = response.get('response', str(response))
            success = response.get('success', True)
            needs_clarification = response.get('status') == 'needs_clarification'
            clarification = response.get('clarification') or {}
        else:
            response_text = str(response)
            success = True
            needs_clarification = False
            clarification = {}

        if needs_clarification:
            map_request.clarification_data = clarification
        elif success:
            map_request.clarification_data = {}
            _save_generated_map_info(map_request, response if isinstance(response, dict) else {})
        else:
            map_request.clarification_data = {}

        final_result = _finalize_map_request(
            map_request,
            {
                **(response if isinstance(response, dict) else {}),
                'response': response_text,
            },
            clarification_required=needs_clarification,
            intent_text=f"{map_request.request_text}\n{message_text}",
            use_latest_artifact=not needs_clarification and success,
        )
        if not success and not needs_clarification:
            map_request.error_message = response_text
            map_request.result_message = response_text
            map_request.save(update_fields=['error_message', 'result_message', 'updated_at'])

        if run:
            run.refresh_from_db()
            if run.status == MapRun.STATUS_RUNNING:
                terminal_status = {
                    'needs_clarification': MapRun.STATUS_AWAITING_INPUT,
                    'completed': MapRun.STATUS_COMPLETED,
                    'partial': MapRun.STATUS_PARTIAL,
                    'failed': MapRun.STATUS_FAILED,
                }[final_result.status]
                run.transition_to(
                    terminal_status,
                    error_code=final_result.error_code,
                    error_message=final_result.error_message,
                    completion_report=final_result.completion_report,
                )

        ChatMessage.objects.create(
            request=map_request,
            message_type='assistant',
            content=response_text,
            extra_data=clarification if needs_clarification else {},
        )
        _publish_lifecycle_event(
            map_request,
            'assistant_message',
            content=response_text,
        )
        terminal_event = {
            'needs_clarification': 'request_needs_clarification',
            'completed': 'request_completed',
            'partial': 'request_partial',
            'failed': 'request_failed',
        }[final_result.status]
        _publish_lifecycle_event(
            map_request,
            terminal_event,
            message=map_request.result_message,
            completion_report=final_result.completion_report,
        )
        _publish_lifecycle_event(
            map_request,
            'done',
            message=map_request.result_message,
            status=map_request.status,
            completion_report=final_result.completion_report,
            clarification=clarification if needs_clarification else None,
        )

    except Exception as e:
        try:
            map_request = MapRequest.objects.get(id=map_request_id)
            run = MapRun.objects.filter(id=run_id, request=map_request).first() if run_id else None
            error_msg = f'继续对话失败: {str(e)}'
            final_result = _finalize_map_request(
                map_request,
                {
                    'success': False,
                    'status': 'failed',
                    'response': error_msg,
                    'message': error_msg,
                    'error_code': getattr(e, 'error_code', 'internal_error'),
                    'source_plan': run.source_plan if run else {},
                },
                use_latest_artifact=False,
            )
            error_msg = final_result.error_message or error_msg
            if run and run.status in {MapRun.STATUS_PENDING, MapRun.STATUS_RUNNING}:
                if run.status == MapRun.STATUS_PENDING:
                    run.transition_to(MapRun.STATUS_RUNNING)
                run.transition_to(
                    MapRun.STATUS_FAILED,
                    error_code=final_result.error_code,
                    error_message=error_msg,
                    completion_report=final_result.completion_report,
                )
            _record_error_event(map_request, run, error_msg, '后台对话任务')
            _publish_lifecycle_event(
                map_request,
                'request_failed',
                message=error_msg,
                completion_report=final_result.completion_report,
            )
            _publish_lifecycle_event(
                map_request,
                'done',
                status=final_result.status,
                message=error_msg,
                completion_report=final_result.completion_report,
            )
            ChatMessage.objects.create(
                request=map_request,
                message_type='assistant',
                content=error_msg
            )
        except Exception:
            pass
    finally:
        try:
            _schedule_realtime_preview_cleanup(map_request_id)
        except Exception:
            pass
        close_old_connections()


def _handle_map_llm_unavailable(map_request):
    """Record an unavailable dependency without manufacturing a result."""
    message = 'Map-LLM 不可用，未生成地图成果'
    final_result = _finalize_map_request(
        map_request,
        {
            'success': False,
            'status': 'failed',
            'response': message,
            'message': message,
            'error_code': 'internal_error',
        },
        use_latest_artifact=False,
    )
    message = final_result.error_message or message

    ChatMessage.objects.create(
        request=map_request,
        message_type='assistant',
        content=message,
    )
    _publish_lifecycle_event(map_request, 'request_started', message='演示模式任务已启动')
    _publish_lifecycle_event(
        map_request,
        'assistant_message',
        content=message,
    )
    terminal_event = {
        'needs_clarification': 'request_needs_clarification',
        'completed': 'request_completed',
        'partial': 'request_partial',
        'failed': 'request_failed',
    }[final_result.status]
    _publish_lifecycle_event(
        map_request,
        terminal_event,
        message=message,
        completion_report=final_result.completion_report,
    )
    _publish_lifecycle_event(
        map_request,
        'done',
        status=final_result.status,
        message=message,
        completion_report=final_result.completion_report,
    )

    return {
        'success': final_result.status == 'completed',
        'status': final_result.status,
        'message': message,
        'error_code': final_result.error_code,
        'request_id': map_request.id
    }


def _process_with_map_llm(map_request, run=None):
    """使用 Map-LLM 处理地图制作请求"""
    try:
        # 保存当前工作目录
        original_cwd = os.getcwd()

        # 切换到 Map-LLM 项目目录
        map_llm_dir = MAP_LLM_DIR
        os.chdir(map_llm_dir)

        # ✅ 简化日志捕获：直接将终端输出保存到数据库，不做去重
        original_stdout = sys.stdout
        original_stderr = sys.stderr

        # 日志捕获（每次请求独立实例）

        class StreamingOutputCapture:
            def __init__(self, original_stream, map_request, run, stream_type='stdout'):
                self.original_stream = original_stream
                self.map_request = map_request
                self.run = run
                self.stream_type = stream_type

            def write(self, text):
                # 写入原始流（终端）
                _write_stream_safely(self.original_stream, text)
                _flush_stream_safely(self.original_stream)

                # 保存到数据库
                if text.strip():
                    try:
                        import re
                        # 清理ANSI代码
                        clean_text = re.sub(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])', '', text.strip())
                        clean_text = re.sub(r'\[(\d+)m', '', clean_text)
                        clean_text = re.sub(r'\[0m', '', clean_text)

                        # 跳过HTTP请求日志
                        if any(pattern in clean_text for pattern in ['HTTP/1.1', 'GET /mapping/api/', 'POST /mapping/api/', '"GET', '"POST']):
                            return

                        if clean_text:
                            step = '执行中'
                            progress = None

                            # 解析步骤信息
                            if '🔄 步骤' in clean_text:
                                match = re.search(r'🔄 步骤 (\d+)/(\d+)', clean_text)
                                if match:
                                    current_step = int(match.group(1))
                                    total_steps = int(match.group(2))
                                    progress = int((current_step / total_steps) * 100)
                                    step = f'步骤 {current_step}/{total_steps}'
                            elif '🛠️' in clean_text:
                                match = re.search(r'🛠️ (\w+)', clean_text)
                                if match:
                                    step = f'使用工具: {match.group(1)}'
                            elif 'Tool |' in clean_text:
                                if 'AddLayerTool |' in clean_text:
                                    step = '添加图层'
                                elif 'StyleLayerTool |' in clean_text:
                                    step = '样式设置'
                                elif 'InitMapTool |' in clean_text:
                                    step = '初始化地图'
                                elif 'AddScalebarTool |' in clean_text:
                                    step = '添加比例尺'
                                else:
                                    step = '工具执行'

                            _publish_process_log_event(
                                self.map_request, clean_text, step=step, progress=progress, run=self.run
                            )

                    except Exception:
                        pass

            def flush(self):
                _flush_stream_safely(self.original_stream)

        # 替换标准输出
        sys.stdout = StreamingOutputCapture(original_stdout, map_request, run, 'stdout')
        sys.stderr = StreamingOutputCapture(original_stderr, map_request, run, 'stderr')

        # 关键：将 Map-LLM 的 loguru sink 重新绑定到当前的 sys.stdout（StreamingOutputCapture）
        try:
            from gis_mapping_agent.utils.logger import setup_logger as mapllm_setup_logger
            mapllm_setup_logger(force_rebind=True)
        except Exception:
            pass

        try:
            # 使用多轮对话智能体
            # 为每个MapRequest生成唯一的session_id
            session_id = f"web_session_{map_request.id}"

            # 获取或创建对话式智能体
            agent = get_or_create_conversation_agent(session_id, map_request.user.id)

            # 使用chat方法进行多轮对话
            response = agent.chat(map_request.request_text, session_id=session_id)

            # Preserve the agent success flag so API/model failures reach the UI.
            if isinstance(response, dict):
                agent_output = response.get('response', str(response))
                agent_success = response.get('success', True)
                agent_error = response.get('error') or response.get('message')
                agent_status = response.get('status')
                clarification = response.get('clarification') or {}
                agent_trace_id = response.get('tool_trace_id')
                agent_source_plan = response.get('source_plan')
                agent_intent = response.get('intent_spec')
                if agent_intent is None and isinstance(response.get('intent'), dict):
                    agent_intent = response.get('intent')
            else:
                agent_output = str(response)
                agent_success = True
                agent_error = None
                agent_status = None
                clarification = {}
                agent_trace_id = None
                agent_source_plan = None
                agent_intent = None

            # 构造 result 格式以兼容后续处理
            result = {
                'success': agent_success,
                'agent_output': agent_output,
                'message': agent_error or '地图制作完成',
                'tool_trace_id': agent_trace_id,
                'source_plan': agent_source_plan,
                'intent_spec': agent_intent,
            }

            if agent_status == 'needs_clarification':
                map_request.clarification_data = clarification
                final_result = _finalize_map_request(
                    map_request,
                    {**result, 'response': agent_output, 'tool_trace_id': agent_trace_id},
                    clarification_required=True,
                    use_latest_artifact=False,
                )
                ChatMessage.objects.create(
                    request=map_request,
                    message_type='assistant',
                    content=agent_output,
                    extra_data=clarification,
                )
                _publish_lifecycle_event(
                    map_request,
                    'assistant_message',
                    content=agent_output,
                    clarification=clarification,
                )
                _publish_lifecycle_event(
                    map_request,
                    'request_needs_clarification',
                    message=agent_output,
                    clarification=clarification,
                )
                _publish_lifecycle_event(
                    map_request,
                    'done',
                    status=map_request.status,
                    message=agent_output,
                    clarification=clarification,
                )
                return {
                    'success': True,
                    'status': final_result.status,
                    'message': map_request.result_message,
                    'response': map_request.result_message,
                    'clarification': clarification,
                    'source_plan': agent_source_plan,
                    'request_id': map_request.id,
                    'result': result,
                }

            if result.get('success', False):
                # Agent success is only a candidate result. Persist the artifact
                # first, then let the shared finalizer decide the terminal state.
                map_request.clarification_data = {}
                _save_generated_map_info(map_request, result)
                final_result = _finalize_map_request(map_request, {
                    **result,
                    'response': result.get('agent_output', '地图制作完成'),
                    'tool_trace_id': result.get('tool_trace_id'),
                })
                final_message = map_request.result_message

                ChatMessage.objects.create(
                    request=map_request,
                    message_type='assistant',
                    content=final_message,
                )
                _publish_lifecycle_event(
                    map_request,
                    'assistant_message',
                    content=final_message,
                )
                terminal_event = (
                    'request_completed' if final_result.status == 'completed'
                    else 'request_partial' if final_result.status == 'partial'
                    else 'request_failed'
                )
                _publish_lifecycle_event(
                    map_request,
                    terminal_event,
                    message=final_message,
                    completion_report=final_result.completion_report,
                )
                _publish_lifecycle_event(
                    map_request,
                    'done',
                    message=final_message,
                    status=final_result.status,
                    completion_report=final_result.completion_report,
                )

                return {
                    'success': final_result.status == 'completed',
                    'status': final_result.status,
                    'message': final_message,
                    'response': final_message,
                    'completion_report': final_result.completion_report,
                    'source_plan': agent_source_plan,
                    'request_id': map_request.id,
                    'result': result
                }
            else:
                # Agent failure is only evidence; the finalizer owns the terminal state.
                error_msg = result.get('message', '地图制作失败')
                map_request.clarification_data = {}
                final_result = _finalize_map_request(
                    map_request,
                    {
                        **result,
                        'response': error_msg,
                    },
                    use_latest_artifact=False,
                )
                final_message = final_result.error_message or error_msg

                ChatMessage.objects.create(
                    request=map_request,
                    message_type='assistant',
                    content=final_message,
                )
                terminal_event = (
                    'request_completed' if final_result.status == 'completed'
                    else 'request_partial' if final_result.status == 'partial'
                    else 'request_needs_clarification'
                    if final_result.status == 'needs_clarification'
                    else 'request_failed'
                )
                _publish_lifecycle_event(
                    map_request,
                    terminal_event,
                    message=final_message,
                    completion_report=final_result.completion_report,
                )
                _publish_lifecycle_event(
                    map_request,
                    'done',
                    message=final_message,
                    status=final_result.status,
                    completion_report=final_result.completion_report,
                )

                return {
                    'success': final_result.status == 'completed',
                    'status': final_result.status,
                    'message': final_message,
                    'error_code': final_result.error_code or result.get('error_code') or 'agent_error',
                    'completion_report': final_result.completion_report,
                    'source_plan': agent_source_plan,
                    'request_id': map_request.id
                }

        finally:
            # 恢复原来的工作目录
            os.chdir(original_cwd)

    except Exception as e:
        # 恢复标准输出（异常情况）
        try:
            sys.stdout = original_stdout
            sys.stderr = original_stderr
        except:
            pass

        # 恢复工作目录（异常情况）
        try:
            os.chdir(original_cwd)
        except:
            pass

        # An exception is evidence only; the Finalizer owns the terminal state.
        error_msg = f"处理过程中发生错误: {str(e)}"
        final_result = _finalize_map_request(
            map_request,
            {
                'success': False,
                'status': 'failed',
                'response': error_msg,
                'message': error_msg,
                'error_code': getattr(e, 'error_code', 'internal_error'),
                'source_plan': locals().get('agent_source_plan') or {},
            },
            use_latest_artifact=False,
        )
        error_msg = final_result.error_message or error_msg

        if run and run.status in {MapRun.STATUS_PENDING, MapRun.STATUS_RUNNING}:
            if run.status == MapRun.STATUS_PENDING:
                run.transition_to(MapRun.STATUS_RUNNING)
            terminal_status = {
                'needs_clarification': MapRun.STATUS_AWAITING_INPUT,
                'completed': MapRun.STATUS_COMPLETED,
                'partial': MapRun.STATUS_PARTIAL,
                'failed': MapRun.STATUS_FAILED,
            }[final_result.status]
            run.transition_to(
                terminal_status,
                error_code=final_result.error_code,
                error_message=final_result.error_message,
                completion_report=final_result.completion_report,
            )

        _record_error_event(map_request, run, error_msg, '错误处理')

        ChatMessage.objects.create(
            request=map_request,
            message_type='assistant',
            content=error_msg
        )
        terminal_event = {
            'needs_clarification': 'request_needs_clarification',
            'completed': 'request_completed',
            'partial': 'request_partial',
            'failed': 'request_failed',
        }[final_result.status]
        _publish_lifecycle_event(
            map_request,
            terminal_event,
            message=error_msg,
            completion_report=final_result.completion_report,
        )
        _publish_lifecycle_event(
            map_request,
            'done',
            status=final_result.status,
            message=error_msg,
            completion_report=final_result.completion_report,
        )

        return {
            'success': final_result.status == 'completed',
            'status': final_result.status,
            'message': error_msg,
            'error_code': final_result.error_code or getattr(e, 'error_code', 'internal_error'),
            'completion_report': final_result.completion_report,
            'source_plan': locals().get('agent_source_plan'),
            'request_id': map_request.id
        }

    finally:
        # 最终清理 - 确保无论如何都恢复原始状态
        try:
            sys.stdout = original_stdout
            sys.stderr = original_stderr
            # 恢复工作目录
            os.chdir(original_cwd)
        except:
            pass


def _save_generated_map_info(map_request, result):
    """保存生成的地图文件信息 - 按用户和会话分层存储"""
    try:
        # 查找 outputs 目录中最新的地图文件
        outputs_dir = MAP_LLM_DIR / 'outputs'

        if outputs_dir.exists():
            # 获取最新的图片文件
            image_files = list(outputs_dir.glob('*.png')) + list(outputs_dir.glob('*.jpg'))
            if image_files:
                latest_file = max(image_files, key=os.path.getctime)

                # ✅ 方案一：按用户和会话分层存储
                # 提取会话ID（从 session_id 格式：web_session_{request_id}）
                session_id = f"session_{map_request.id}"

                # 计算当前会话的版本号（已有地图数量 + 1）
                current_version = map_request.generated_maps.count() + 1

                # 构建分层目录结构：user_{user_id}/session_{request_id}/
                user_dir = f"user_{map_request.user.id}"
                session_dir = session_id

                # ✅ 创建目录结构（与 static 同级）
                base_dir = Path(settings.GENERATED_MAPS_DIR)
                target_dir = base_dir / user_dir / session_dir
                target_dir.mkdir(parents=True, exist_ok=True)

                # 生成规范的文件名：v{version}_{original_name}
                file_extension = latest_file.suffix
                base_name = latest_file.stem
                new_filename = f"v{current_version}_{base_name}{file_extension}"
                target_file_path = target_dir / new_filename

                # 将 outputs 中的最终图片转移到 Web 成果目录，避免长期重复保存
                import shutil
                try:
                    shutil.move(str(latest_file), str(target_file_path))
                except Exception:
                    shutil.copy2(latest_file, target_file_path)
                    try:
                        latest_file.unlink()
                    except Exception:
                        pass

                # 保存到数据库（存储相对路径，相对于 GENERATED_MAPS_DIR）
                relative_path = f"{user_dir}/{session_dir}/{new_filename}"

                GeneratedMap.objects.create(
                    request=map_request,
                    filename=new_filename,
                    file_path=relative_path,
                    file_size=target_file_path.stat().st_size if target_file_path.exists() else 0,
                    version=current_version,
                    session_id=session_id
                )

                # print(f"✅ 地图文件已保存: {relative_path}")

                # 创建或更新 metadata.json
                _save_session_metadata(map_request, target_dir, current_version, new_filename, target_file_path)

    except Exception as e:
        print(f"❌ 保存地图文件信息失败: {e}")


def _save_session_metadata(map_request, session_dir, version, filename, file_path):
    """保存会话元数据到 metadata.json"""
    try:
        import hashlib

        metadata_file = session_dir / 'metadata.json'

        # 计算文件校验和
        checksum = ""
        if file_path.exists():
            with open(file_path, 'rb') as f:
                checksum = f"sha256:{hashlib.sha256(f.read()).hexdigest()}"

        # 读取现有元数据或创建新的
        if metadata_file.exists():
            with open(metadata_file, 'r', encoding='utf-8') as f:
                metadata = json.load(f)
        else:
            metadata = {
                "request_id": map_request.id,
                "user_id": map_request.user.id,
                "session_id": f"session_{map_request.id}",
                "created_at": map_request.created_at.isoformat(),
                "request_text": map_request.request_text[:200],  # 保存前200字符
                "maps": []
            }

        # 添加新地图信息
        map_info = {
            "version": version,
            "filename": filename,
            "size": file_path.stat().st_size if file_path.exists() else 0,
            "checksum": checksum,
            "created_at": timezone.now().isoformat()
        }
        metadata["maps"].append(map_info)
        metadata["updated_at"] = timezone.now().isoformat()

        # 写入文件
        with open(metadata_file, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)

        # print(f"✅ 元数据已更新: {metadata_file}")

    except Exception as e:
        print(f"⚠️ 保存元数据失败: {e}")
        import traceback
        traceback.print_exc()


@login_required
def get_chat_messages(request, request_id):
    """获取聊天消息"""
    try:
        map_request = get_object_or_404(MapRequest, id=request_id, user=request.user)
        messages = map_request.chat_messages.all()
        
        messages_data = []
        for msg in messages:
            messages_data.append({
                'id': msg.id,
                'type': msg.message_type,
                'content': msg.content,
                'created_at': msg.created_at.isoformat(),
                'extra_data': msg.extra_data
            })
        
        return JsonResponse({
            'success': True,
            'messages': messages_data,
            'request_status': map_request.status
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'获取消息失败: {str(e)}'
        })


@login_required
def get_generated_maps(request, request_id):
    """获取生成的地图文件"""
    try:
        map_request = get_object_or_404(MapRequest, id=request_id, user=request.user)
        # 	2	3	4
        #
        #
        #
        #
        maps = map_request.generated_maps.order_by('-created_at')

        maps_data = []
        for map_obj in maps:
            # ✅ 构建完整的文件路径（从 GENERATED_MAPS_DIR）
            full_file_path = os.path.join(settings.GENERATED_MAPS_DIR, map_obj.file_path)
            file_exists = os.path.exists(full_file_path)

            # 构建 Web 访问路径
            web_path = f"/generated_maps/{map_obj.file_path}"

            maps_data.append({
                'id': map_obj.id,
                'request_id': map_request.id,
                'filename': map_obj.filename,
                'version': map_obj.version,
                'file_path': web_path,  # 返回 Web 访问路径
                'file_size': map_obj.file_size,
                'file_exists': file_exists,
                'created_at': map_obj.created_at.isoformat()
            })
        
        return JsonResponse({
            'success': True,
            'maps': maps_data
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'获取地图文件失败: {str(e)}'
        })


@login_required
@require_http_methods(["GET"])
def get_history_maps(request):
    """Return the current user's generated map history grouped by request."""
    try:
        try:
            limit = int(request.GET.get("limit", 30))
        except (TypeError, ValueError):
            limit = 30
        limit = max(1, min(limit, 100))

        requests = (
            MapRequest.objects
            .filter(user=request.user, generated_maps__isnull=False)
            .distinct()
            .order_by("-updated_at")[:limit]
        )

        sessions_data = []
        for map_request in requests:
            latest_run = map_request.runs.order_by("-created_at", "-id").first()
            maps_data = []
            for map_obj in map_request.generated_maps.order_by("-created_at"):
                full_file_path = os.path.join(settings.GENERATED_MAPS_DIR, map_obj.file_path)
                file_exists = os.path.exists(full_file_path)
                maps_data.append({
                    "id": map_obj.id,
                    "request_id": map_request.id,
                    "filename": map_obj.filename,
                    "version": map_obj.version,
                    "file_path": f"/generated_maps/{map_obj.file_path}",
                    "file_size": map_obj.file_size,
                    "file_exists": file_exists,
                    "created_at": map_obj.created_at.isoformat(),
                })

            if not maps_data:
                continue

            sessions_data.append({
                "request_id": map_request.id,
                "title": map_request.title or map_request.request_text[:40] or f"地图请求 {map_request.id}",
                "request_text": map_request.request_text,
                "status": map_request.status,
                "created_at": map_request.created_at.isoformat(),
                "updated_at": map_request.updated_at.isoformat(),
                "maps": maps_data,
                "clarification": map_request.clarification_data or None,
                "view_state": _load_latest_view_state(map_request),
                "latest_run": {
                    "id": latest_run.id,
                    "status": latest_run.status,
                    "trace_id": latest_run.trace_id,
                    "error_code": latest_run.error_code,
                    "error_message": latest_run.error_message,
                } if latest_run else None,
            })

        return JsonResponse({
            "success": True,
            "sessions": sessions_data,
        })

    except Exception as e:
        return JsonResponse({
            "success": False,
            "message": f"获取历史地图失败: {str(e)}",
        })


def _load_latest_view_state(map_request):
    """Load the latest persisted map context for the history workbench."""
    try:
        from gis_mapping_agent.state import get_state_manager

        manager = get_state_manager()
        session_id = f"web_session_{map_request.id}"
        versions = manager.list_versions(session_id)
        if not versions:
            return None
        current = next((item for item in versions if item.get("is_current")), versions[-1])
        version = current.get("version")
        state = manager.load_state(session_id, version)
        if state is None:
            return None
        from .realtime import _view_state

        return _view_state(state)
    except Exception:
        return None


@login_required
@csrf_exempt
@require_http_methods(["POST"])
def activate_history_map(request):
    """Set a historical generated map's MapState version as the active version."""
    try:
        data = json.loads(request.body or "{}")
        map_id = data.get("map_id")
        if not map_id:
            return JsonResponse({
                "success": False,
                "message": "缺少历史地图ID",
            })

        generated_map = get_object_or_404(
            GeneratedMap,
            id=map_id,
            request__user=request.user,
        )
        map_request = generated_map.request
        session_id = f"web_session_{map_request.id}"

        try:
            from gis_mapping_agent.state import get_state_manager
            state_manager = get_state_manager()
            map_state = state_manager.load_state(session_id, generated_map.version)
            if not map_state:
                return JsonResponse({
                    "success": True,
                    "active_state": False,
                    "request_id": map_request.id,
                    "map_id": generated_map.id,
                    "version": generated_map.version,
                    "message": "已切换历史图片，但未找到对应状态版本；继续修改时可能使用该会话最新状态。",
                })

            versions = state_manager.list_versions(session_id)
            version_numbers = [item.get("version") for item in versions if item.get("version") is not None]
            latest_version = max(version_numbers) if version_numbers else generated_map.version
            current_version = next(
                (item.get("version") for item in versions if item.get("is_current")),
                latest_version,
            )
            active_version = generated_map.version
            cloned = False

            if generated_map.version != current_version:
                selected_version = generated_map.version
                active_version = latest_version + 1
                map_state.version_info.version = active_version
                map_state.version_info.parent_version = selected_version
                map_state.version_info.description = f"Activated from history map v{selected_version}"
                map_state.version_info.is_current = True
                map_state.version_info.created_at = timezone.now()

            state_manager.save_state(map_state)
            cloned = active_version != generated_map.version
            return JsonResponse({
                "success": True,
                "active_state": True,
                "request_id": map_request.id,
                "map_id": generated_map.id,
                "version": generated_map.version,
                "active_version": active_version,
                "cloned": cloned,
                "message": (
                    f"已基于历史地图 v{generated_map.version} 创建当前可修改状态 v{active_version}"
                    if cloned else f"已激活历史地图版本 v{generated_map.version}"
                ),
            })

        except Exception as state_error:
            return JsonResponse({
                "success": True,
                "active_state": False,
                "request_id": map_request.id,
                "map_id": generated_map.id,
                "version": generated_map.version,
                "message": f"已切换历史图片，但激活状态版本失败: {state_error}",
            })

    except Exception as e:
        return JsonResponse({
            "success": False,
            "message": f"激活历史地图失败: {str(e)}",
        })


@login_required
@require_http_methods(["GET"])
def get_latest_realtime_preview(request, request_id):
    """获取当前制图请求最新的 Matplotlib 中间预览图。"""
    try:
        get_object_or_404(MapRequest, id=request_id, user=request.user)

        preview_dir = Path(settings.GENERATED_MAPS_DIR) / "realtime_previews" / f"request_{request_id}"
        if not preview_dir.exists():
            return JsonResponse({
                "success": True,
                "preview": None,
            })

        preview_files = sorted(
            preview_dir.glob("*.png"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if not preview_files:
            return JsonResponse({
                "success": True,
                "preview": None,
            })

        latest = preview_files[0]
        relative_path = latest.relative_to(Path(settings.GENERATED_MAPS_DIR)).as_posix()
        return JsonResponse({
            "success": True,
            "preview": {
                "image_url": f"/generated_maps/{relative_path}",
                "filename": latest.name,
                "created_at_ms": int(latest.stat().st_mtime * 1000),
                "file_size": latest.stat().st_size,
            },
        })

    except Exception as e:
        return JsonResponse({
            "success": False,
            "message": f"获取实时预览失败: {str(e)}",
        })


@login_required
@require_http_methods(["GET"])
def get_process_logs(request, request_id):
    """获取处理过程的实时日志"""
    try:
        map_request = get_object_or_404(MapRequest, id=request_id, user=request.user)

        # Historical views may contain several adjustment runs.  Scope the
        # log stream when the caller has selected a particular run so the log
        # count and Trace count describe the same execution.
        since = request.GET.get('since')
        run_id = request.GET.get('run_id')
        selected_run = None
        if run_id not in (None, ''):
            try:
                selected_run = MapRun.objects.filter(
                    id=int(run_id), request=map_request
                ).first()
            except (TypeError, ValueError):
                return JsonResponse({
                    'success': False,
                    'message': 'run_id 必须是整数'
                }, status=400)
            if selected_run is None:
                return JsonResponse({
                    'success': False,
                    'message': '指定的执行记录不存在'
                }, status=404)

        if since:
            try:
                since_time = timezone.datetime.fromisoformat(since.replace('Z', '+00:00'))
                logs = ProcessLog.objects.filter(request=map_request, created_at__gte=since_time)
            except ValueError:
                logs = ProcessLog.objects.filter(request=map_request)
        else:
            logs = ProcessLog.objects.filter(request=map_request)
        if selected_run is not None:
            logs = logs.filter(run=selected_run)
        logs = logs.order_by('created_at', 'id')

        run_context = _current_run_context(map_request)
        log_data = []
        for log in logs.select_related('run'):
            log_context = (
                {'run_id': log.run_id, 'trace_id': log.run.trace_id or None}
                if log.run_id and log.run
                else run_context
            )
            log_data.append({
                'id': log.id,
                'event_id': log.event_id,
                'event_seq': log.event_seq,
                'event_type': log.event_type,
                'phase': log.phase or log.step,
                'parent_event_id': log.parent_event_id or None,
                'status': 'error' if log.level == 'error' else log.status,
                'duration_ms': log.duration_ms,
                'has_details': bool(log.input_data or log.output_data or log.attributes or log.error is not None),
                'level': log.level,
                'message': log.message,
                'step': log.step,
                'progress': log.progress,
                'created_at': log.created_at.isoformat(),
                'run_id': log_context['run_id'],
                'trace_id': log_context['trace_id'],
            })

        return JsonResponse({
            'success': True,
            'logs': log_data,
            'status': map_request.status
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'获取日志失败: {str(e)}'
        }, status=500)


# 自定义日志处理器，用于捕获Map-LLM的输出
class DatabaseLogHandler(logging.Handler):
    """将日志写入数据库的处理器"""

    def __init__(self, map_request, run=None):
        super().__init__()
        self.map_request = map_request
        self.run = run

    def emit(self, record):
        try:
            # 解析日志消息
            raw_message = self.format(record)
            level = record.levelname.lower()

            # 清理ANSI颜色代码
            message = self._clean_ansi_codes(raw_message)

            # 过滤掉一些不需要的日志
            if self._should_skip_message(message):
                return

            # 如果消息为空或只有空白字符，跳过
            if not message.strip():
                return

            # 解析Map-LLM特有的输出格式
            step, progress = self._parse_map_llm_message(message)

            _publish_process_log_event(
                self.map_request,
                message,
                level=level,
                step=step,
                progress=progress,
                run=self.run,
            )

        except Exception:
            # 避免日志处理器本身出错影响主程序
            pass

    def _should_skip_message(self, message):
        """判断是否应该跳过某些消息"""
        # 只跳过空消息和HTTP日志
        if not message.strip():
            return True

        http_patterns = ['HTTP/1.1', 'GET /mapping/api/', 'POST /mapping/api/', '"GET', '"POST']
        return any(pattern in message for pattern in http_patterns)

    def _clean_ansi_codes(self, message):
        """清理ANSI颜色代码"""
        import re
        # 移除ANSI颜色代码
        ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
        cleaned = ansi_escape.sub('', message)

        # 移除其他常见的颜色代码格式
        cleaned = re.sub(r'\[(\d+)m', '', cleaned)
        cleaned = re.sub(r'\[0m', '', cleaned)

        return cleaned.strip()

    def _parse_map_llm_message(self, message):
        """解析Map-LLM消息，提取步骤和进度信息"""
        step = ''
        progress = None

        # 解析步骤信息
        if '🔄 步骤' in message:
            import re
            match = re.search(r'🔄 步骤 (\d+)/(\d+)', message)
            if match:
                current_step = int(match.group(1))
                total_steps = int(match.group(2))
                progress = int((current_step / total_steps) * 100)
                step = f'步骤 {current_step}/{total_steps}'

        # 解析工具名称
        elif '🛠️' in message:
            import re
            match = re.search(r'🛠️ (\w+)', message)
            if match:
                step = f'使用工具: {match.group(1)}'

        # 解析工具输出
        elif 'Tool |' in message or 'AddLayerTool |' in message or 'StyleLayerTool |' in message:
            if 'AddLayerTool |' in message:
                step = '添加图层'
            elif 'StyleLayerTool |' in message:
                step = '样式设置'
            elif 'InitMapTool |' in message:
                step = '初始化地图'
            elif 'AddScalebarTool |' in message:
                step = '添加比例尺'
            else:
                step = '工具执行'

        # 解析成功/失败状态
        elif '✅ 成功' in message:
            step = '操作成功'
        elif '❌ 失败' in message:
            step = '操作失败'

        return step, progress


@login_required
@csrf_exempt
@require_http_methods(["POST"])
def convert_map_format(request):
    """
    转换地图格式API
    支持将PNG格式转换为JPG、PDF、SVG等格式
    """
    try:
        data = json.loads(request.body)
        file_path = data.get('file_path', '')
        target_format = data.get('target_format', 'png').lower()
        map_id = data.get('map_id')

        # 验证格式
        supported_formats = ['png', 'jpg', 'jpeg', 'pdf', 'svg']
        if target_format not in supported_formats:
            return JsonResponse({
                'success': False,
                'message': f'不支持的格式: {target_format}'
            })

        # 解析文件路径
        # file_path 格式: /generated_maps/user_X/session_Y/filename.png
        print(f"[DEBUG] 接收到的文件路径: {file_path}")

        if file_path.startswith('/generated_maps/'):
            relative_path = file_path.replace('/generated_maps/', '')
        else:
            return JsonResponse({
                'success': False,
                'message': f'无效的文件路径: {file_path}'
            })

        # 构建完整的源文件路径
        source_file = Path(settings.GENERATED_MAPS_DIR) / relative_path
        print(f"[DEBUG] 源文件完整路径: {source_file}")
        print(f"[DEBUG] 文件是否存在: {source_file.exists()}")
        print(f"[DEBUG] GENERATED_MAPS_DIR: {settings.GENERATED_MAPS_DIR}")

        if not source_file.exists():
            return JsonResponse({
                'success': False,
                'message': f'源文件不存在: {source_file}'
            })

        # 生成目标文件路径
        target_file = source_file.with_suffix(f'.{target_format}')

        # 使用PIL进行格式转换
        from PIL import Image
        import io

        try:
            # 打开源图片
            img = Image.open(source_file)

            # 根据目标格式进行转换
            if target_format in ['jpg', 'jpeg']:
                # JPG不支持透明度，需要转换为RGB
                if img.mode in ('RGBA', 'LA', 'P'):
                    # 创建白色背景
                    background = Image.new('RGB', img.size, (255, 255, 255))
                    if img.mode == 'P':
                        img = img.convert('RGBA')
                    background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                    img = background
                else:
                    img = img.convert('RGB')
                img.save(target_file, 'JPEG', quality=95, optimize=True)

            elif target_format == 'pdf':
                # PDF转换
                if img.mode in ('RGBA', 'LA'):
                    # PDF不支持透明度
                    background = Image.new('RGB', img.size, (255, 255, 255))
                    background.paste(img, mask=img.split()[-1])
                    img = background
                else:
                    img = img.convert('RGB')
                img.save(target_file, 'PDF', resolution=100.0, optimize=True)

            elif target_format == 'svg':
                # SVG转换需要特殊处理
                # 这里使用简单的方法：将PNG嵌入到SVG中
                import base64

                # 读取PNG文件并转换为base64
                with open(source_file, 'rb') as f:
                    img_data = base64.b64encode(f.read()).decode('utf-8')

                # 获取图片尺寸
                width, height = img.size

                # 创建SVG文件
                svg_content = f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"
     width="{width}" height="{height}" viewBox="0 0 {width} {height}">
    <image width="{width}" height="{height}"
           xlink:href="data:image/png;base64,{img_data}"/>
</svg>'''

                with open(target_file, 'w', encoding='utf-8') as f:
                    f.write(svg_content)

            elif target_format == 'png':
                # PNG格式直接保存
                img.save(target_file, 'PNG', optimize=True)

            # 关闭图片
            img.close()

            # 构建Web访问路径
            target_relative_path = str(target_file.relative_to(settings.GENERATED_MAPS_DIR))
            web_path = f"/generated_maps/{target_relative_path}"

            return JsonResponse({
                'success': True,
                'message': f'格式转换成功: {target_format.upper()}',
                'file_url': web_path,
                'file_size': target_file.stat().st_size
            })

        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': f'图片转换失败: {str(e)}'
            })

    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'message': '无效的JSON数据'
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'转换失败: {str(e)}'
        })
