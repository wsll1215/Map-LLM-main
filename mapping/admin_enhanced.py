"""
增强型 Django Admin 配置
提供完整的会话和地图文件管理功能
"""
from django.contrib import admin
from django.utils.html import format_html
from django.urls import path, reverse
from django.shortcuts import render, redirect
from django.http import JsonResponse, HttpResponse, FileResponse
from django.db.models import Count, Sum, Q
from django.utils import timezone
from datetime import timedelta
import os
import json
from pathlib import Path
from .models import MapRequest, GeneratedMap, ChatMessage, ProcessLog
from django.conf import settings

# 导入数据库管理模块
from . import db_admin


class GeneratedMapInline(admin.StackedInline):
    """地图文件内联显示"""
    model = GeneratedMap
    extra = 0
    readonly_fields = ('map_card_display',)
    fields = ('map_card_display',)
    can_delete = False  # 禁用默认删除，使用自定义删除按钮
    show_change_link = False  # 不显示修改链接
    verbose_name = '生成的地图'
    verbose_name_plural = '生成的地图'

    def has_add_permission(self, request, obj=None):
        """禁用添加新地图"""
        return False

    # 添加自定义 CSS 隐藏 inline 标题
    class Media:
        css = {
            'all': ('css/admin_inline_custom.css',)
        }
        js = ('js/admin_map_delete.js',)

    def map_card_display(self, obj):
        """地图卡片显示（合并所有信息）"""
        if obj.file_path:
            # 构建完整的文件路径
            full_path = os.path.join(settings.GENERATED_MAPS_DIR, obj.file_path)

            # 检查文件是否存在
            if os.path.exists(full_path):
                # 生成访问URL（相对于 generated_maps 目录）
                url = f"/generated_maps/{obj.file_path.replace(os.sep, '/')}"

                # 格式化文件大小
                size_str = '-'
                if obj.file_size:
                    size = obj.file_size
                    for unit in ['B', 'KB', 'MB', 'GB']:
                        if size < 1024.0:
                            size_str = f"{size:.1f} {unit}"
                            break
                        size /= 1024.0

                # 格式化时间
                time_str = obj.created_at.strftime('%Y年%m月%d日 %H:%M')

                return format_html(
                    '<div style="display:flex; align-items:center; padding:15px; background:#f9f9f9; border:1px solid #ddd; border-radius:8px; margin:10px 0; position:relative;">'
                        '<div style="flex-shrink:0; margin-right:20px;">'
                            '<a href="{}" target="_blank">'
                                '<img src="{}" style="width:150px; height:150px; object-fit:cover; border:2px solid #ddd; border-radius:8px; box-shadow:0 2px 4px rgba(0,0,0,0.1);"/>'
                            '</a>'
                        '</div>'
                        '<div style="flex-grow:1;">'
                            '<div style="font-size:16px; font-weight:bold; color:#333; margin-bottom:10px;">📍 版本 v{}</div>'
                            '<div style="font-size:13px; color:#666; margin-bottom:5px;">📄 文件名: {}</div>'
                            '<div style="font-size:13px; color:#666; margin-bottom:5px;">💾 大小: {}</div>'
                            '<div style="font-size:13px; color:#666;">🕐 创建时间: {}</div>'
                        '</div>'
                        '<div style="position:absolute; top:10px; right:10px;">'
                            '<button type="button" class="delete-map-btn" data-map-id="{}" style="padding:8px 12px; background:#dc3545; color:white; border:none; border-radius:4px; cursor:pointer; font-size:12px; font-weight:bold;">🗑️ 删除</button>'
                        '</div>'
                    '</div>',
                    url, url, obj.version, obj.filename, size_str, time_str, obj.id
                )

        # 文件不存在
        return format_html(
            '<div style="padding:15px; background:#fff3cd; border:1px solid #ffc107; border-radius:8px; color:#856404;">'
                '⚠️ 文件不存在: {}'
            '</div>',
            obj.filename
        )

    map_card_display.short_description = ''  # 不显示标题


