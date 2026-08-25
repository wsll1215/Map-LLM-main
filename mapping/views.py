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
from django.views.decorators.http import require_http_methods
from django.conf import settings
from django.utils import timezone
from django.db import close_old_connections

from .models import MapRequest, MapRun, GeneratedMap, ChatMessage, ProcessLog
from .realtime import publish_map_build_event
from .task_dispatch import dispatch_conversation, dispatch_map_request

MAP_LLM_DIR = settings.BASE_DIR
if str(MAP_LLM_DIR) not in sys.path:
    sys.path.insert(0, str(MAP_LLM_DIR))

MAP_LLM_EXECUTION_LOCK = threading.RLock()


def _publish_lifecycle_event(map_request, event_type, **extra):
    """Publish request lifecycle state without coupling generation to SSE."""
    payload = {
        "type": event_type,
        "request_id": map_request.id,
        "status": map_request.status,
        "created_at_ms": int(timezone.now().timestamp() * 1000),
    }
    payload.update(extra)
    return publish_map_build_event(map_request.id, payload)


def _publish_process_log_event(map_request, message, *, level='info', step=None, progress=None):
    publish_map_build_event(map_request.id, {
        'type': 'process_log',
        'request_id': map_request.id,
        'level': level,
        'message': str(message),
        'step': step,
        'progress': progress,
        'created_at_ms': int(timezone.now().timestamp() * 1000),
    })


def _record_dispatch_failure(map_request, run, error):
    """Persist a worker submission failure so clients never observe a stuck run."""
    message = f'任务提交失败：{error}'
    map_request.status = 'failed'
    map_request.error_message = message
    map_request.result_message = message
    map_request.clarification_data = {}
    map_request.save()

    if run and run.status in {MapRun.STATUS_PENDING, MapRun.STATUS_RUNNING}:
        run.transition_to(MapRun.STATUS_FAILED, error_message=message)

    ProcessLog.objects.create(
        request=map_request,
        level='error',
        message=message,
        step='任务提交',
    )
    ChatMessage.objects.create(
        request=map_request,
        message_type='assistant',
        content=message,
    )
    _publish_lifecycle_event(map_request, 'request_failed', message=message)
    _publish_lifecycle_event(map_request, 'done', status='failed', message=message)
    return message


def _record_run_trace(run, response):
    """Persist the agent trace when a run returns one."""
    if not run or not isinstance(response, dict) or not response.get('tool_trace_id'):
        return
    run.trace_id = str(response['tool_trace_id'])
    run.save(update_fields={'trace_id', 'updated_at'})


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


