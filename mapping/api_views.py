"""
REST API 视图
提供会话和地图文件管理的 API 接口
"""
from django.http import JsonResponse, FileResponse, HttpResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.utils import timezone
from django.conf import settings
from pathlib import Path
import json
import os
import shutil
import zipfile
from datetime import timedelta
from .models import MapRequest, GeneratedMap, ChatMessage


@login_required
@require_http_methods(["GET"])
def list_user_sessions(request):
    """获取用户的所有会话列表"""
    user_id = request.GET.get('user_id')
    
    if not user_id:
        return JsonResponse({'error': '缺少 user_id 参数'}, status=400)
    
    # 查询用户的所有请求
    sessions = MapRequest.objects.filter(user_id=user_id).values(
        'id', 'title', 'status', 'created_at', 'updated_at'
    ).annotate(
        maps_count=Count('generated_maps')
    ).order_by('-created_at')
    
    # 添加会话目录信息
    result = []
    for session in sessions:
        session_dir = Path(settings.GENERATED_MAPS_DIR) / f"user_{user_id}" / f"session_{session['id']}"
        
        session_data = {
            'id': session['id'],
            'title': session['title'] or '未命名地图',
            'status': session['status'],
            'maps_count': session['maps_count'],
            'created_at': session['created_at'].isoformat(),
            'updated_at': session['updated_at'].isoformat(),
            'has_files': session_dir.exists()
        }
        
        # 读取 metadata.json
        if session_dir.exists():
            metadata_file = session_dir / "metadata.json"
            if metadata_file.exists():
                try:
                    with open(metadata_file, 'r', encoding='utf-8') as f:
                        metadata = json.load(f)
                    session_data['metadata'] = metadata
                except:
                    pass
        
        result.append(session_data)
    
    return JsonResponse({
        'success': True,
        'count': len(result),
        'sessions': result
    })


@login_required
@require_http_methods(["GET"])
def get_session_detail(request, session_id):
    """获取会话详情"""
    try:
        session = MapRequest.objects.get(id=session_id)
    except MapRequest.DoesNotExist:
        return JsonResponse({'error': '会话不存在'}, status=404)
    
    # 基本信息
    data = {
        'id': session.id,
        'user_id': session.user.id,
        'username': session.user.username,
        'title': session.title or '未命名地图',
        'request_text': session.request_text,
        'status': session.status,
        'created_at': session.created_at.isoformat(),
        'updated_at': session.updated_at.isoformat(),
    }
    
    # 地图列表
    maps = []
    for gen_map in session.generated_maps.all():
        map_data = {
            'id': gen_map.id,
            'filename': gen_map.filename,
            'version': gen_map.version,
            'file_size': gen_map.file_size,
            'created_at': gen_map.created_at.isoformat(),
        }
        
        # 生成访问URL
        if gen_map.file_path and os.path.exists(gen_map.file_path):
            rel_path = os.path.relpath(gen_map.file_path, settings.BASE_DIR)
            map_data['url'] = f"/{rel_path.replace(os.sep, '/')}"
            map_data['exists'] = True
        else:
            map_data['exists'] = False
        
        maps.append(map_data)
    
    data['maps'] = maps
    
    # 聊天消息
    messages = []
    for msg in session.chat_messages.all():
        messages.append({
            'type': msg.message_type,
            'content': msg.content,
            'created_at': msg.created_at.isoformat()
        })
    
    data['messages'] = messages
    
    # 会话目录信息
    session_dir = Path(settings.GENERATED_MAPS_DIR) / f"user_{session.user.id}" / f"session_{session.id}"
    
    if session_dir.exists():
        # 读取 metadata.json
        metadata_file = session_dir / "metadata.json"
        if metadata_file.exists():
            try:
                with open(metadata_file, 'r', encoding='utf-8') as f:
                    data['metadata'] = json.load(f)
            except:
                pass
        
        # 计算目录大小
        total_size = sum(f.stat().st_size for f in session_dir.rglob('*') if f.is_file())
        data['storage_size'] = total_size
    
    return JsonResponse({
        'success': True,
        'session': data
    })


