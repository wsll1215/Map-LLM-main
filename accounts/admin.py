from django.contrib import admin
from .models import UserProfile
from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import Group
from django.utils.html import format_html
from django.db.models import Count
from django.utils import timezone
from datetime import timedelta

# 取消注册Group模型
admin.site.unregister(Group)


class UserProfileAdmin(admin.ModelAdmin):
    """增强型用户管理"""

    # 列表页显示字段
    list_display = (
        'id',
        'colored_username',
        'email_display',
        'superuser_badge',
        'active_badge',
        'maps_count',
        'last_login_display',
        'date_joined_display'
    )

    # 搜索字段
    search_fields = ['username', 'id', 'email']

    # 添加列表过滤器
    list_filter = ('is_superuser', 'is_active', 'is_staff', 'date_joined')

    # 列表页每页显示的记录数
    list_per_page = 20

    # 不使用列表页直接编辑，改用批量操作
    list_editable = ()

    # 只读字段
    readonly_fields = (
        'date_joined',
        'last_login',
        'user_stats_display'
    )

    # 字段分组
    fieldsets = (
        ('用户基本信息', {
            'fields': ('username', 'email', 'mpassword'),
            'classes': ('wide', 'extrapretty'),
        }),
        ('权限信息', {
            'fields': ('is_superuser', 'is_staff', 'is_active'),
            'classes': ('wide',),
            'description': '设置用户权限和状态'
        }),
        ('时间信息', {
            'fields': ('date_joined', 'last_login'),
            'classes': ('collapse',),
        }),
        ('统计信息', {
            'fields': ('user_stats_display',),
            'classes': ('wide',),
        }),
    )

    # 批量操作
    actions = ['activate_users', 'deactivate_users', 'make_superuser', 'remove_superuser']

    # 为字段添加颜色和样式
    def colored_username(self, obj):
        """彩色用户名"""
        if obj.is_superuser:
            return format_html(
                '<span style="color: #e74c3c; font-weight: bold;">👑 {}</span>',
                obj.username
            )
        return format_html(
            '<span style="color: #3498db;">{}</span>',
            obj.username
        )
    colored_username.short_description = '用户名'
    colored_username.admin_order_field = 'username'

    def email_display(self, obj):
        """邮箱显示"""
        if obj.email:
            return format_html('<span style="color: #7f8c8d;">📧 {}</span>', obj.email)
        return format_html('<span style="color: #bdc3c7;">未设置</span>')
    email_display.short_description = '邮箱'

    def superuser_badge(self, obj):
        """超级用户徽章"""
        if obj.is_superuser:
            return format_html(
                '<span style="background-color: #e74c3c; color: white; padding: 3px 8px; '
                'border-radius: 3px; font-size: 11px;">超级管理员</span>'
            )
        return format_html(
            '<span style="background-color: #95a5a6; color: white; padding: 3px 8px; '
            'border-radius: 3px; font-size: 11px;">普通用户</span>'
        )
    superuser_badge.short_description = '权限'

    def active_badge(self, obj):
        """激活状态徽章"""
        if obj.is_active:
            return format_html(
                '<span style="background-color: #27ae60; color: white; padding: 3px 8px; '
                'border-radius: 3px; font-size: 11px;">✓ 激活</span>'
            )
        return format_html(
            '<span style="background-color: #e67e22; color: white; padding: 3px 8px; '
            'border-radius: 3px; font-size: 11px;">✗ 未激活</span>'
        )
    active_badge.short_description = '状态'

    def maps_count(self, obj):
        """地图数量"""
        from mapping.models import MapRequest
        count = MapRequest.objects.filter(user=obj).count()
        if count > 0:
            return format_html(
                '<span style="color: #3498db; font-weight: bold;">🗺️ {}</span>',
                count
            )
        return format_html('<span style="color: #bdc3c7;">0</span>')
    maps_count.short_description = '地图数量'

    def last_login_display(self, obj):
        """最后登录时间"""
        if obj.last_login:
            now = timezone.now()
            diff = now - obj.last_login

            if diff < timedelta(minutes=5):
                return format_html('<span style="color: #27ae60;">🟢 刚刚</span>')
            elif diff < timedelta(hours=1):
                return format_html('<span style="color: #27ae60;">🟢 {}分钟前</span>', int(diff.seconds / 60))
            elif diff < timedelta(days=1):
                return format_html('<span style="color: #f39c12;">🟡 {}小时前</span>', int(diff.seconds / 3600))
            elif diff < timedelta(days=7):
                return format_html('<span style="color: #e67e22;">🟠 {}天前</span>', diff.days)
            else:
                return format_html('<span style="color: #95a5a6;">⚪ {}</span>', obj.last_login.strftime('%Y-%m-%d'))
        return format_html('<span style="color: #bdc3c7;">从未登录</span>')
    last_login_display.short_description = '最后登录'

    def date_joined_display(self, obj):
        """加入时间"""
        return format_html(
            '<span style="color: #7f8c8d;">📅 {}</span>',
            obj.date_joined.strftime('%Y-%m-%d %H:%M')
        )
    date_joined_display.short_description = '加入时间'
    date_joined_display.admin_order_field = 'date_joined'

    def user_stats_display(self, obj):
        """用户统计信息"""
        from mapping.models import MapRequest

        total_requests = MapRequest.objects.filter(user=obj).count()
        completed_requests = MapRequest.objects.filter(user=obj, status='completed').count()
        failed_requests = MapRequest.objects.filter(user=obj, status='failed').count()

        success_rate = (completed_requests / total_requests * 100) if total_requests > 0 else 0

        return format_html(
            '<div style="padding: 10px; background-color: #f8f9fa; border-radius: 5px;">'
            '<p><strong>📊 用户统计</strong></p>'
            '<p>总请求数: <span style="color: #3498db; font-weight: bold;">{}</span></p>'
            '<p>已完成: <span style="color: #27ae60; font-weight: bold;">{}</span></p>'
            '<p>失败: <span style="color: #e74c3c; font-weight: bold;">{}</span></p>'
            '<p>成功率: <span style="color: #f39c12; font-weight: bold;">{:.1f}%</span></p>'
            '</div>',
            total_requests, completed_requests, failed_requests, success_rate
        )
    user_stats_display.short_description = '用户统计'

    # 批量操作方法
    def activate_users(self, request, queryset):
        """激活用户"""
        updated = queryset.update(is_active=True)
        self.message_user(request, f'成功激活 {updated} 个用户')
    activate_users.short_description = '激活所选用户'

    def deactivate_users(self, request, queryset):
        """停用用户"""
        updated = queryset.update(is_active=False)
        self.message_user(request, f'成功停用 {updated} 个用户')
    deactivate_users.short_description = '停用所选用户'

    def make_superuser(self, request, queryset):
        """设为超级用户"""
        updated = queryset.update(is_superuser=True, is_staff=True)
        self.message_user(request, f'成功将 {updated} 个用户设为超级管理员')
    make_superuser.short_description = '设为超级管理员'

    def remove_superuser(self, request, queryset):
        """取消超级用户"""
        updated = queryset.update(is_superuser=False)
        self.message_user(request, f'成功取消 {updated} 个用户的超级管理员权限')
    remove_superuser.short_description = '取消超级管理员'

    # 添加自定义CSS和JS
    class Media:
        css = {
            'all': ('css/admin_custom.css',)
        }
        js = ('js/admin_custom.js',)

    def save_model(self, request, obj, form, change):
        """保存模型时处理密码"""
        if form.is_valid():
            # 如果修改了密码字段，则更新password
            if 'mpassword' in form.changed_data and obj.mpassword:
                obj.password = make_password(obj.mpassword)
        super().save_model(request, obj, form, change)


# 注册模型
admin.site.register(UserProfile, UserProfileAdmin)

# 自定义Admin站点标题和头部
admin.site.site_title = "智能GIS制图系统 - 管理后台"
admin.site.site_header = "智能GIS制图系统 - 管理后台"
admin.site.index_title = "欢迎使用智能GIS制图系统"