@login_required
def mapping_index(request):
    """地图制作主页"""
    # 获取用户最近的地图制作请求
    recent_requests = MapRequest.objects.filter(user=request.user)[:10]
    
    context = {
        'recent_requests': recent_requests,
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
        
        # 创建地图请求
        map_request = MapRequest.objects.create(
            user=request.user,
            request_text=request_text,
            status='pending'
        )
        
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
        
        map_request = get_object_or_404(MapRequest, id=request_id, user=request.user)
        
        if not MAP_LLM_AVAILABLE:
            # 如果 Map-LLM 不可用，返回模拟响应
            return _handle_map_llm_unavailable(map_request)
        
        # 更新状态为处理中
        map_request.status = 'processing'
        map_request.clarification_data = {}
        map_request.save()
        _clear_realtime_previews(map_request.id)
        _publish_lifecycle_event(map_request, 'request_started', message='地图制作任务已启动')
        
        # 创建系统消息
        ChatMessage.objects.create(
            request=map_request,
            message_type='system',
            content='正在处理您的制图请求，请稍候...'
        )
        
        # 后台执行制图任务，避免长 HTTP 请求阻塞实时预览/日志轮询。
        run = MapRun.objects.create(
            request=map_request,
            idempotency_key=f"legacy-{map_request.id}-{timezone.now().timestamp()}",
            trace_id=f"web_session_{map_request.id}:create",
        )
        try:
            dispatch_map_request(map_request.id, run.id)
        except Exception as exc:
            message = _record_dispatch_failure(map_request, run, exc)
            return JsonResponse(
                {
                    'success': False,
                    'processing': False,
                    'message': message,
                    'request_id': map_request.id,
                },
                status=503,
            )

        return JsonResponse({
            'success': True,
            'processing': True,
            'message': '地图制作任务已启动',
            'request_id': map_request.id
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
            response = _process_with_map_llm(map_request)
        _record_run_trace(run, response)
        if run:
            run.refresh_from_db()
            if run.status == MapRun.STATUS_RUNNING:
                terminal_status = (
                    MapRun.STATUS_COMPLETED
                    if map_request.status == 'completed'
                    else MapRun.STATUS_AWAITING_INPUT
                    if map_request.status == 'needs_clarification'
                    else MapRun.STATUS_FAILED
                )
                run.transition_to(
                    terminal_status,
                    error_message=map_request.error_message,
                )
    except Exception as e:
        try:
            map_request = MapRequest.objects.get(id=map_request_id)
            run = MapRun.objects.filter(id=run_id, request=map_request).first() if run_id else None
            map_request.status = 'failed'
            map_request.error_message = f'后台制图失败: {str(e)}'
            map_request.save()
            if run and run.status in {MapRun.STATUS_PENDING, MapRun.STATUS_RUNNING}:
                if run.status == MapRun.STATUS_PENDING:
                    run.transition_to(MapRun.STATUS_RUNNING)
                run.transition_to(MapRun.STATUS_FAILED, error_message=map_request.error_message)
            ProcessLog.objects.create(
                request=map_request,
                level='error',
                message=map_request.error_message,
                step='后台任务'
            )
            ChatMessage.objects.create(
                request=map_request,
                message_type='assistant',
                content=map_request.error_message
            )
            _publish_lifecycle_event(
                map_request,
                'request_failed',
                message=map_request.error_message,
            )
            _publish_lifecycle_event(map_request, 'done', message=map_request.error_message)
        except Exception:
            pass
    finally:
        _clear_realtime_previews(map_request_id)
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

        # 获取原始请求
        map_request = get_object_or_404(MapRequest, id=request_id, user=request.user)
        include_clarification_context = map_request.status == 'needs_clarification'

        if not MAP_LLM_AVAILABLE:
            return JsonResponse({
                'success': False,
                'message': 'Map-LLM 不可用'
            })

        # 创建用户消息
        ChatMessage.objects.create(
            request=map_request,
            message_type='user',
            content=message_text
        )

        # 更新状态
        map_request.status = 'processing'
        map_request.clarification_data = {}
        map_request.save()

        _clear_realtime_previews(map_request.id)
        stream_after_id = _publish_lifecycle_event(
            map_request, 'request_started', message='地图调整任务已启动'
        )

        run = MapRun.objects.create(
            request=map_request,
            idempotency_key=f"conversation-{map_request.id}-{timezone.now().timestamp()}",
            trace_id=f"web_session_{map_request.id}:conversation",
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
                    def __init__(self, original_stream, map_request, stream_type='stdout'):
                        self.original_stream = original_stream
                        self.map_request = map_request
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

                                    ProcessLog.objects.create(
                                        request=self.map_request,
                                        level='info',
                                        message=clean_text,
                                        step=step,
                                        progress=progress
                                    )
                                    _publish_process_log_event(
                                        self.map_request, clean_text, step=step, progress=progress
                                    )
                            except Exception:
                                pass

                    def flush(self):
                        _flush_stream_safely(self.original_stream)

                sys.stdout = StreamingOutputCapture(original_stdout, map_request, 'stdout')
                sys.stderr = StreamingOutputCapture(original_stderr, map_request, 'stderr')

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
            map_request.status = 'needs_clarification'
            map_request.error_message = ''
            map_request.result_message = response_text
            map_request.clarification_data = clarification
        elif success:
            map_request.status = 'completed'
            map_request.error_message = ''
            map_request.result_message = response_text
            map_request.clarification_data = {}
            _save_generated_map_info(map_request, response if isinstance(response, dict) else {})
        else:
            map_request.status = 'failed'
            map_request.error_message = response_text
            map_request.result_message = response_text
            map_request.clarification_data = {}
        map_request.save()

        if run:
            run.refresh_from_db()
            if run.status == MapRun.STATUS_RUNNING:
                terminal_status = (
                    MapRun.STATUS_AWAITING_INPUT
                    if needs_clarification
                    else MapRun.STATUS_COMPLETED
                    if success
                    else MapRun.STATUS_FAILED
                )
                run.transition_to(
                    terminal_status,
                    error_message=None if success else response_text,
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
        terminal_event = (
            'request_needs_clarification'
            if needs_clarification
            else 'request_completed' if success else 'request_failed'
        )
        _publish_lifecycle_event(map_request, terminal_event, message=response_text)
        _publish_lifecycle_event(
            map_request,
            'done',
            message=response_text,
            status=map_request.status,
            clarification=clarification if needs_clarification else None,
        )

    except Exception as e:
        try:
            map_request = MapRequest.objects.get(id=map_request_id)
            run = MapRun.objects.filter(id=run_id, request=map_request).first() if run_id else None
            error_msg = f'继续对话失败: {str(e)}'
            map_request.status = 'failed'
            map_request.error_message = error_msg
            map_request.result_message = error_msg
            map_request.save()
            if run and run.status in {MapRun.STATUS_PENDING, MapRun.STATUS_RUNNING}:
                if run.status == MapRun.STATUS_PENDING:
                    run.transition_to(MapRun.STATUS_RUNNING)
                run.transition_to(MapRun.STATUS_FAILED, error_message=error_msg)
            ProcessLog.objects.create(
                request=map_request,
                level='error',
                message=error_msg,
                step='后台对话任务'
            )
            _publish_lifecycle_event(map_request, 'request_failed', message=error_msg)
            _publish_lifecycle_event(map_request, 'done', message=error_msg)
            ChatMessage.objects.create(
                request=map_request,
                message_type='assistant',
                content=error_msg
            )
        except Exception:
            pass
    finally:
        try:
            _clear_realtime_previews(map_request_id)
        except Exception:
            pass
        close_old_connections()


def _handle_map_llm_unavailable(map_request):
    """处理 Map-LLM 不可用的情况 - 返回演示响应"""
    map_request.status = 'completed'
    map_request.result_message = '演示模式：地图制作功能正常'
    map_request.save()

    ChatMessage.objects.create(
        request=map_request,
        message_type='assistant',
        content='''地图制作功能已就绪！

当前为演示模式，Map-LLM 集成功能包括：
✅ 智能制图请求处理
✅ 聊天界面交互
✅ 地图文件管理
✅ 用户会话记录

要启用完整的 Map-LLM 功能，请：
1. 确保 Map-LLM 项目在正确位置
2. 安装相关依赖包
3. 配置 API 密钥

您的制图需求已记录，系统架构运行正常！'''
    )
    _publish_lifecycle_event(map_request, 'request_started', message='演示模式任务已启动')
    _publish_lifecycle_event(
        map_request,
        'assistant_message',
        content=map_request.result_message,
    )
    _publish_lifecycle_event(map_request, 'request_completed', message=map_request.result_message)
    _publish_lifecycle_event(map_request, 'done', message=map_request.result_message)

    return {
        'success': True,
        'message': '演示模式：功能正常',
        'request_id': map_request.id
    }


def _process_with_map_llm(map_request):
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
            def __init__(self, original_stream, map_request, stream_type='stdout'):
                self.original_stream = original_stream
                self.map_request = map_request
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

                            ProcessLog.objects.create(
                                request=self.map_request,
                                level='info',
                                message=clean_text,
                                step=step,
                                progress=progress
                            )
                            _publish_process_log_event(
                                self.map_request, clean_text, step=step, progress=progress
                            )

                    except Exception:
                        pass

            def flush(self):
                _flush_stream_safely(self.original_stream)

        # 替换标准输出
        sys.stdout = StreamingOutputCapture(original_stdout, map_request, 'stdout')
        sys.stderr = StreamingOutputCapture(original_stderr, map_request, 'stderr')

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
            else:
                agent_output = str(response)
                agent_success = True
                agent_error = None
                agent_status = None
                clarification = {}
                agent_trace_id = None

            # 构造 result 格式以兼容后续处理
            result = {
                'success': agent_success,
                'agent_output': agent_output,
                'message': agent_error or '地图制作完成',
                'tool_trace_id': agent_trace_id,
            }

            if agent_status == 'needs_clarification':
                map_request.status = 'needs_clarification'
                map_request.result_message = agent_output
                map_request.error_message = ''
                map_request.clarification_data = clarification
                map_request.save()
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
                    'status': 'needs_clarification',
                    'message': agent_output,
                    'response': agent_output,
                    'clarification': clarification,
                    'request_id': map_request.id,
                    'result': result,
                }

            if result.get('success', False):
                # 处理成功
                map_request.status = 'completed'
                map_request.result_message = result.get('agent_output', '地图制作完成')
                map_request.clarification_data = {}
                map_request.save()

                # 创建助手回复消息
                ChatMessage.objects.create(
                    request=map_request,
                    message_type='assistant',
                    content=result.get('agent_output', '地图制作完成')
                )

                # 查找生成的地图文件
                _save_generated_map_info(map_request, result)
                _publish_lifecycle_event(
                    map_request,
                    'assistant_message',
                    content=result.get('agent_output', '地图制作完成'),
                )
                _publish_lifecycle_event(
                    map_request,
                    'request_completed',
                    message=result.get('agent_output', '地图制作完成'),
                )
                _publish_lifecycle_event(map_request, 'done', message=result.get('agent_output', '地图制作完成'))

                return {
                    'success': True,
                    'message': '地图制作完成',
                    'response': result.get('agent_output', '地图制作完成'),  # ✅ 只返回 agent_output 内容
                    'request_id': map_request.id,
                    'result': result
                }
            else:
                # 处理失败
                error_msg = result.get('message', '地图制作失败')
                map_request.status = 'failed'
                map_request.error_message = error_msg
                map_request.result_message = f'地图制作失败：{error_msg}'
                map_request.clarification_data = {}
                map_request.save()

                ChatMessage.objects.create(
                    request=map_request,
                    message_type='assistant',
                    content=f"地图制作失败：{error_msg}"
                )
                _publish_lifecycle_event(map_request, 'request_failed', message=error_msg)
                _publish_lifecycle_event(map_request, 'done', message=error_msg)

                return {
                    'success': False,
                    'message': error_msg,
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

        # 异常处理
        error_msg = f"处理过程中发生错误: {str(e)}"
        map_request.status = 'failed'
        map_request.error_message = error_msg
        map_request.result_message = error_msg
        map_request.save()

        ProcessLog.objects.create(
            request=map_request,
            level='error',
            message=error_msg,
            step='错误处理'
        )

        ChatMessage.objects.create(
            request=map_request,
            message_type='assistant',
            content=error_msg
        )
        _publish_lifecycle_event(map_request, 'request_failed', message=error_msg)
        _publish_lifecycle_event(map_request, 'done', message=error_msg)

        return {
            'success': False,
            'message': error_msg,
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

        # 获取最新的日志
        since = request.GET.get('since')
        if since:
            try:
                since_time = timezone.datetime.fromisoformat(since.replace('Z', '+00:00'))
                logs = ProcessLog.objects.filter(
                    request=map_request,
                    created_at__gte=since_time
                ).order_by('created_at')
            except ValueError:
                logs = ProcessLog.objects.filter(request=map_request).order_by('created_at')
        else:
            logs = ProcessLog.objects.filter(request=map_request).order_by('created_at')

        log_data = []
        for log in logs:
            log_data.append({
                'id': log.id,
                'level': log.level,
                'message': log.message,
                'step': log.step,
                'progress': log.progress,
                'created_at': log.created_at.isoformat()
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

    def __init__(self, map_request):
        super().__init__()
        self.map_request = map_request

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

            # 保存到数据库
            ProcessLog.objects.create(
                request=self.map_request,
                level=level,
                message=message,
                step=step,
                progress=progress
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