class ChatMessageInline(admin.StackedInline):
    """聊天消息内联显示"""
    model = ChatMessage
    extra = 0
    readonly_fields = ('message_card_display',)
    fields = ('message_card_display',)
    can_delete = False
    verbose_name = '对话消息'
    verbose_name_plural = '对话消息'

    # 添加自定义 CSS 隐藏 inline 标题
    class Media:
        css = {
            'all': ('css/admin_inline_custom.css',)
        }

    def has_add_permission(self, request, obj=None):
        """禁用添加新消息"""
        return False

    def message_card_display(self, obj):
        """消息卡片显示（合并所有信息）"""
        content = obj.content[:500] + '...' if len(obj.content) > 500 else obj.content

        # 格式化时间
        time_str = obj.created_at.strftime('%Y年%m月%d日 %H:%M')

        # 根据消息类型设置样式
        if obj.message_type == 'user':
            icon = '👤'
            color = '#2196F3'
            bg_color = '#E3F2FD'
            border_color = '#2196F3'
            label = '用户'
        elif obj.message_type == 'assistant':
            icon = '🤖'
            color = '#4CAF50'
            bg_color = '#E8F5E9'
            border_color = '#4CAF50'
            label = '助手'
        elif obj.message_type == 'system':
            icon = '⚙️'
            color = '#FF9800'
            bg_color = '#FFF3E0'
            border_color = '#FF9800'
            label = '系统'
        else:
            icon = '📝'
            color = '#999'
            bg_color = '#F5F5F5'
            border_color = '#999'
            label = '其他'

        return format_html(
            '<div style="padding:15px; background:{}; border-left:4px solid {}; border-radius:8px; margin:10px 0; box-shadow:0 1px 3px rgba(0,0,0,0.1);">'
                '<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">'
                    '<span style="color:{}; font-weight:bold; font-size:14px;">{} {}</span>'
                    '<span style="color:#999; font-size:12px;">🕐 {}</span>'
                '</div>'
                '<div style="color:#333; line-height:1.6; white-space:pre-wrap; font-size:13px;">{}</div>'
            '</div>',
            bg_color, border_color, color, icon, label, time_str, content
        )

    message_card_display.short_description = ''  # 不显示标题