@login_required
@require_http_methods(["DELETE"])
def delete_session(request, session_id):
    """删除会话"""
    try:
        session = MapRequest.objects.get(id=session_id)
    except MapRequest.DoesNotExist:
        return JsonResponse({'error': '会话不存在'}, status=404)
    
    # 删除文件目录
    session_dir = Path(settings.GENERATED_MAPS_DIR) / f"user_{session.user.id}" / f"session_{session.id}"
    
    deleted_size = 0
    if session_dir.exists():
        # 计算大小
        deleted_size = sum(f.stat().st_size for f in session_dir.rglob('*') if f.is_file())
        
        # 删除目录
        shutil.rmtree(session_dir)
    
    # 删除数据库记录
    session.delete()
    
    return JsonResponse({
        'success': True,
        'message': '会话已删除',
        'deleted_size': deleted_size
    })


@login_required
@require_http_methods(["GET"])
def download_session(request, session_id):
    """下载会话的所有文件（打包为ZIP）"""
    try:
        session = MapRequest.objects.get(id=session_id)
    except MapRequest.DoesNotExist:
        return JsonResponse({'error': '会话不存在'}, status=404)
    
    session_dir = Path(settings.GENERATED_MAPS_DIR) / f"user_{session.user.id}" / f"session_{session.id}"
    
    if not session_dir.exists():
        return JsonResponse({'error': '会话目录不存在'}, status=404)
    
    # 创建临时ZIP文件
    zip_filename = f"session_{session_id}_{timezone.now().strftime('%Y%m%d_%H%M%S')}.zip"
    zip_path = Path(settings.BASE_DIR) / 'temp' / zip_filename
    zip_path.parent.mkdir(exist_ok=True)
    
    # 打包文件
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for file in session_dir.rglob('*'):
            if file.is_file():
                arcname = file.relative_to(session_dir)
                zipf.write(file, arcname)
    
    # 返回文件
    response = FileResponse(open(zip_path, 'rb'), content_type='application/zip')
    response['Content-Disposition'] = f'attachment; filename="{zip_filename}"'
    
    return response




@login_required
@require_http_methods(["POST"])
def cleanup_old_sessions(request):
    """清理旧会话"""
    try:
        data = json.loads(request.body)
        days = data.get('days', 30)
        keep_sessions = data.get('keep_sessions', 5)
    except:
        days = 30
        keep_sessions = 5
    
    cutoff_date = timezone.now() - timedelta(days=days)
    
    # 获取所有用户
    from django.contrib.auth import get_user_model
    User = get_user_model()
    
    deleted_count = 0
    deleted_size = 0
    
    for user in User.objects.all():
        # 获取用户的所有会话，按时间倒序
        sessions = MapRequest.objects.filter(user=user).order_by('-created_at')
        
        # 保留最近的 N 个会话
        sessions_to_keep = set(s.id for s in sessions[:keep_sessions])
        
        # 删除超过指定天数且不在保留列表中的会话
        old_sessions = sessions.filter(created_at__lt=cutoff_date).exclude(id__in=sessions_to_keep)
        
        for session in old_sessions:
            session_dir = Path(settings.GENERATED_MAPS_DIR) / f"user_{user.id}" / f"session_{session.id}"
            
            if session_dir.exists():
                # 计算大小
                size = sum(f.stat().st_size for f in session_dir.rglob('*') if f.is_file())
                deleted_size += size
                
                # 删除目录
                shutil.rmtree(session_dir)
            
            # 删除数据库记录
            session.delete()
            deleted_count += 1
    
    return JsonResponse({
        'success': True,
        'deleted_count': deleted_count,
        'deleted_size': deleted_size,
        'message': f'成功清理 {deleted_count} 个会话，释放空间 {deleted_size} 字节'
    })


@login_required
@require_http_methods(["POST"])
@csrf_exempt
def delete_generated_map(request, map_id):
    """删除单个生成的地图文件和数据库记录"""
    try:
        # 获取地图对象
        generated_map = GeneratedMap.objects.get(id=map_id)

        # 检查权限：只有地图所属请求的用户或管理员才能删除
        if generated_map.request and generated_map.request.user != request.user and not request.user.is_staff:
            return JsonResponse({
                'success': False,
                'error': '没有权限删除此地图'
            }, status=403)

        # 获取文件路径用于日志
        file_path = generated_map.file_path
        filename = generated_map.filename

        # 删除地图（会自动删除文件）
        generated_map.delete()

        return JsonResponse({
            'success': True,
            'message': f'成功删除地图: {filename}',
            'deleted_file': file_path
        })

    except GeneratedMap.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': '地图不存在'
        }, status=404)

    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': f'删除失败: {str(e)}'
        }, status=500)