@admin.register(MapRequest)
class MapRequestAdminEnhanced(admin.ModelAdmin):
    """增强型地图请求管理"""
    
    list_display = (
        'colored_user',
        'request_preview',
        'status_badge',
        'maps_count',
        'created_at_display',
        'action_buttons'
    )
    
    list_filter = (
        'status', 
        'created_at',
        ('user', admin.RelatedOnlyFieldListFilter),
    )
    
    search_fields = ('title', 'user__username', 'request_text', 'session_id')
    
    readonly_fields = (
        'created_at',
        'updated_at',
        'session_info_display',
        'storage_info_display'
    )

    fieldsets = (
        ('基本信息', {
            'fields': ('user', 'status', 'created_at', 'updated_at', 'session_info_display', 'storage_info_display')
        }),
    )
    
    inlines = [GeneratedMapInline, ChatMessageInline]

    actions = [
        'delete_selected_with_files',
        'mark_as_completed'
    ]

    list_per_page = 20

    # 自定义模板
    change_form_template = 'admin/mapping/maprequest_change_form.html'

    # 加载 JavaScript 文件
    class Media:
        js = ('js/admin_mapping.js',)

    # 隐藏不需要的按钮
    def has_add_permission(self, request):
        """隐藏"添加另一个"按钮"""
        return False

    def response_add(self, request, obj, post_url_continue=None):
        """保存后直接返回列表页"""
        return redirect('admin:mapping_maprequest_changelist')

    def response_change(self, request, obj):
        """保存后直接返回列表页"""
        return redirect('admin:mapping_maprequest_changelist')
    
    # ==================== 自定义显示字段 ====================
    
    def colored_user(self, obj):
        """彩色用户名"""
        return format_html(
            '<span style="color:#2196F3; font-weight:bold;">👤 {}</span>',
            obj.user.username
        )
    colored_user.short_description = '用户'
    colored_user.admin_order_field = 'user__username'

    def request_preview(self, obj):
        """请求内容预览"""
        text = obj.request_text or '无内容'
        preview = text[:50] + '...' if len(text) > 50 else text
        return format_html('<span title="{}">{}</span>', text, preview)
    request_preview.short_description = '请求内容'
    
    def status_badge(self, obj):
        """状态徽章"""
        colors = {
            'pending': '#FFC107',
            'processing': '#2196F3',
            'completed': '#4CAF50',
            'failed': '#F44336'
        }
        icons = {
            'pending': '⏳',
            'processing': '⚙️',
            'completed': '✅',
            'failed': '❌'
        }
        color = colors.get(obj.status, '#999')
        icon = icons.get(obj.status, '❓')
        return format_html(
            '<span style="background:{}; color:white; padding:3px 8px; border-radius:3px; font-size:12px;">'
            '{} {}</span>',
            color, icon, obj.get_status_display()
        )
    status_badge.short_description = '状态'
    status_badge.admin_order_field = 'status'
    
    def maps_count(self, obj):
        """地图数量"""
        count = obj.generated_maps.count()
        if count > 0:
            return format_html(
                '<span style="background:#E3F2FD; color:#1976D2; padding:2px 6px; border-radius:3px;">'
                '📊 {} 个版本</span>',
                count
            )
        return format_html('<span style="color:#999;">无地图</span>')
    maps_count.short_description = '地图版本'
    

    def created_at_display(self, obj):
        """创建时间显示"""
        now = timezone.now()
        diff = now - obj.created_at
        
        if diff < timedelta(hours=1):
            return format_html('<span style="color:#4CAF50;">🕐 {} 分钟前</span>', diff.seconds // 60)
        elif diff < timedelta(days=1):
            return format_html('<span style="color:#2196F3;">🕐 {} 小时前</span>', diff.seconds // 3600)
        elif diff < timedelta(days=7):
            return format_html('<span style="color:#FF9800;">📅 {} 天前</span>', diff.days)
        else:
            return format_html('<span style="color:#999;">📅 {}</span>', obj.created_at.strftime('%Y-%m-%d'))
    created_at_display.short_description = '创建时间'
    created_at_display.admin_order_field = 'created_at'
    
    def action_buttons(self, obj):
        """操作按钮"""
        buttons = []
        
        # 查看详情按钮
        detail_url = reverse('admin:mapping_maprequest_change', args=[obj.id])
        buttons.append(f'<a href="{detail_url}" style="color:#2196F3; margin-right:8px;">📝 详情</a>')
        
        # 下载按钮（如果有地图）
        if obj.generated_maps.exists():
            download_url = reverse('admin:mapping_download_session', args=[obj.id])
            buttons.append(f'<a href="{download_url}" style="color:#4CAF50; margin-right:8px;">⬇️ 下载</a>')
        
        # 删除按钮
        buttons.append(f'<a href="#" onclick="deleteSession({obj.id}); return false;" style="color:#F44336;">🗑️ 删除</a>')
        
        return format_html(' '.join(buttons))
    action_buttons.short_description = '操作'
    
    def session_info_display(self, obj):
        """会话信息显示"""
        info = []
        info.append(f"<strong>📋 请求ID:</strong> {obj.id}")
        info.append(f"<strong>👤 用户ID:</strong> {obj.user.id}")
        info.append(f"<strong>👤 用户名:</strong> {obj.user.username}")

        if hasattr(obj, 'session_id') and obj.session_id:
            info.append(f"<strong>🔑 会话ID:</strong> {obj.session_id}")

        # 获取生成的地图数量
        maps_count = obj.generated_maps.count()
        info.append(f"<strong>🗺️ 地图数量:</strong> {maps_count}")

        # 获取聊天消息数量
        messages_count = obj.chat_messages.count()
        info.append(f"<strong>💬 消息数量:</strong> {messages_count}")

        session_dir = Path(settings.GENERATED_MAPS_DIR) / f"user_{obj.user.id}" / f"session_{obj.id}"
        if session_dir.exists():
            info.append(f"<strong>📁 会话目录:</strong> {session_dir}")

            # 读取 metadata.json
            metadata_file = session_dir / "metadata.json"
            if metadata_file.exists():
                try:
                    with open(metadata_file, 'r', encoding='utf-8') as f:
                        metadata = json.load(f)
                    info.append(f"<strong>📊 元数据地图数:</strong> {len(metadata.get('maps', []))}")
                    info.append(f"<strong>🕐 最后更新:</strong> {metadata.get('updated_at', 'N/A')}")
                except Exception as e:
                    info.append(f"<strong>⚠️ 元数据读取失败:</strong> {str(e)}")
        else:
            info.append(f"<strong>⚠️ 会话目录:</strong> 不存在")

        return format_html('<br>'.join(info))
    session_info_display.short_description = '会话详情'
    
    def storage_info_display(self, obj):
        """存储信息显示"""
        session_dir = Path(settings.GENERATED_MAPS_DIR) / f"user_{obj.user.id}" / f"session_{obj.id}"

        if not session_dir.exists():
            return format_html('<span style="color:#999;">⚠️ 会话目录不存在</span>')

        try:
            # 计算目录大小
            total_size = sum(f.stat().st_size for f in session_dir.rglob('*') if f.is_file())

            # 格式化大小
            size = total_size
            for unit in ['B', 'KB', 'MB', 'GB']:
                if size < 1024.0:
                    size_str = f"{size:.1f} {unit}"
                    break
                size /= 1024.0

            # 文件数量
            file_count = len(list(session_dir.rglob('*.png')))

            info = []
            info.append(f"<strong>💾 存储大小:</strong> {size_str}")
            info.append(f"<strong>📄 文件数量:</strong> {file_count} 个")
            info.append(f"<strong>📁 目录路径:</strong> <code style='background:#f5f5f5; padding:2px 4px; border-radius:3px;'>{session_dir}</code>")

            return format_html('<br>'.join(info))
        except Exception as e:
            return format_html('<span style="color:#F44336;">❌ 存储信息读取失败: {}</span>', str(e))
    storage_info_display.short_description = '存储信息'

    # ==================== 删除处理 ====================

    def has_delete_permission(self, request, obj=None):
        """禁用默认的删除权限，只使用自定义的批量删除操作"""
        return False

    def delete_model(self, request, obj):
        """覆盖删除单个模型的方法，确保调用自定义的 delete() 方法"""
        obj.delete()

    # ==================== 批量操作 ====================

    def delete_selected_with_files(self, request, queryset):
        """删除选中的会话（包括会话文件、生成的地图、日志和聊天消息）"""
        deleted_count = 0
        deleted_size = 0

        # 必须逐个删除，以确保调用每个对象的 delete() 方法
        # 这样才能触发 MapRequest.delete() 中的文件删除逻辑
        for obj in queryset:
            # 计算会话目录大小
            session_dir = Path(settings.GENERATED_MAPS_DIR) / f"user_{obj.user.id}" / f"session_{obj.id}"
            if session_dir.exists():
                try:
                    deleted_size += sum(f.stat().st_size for f in session_dir.rglob('*') if f.is_file())
                except Exception as e:
                    print(f"计算目录大小失败: {e}")

            # 删除对象（会自动删除文件和数据库记录）
            # 重要：必须调用 obj.delete() 而不是 queryset.delete()
            # 这样才能触发 MapRequest 模型的 delete() 方法
            try:
                obj.delete()
                deleted_count += 1
            except Exception as e:
                print(f"删除会话失败: {obj.id}, 错误: {e}")

        # 格式化大小
        size = deleted_size
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024.0:
                size_str = f"{size:.1f} {unit}"
                break
            size /= 1024.0

        self.message_user(request, f'✅ 成功删除 {deleted_count} 个会话，释放空间 {size_str}（包括会话文件、生成的地图、日志和聊天消息）')

    delete_selected_with_files.short_description = '🗑️ 删除选中的会话（包括所有文件）'

    def mark_as_completed(self, request, queryset):
        """标记为已完成"""
        updated = queryset.update(status='completed')
        self.message_user(request, f'成功标记 {updated} 个会话为已完成')

    mark_as_completed.short_description = '✅ 标记为已完成'

    # ==================== 自定义URL和视图 ====================

    def get_urls(self):
        """添加自定义URL"""
        urls = super().get_urls()
        custom_urls = [
            path('download/<int:request_id>/', self.admin_site.admin_view(self.download_session), name='mapping_download_session'),
            path('preview/<int:map_id>/', self.admin_site.admin_view(self.preview_map), name='mapping_preview_map'),
        ]
        return custom_urls + urls

    def download_session(self, request, request_id):
        """下载会话文件"""
        obj = MapRequest.objects.get(id=request_id)
        session_dir = Path(settings.GENERATED_MAPS_DIR) / f"user_{obj.user.id}" / f"session_{obj.id}"

        if not session_dir.exists():
            return JsonResponse({'error': '会话目录不存在'}, status=404)

        # TODO: 实现打包下载
        return JsonResponse({'message': '下载功能开发中...'})

    def preview_map(self, request, map_id):
        """预览地图"""
        gen_map = GeneratedMap.objects.get(id=map_id)

        if not gen_map.file_path or not os.path.exists(gen_map.file_path):
            return JsonResponse({'error': '文件不存在'}, status=404)

        return FileResponse(open(gen_map.file_path, 'rb'), content_type='image/png')


# GeneratedMapAdminEnhanced 已删除
# 生成的地图现在仅作为 MapRequest 的内联模型显示，不再作为独立的 Admin 模块

