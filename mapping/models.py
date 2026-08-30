from django.db import models
from django.contrib.gis.db import models as gis_models
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils import timezone
import json
import os
import shutil
import uuid
from pathlib import Path

User = get_user_model()


def _new_trace_event_id():
    return f"evt_{uuid.uuid4().hex}"


class MapRequest(models.Model):
    """地图制作请求模型"""
    
    STATUS_CHOICES = [
        ('pending', '等待处理'),
        ('processing', '处理中'),
        ('needs_clarification', '等待补充信息'),
        ('completed', '已完成'),
        ('partial', '部分完成'),
        ('failed', '失败'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name='用户')
    title = models.CharField(max_length=200, verbose_name='地图标题', blank=True)
    request_text = models.TextField(verbose_name='制图需求描述')
    creation_idempotency_key = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name='创建幂等键',
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', verbose_name='状态')
    
    # 地图配置参数（JSON格式存储）
    map_config = models.JSONField(default=dict, verbose_name='地图配置', blank=True)
    
    # 处理结果
    result_message = models.TextField(verbose_name='处理结果消息', blank=True)
    error_message = models.TextField(verbose_name='错误信息', blank=True)
    clarification_data = models.JSONField(default=dict, verbose_name='澄清信息', blank=True)
    completion_report = models.JSONField(default=dict, verbose_name='完成报告', blank=True)
    
    # 时间戳
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')
    
    class Meta:
        verbose_name = '地图制作请求'
        verbose_name_plural = '地图制作请求'
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'creation_idempotency_key'],
                name='mapping_request_user_creation_key_uniq',
            )
        ]
    
    def __str__(self):
        return f"{self.user.username} - {self.title or '未命名地图'} ({self.get_status_display()})"
    
    def set_config(self, config_dict):
        """设置地图配置"""
        self.map_config = config_dict
        self.save()
    
    def get_config(self):
        """获取地图配置"""
        return self.map_config

    def save(self, *args, **kwargs):
        """Keep the persisted completion report compatible with its NOT NULL contract."""
        if self.completion_report is None:
            self.completion_report = {}
            if kwargs.get('update_fields') is not None:
                kwargs['update_fields'] = set(kwargs['update_fields']) | {'completion_report'}
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        """删除模型时同时删除会话文件和生成的地图"""
        from django.conf import settings
        import logging

        logger = logging.getLogger(__name__)

        # 删除会话目录（包含所有生成的地图和日志）
        session_dir = Path(settings.GENERATED_MAPS_DIR) / f"user_{self.user.id}" / f"session_{self.id}"

        logger.info(f"开始删除会话: {self.id}, 目录: {session_dir}")

        if session_dir.exists():
            try:
                # 递归删除整个目录
                shutil.rmtree(session_dir)
                logger.info(f"✅ 已删除会话目录: {session_dir}")
                print(f"✅ 已删除会话目录: {session_dir}")
            except Exception as e:
                logger.error(f"❌ 删除会话目录失败: {session_dir}, 错误: {e}")
                print(f"❌ 删除会话目录失败: {session_dir}, 错误: {e}")
        else:
            logger.warning(f"⚠️ 会话目录不存在: {session_dir}")
            print(f"⚠️ 会话目录不存在: {session_dir}")

        # 调用父类的 delete 方法删除数据库记录（包括关联的 GeneratedMap 和 ChatMessage）
        logger.info(f"删除数据库记录: MapRequest {self.id}")
        super().delete(*args, **kwargs)
        logger.info(f"✅ 会话 {self.id} 已完全删除")


class MapRun(models.Model):
    """一次地图生成执行，归属于一个 MapRequest。"""

    STATUS_PENDING = 'pending'
    STATUS_RUNNING = 'running'
    STATUS_AWAITING_INPUT = 'awaiting_input'
    STATUS_COMPLETED = 'completed'
    STATUS_PARTIAL = 'partial'
    STATUS_FAILED = 'failed'
    STATUS_CANCEL_REQUESTED = 'cancel_requested'
    STATUS_CANCELLED = 'cancelled'

    STATUS_CHOICES = [
        (STATUS_PENDING, '等待处理'),
        (STATUS_RUNNING, '处理中'),
        (STATUS_AWAITING_INPUT, '等待补充信息'),
        (STATUS_COMPLETED, '已完成'),
        (STATUS_PARTIAL, '部分完成'),
        (STATUS_FAILED, '失败'),
        (STATUS_CANCEL_REQUESTED, '取消中'),
        (STATUS_CANCELLED, '已取消'),
    ]

    _TRANSITIONS = {
        STATUS_PENDING: {STATUS_RUNNING, STATUS_FAILED, STATUS_CANCEL_REQUESTED},
        STATUS_RUNNING: {
            STATUS_AWAITING_INPUT,
            STATUS_COMPLETED,
            STATUS_PARTIAL,
            STATUS_FAILED,
            STATUS_CANCEL_REQUESTED,
        },
        STATUS_AWAITING_INPUT: set(),
        STATUS_CANCEL_REQUESTED: {STATUS_CANCELLED, STATUS_FAILED},
        STATUS_COMPLETED: set(),
        STATUS_PARTIAL: set(),
        STATUS_FAILED: set(),
        STATUS_CANCELLED: set(),
    }

    request = models.ForeignKey(
        MapRequest,
        on_delete=models.CASCADE,
        related_name='runs',
        verbose_name='关联请求',
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
        verbose_name='运行状态',
    )
    idempotency_key = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        verbose_name='幂等键',
    )
    trace_id = models.CharField(
        max_length=255,
        blank=True,
        verbose_name='智能体调用链标识',
    )
    map_version = models.PositiveIntegerField(null=True, blank=True, verbose_name='地图版本')
    attempt = models.PositiveIntegerField(default=1, verbose_name='尝试次数')
    heartbeat_at = models.DateTimeField(null=True, blank=True, verbose_name='心跳时间')
    started_at = models.DateTimeField(null=True, blank=True, verbose_name='开始时间')
    finished_at = models.DateTimeField(null=True, blank=True, verbose_name='结束时间')
    error_code = models.CharField(max_length=100, blank=True, verbose_name='错误代码')
    error_message = models.TextField(blank=True, verbose_name='错误信息')
    completion_report = models.JSONField(default=dict, blank=True, verbose_name='完成报告')
    source_plan = models.JSONField(default=dict, blank=True, verbose_name='来源计划诊断')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        verbose_name = '地图运行'
        verbose_name_plural = '地图运行'
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['request', 'idempotency_key'],
                name='mapping_run_request_idempotency_key_uniq',
            )
        ]

    def __str__(self):
        return f'Run {self.pk} for request {self.request_id} ({self.status})'

    def transition_to(self, status, *, error_code=None, error_message=None, completion_report=None):
        """执行受约束的状态变更，并记录运行时间。"""
        if self.pk is None:
            raise ValueError('MapRun must be saved before changing status')
        if status not in dict(self.STATUS_CHOICES):
            raise ValidationError({'status': f'未知的运行状态: {status}'})
        if status not in self._TRANSITIONS[self.status]:
            raise ValidationError(
                {'status': f'不允许从 {self.status} 变更为 {status}'}
            )

        now = timezone.now()
        self.status = status
        update_fields = {'status', 'updated_at'}
        if status == self.STATUS_RUNNING:
            self.started_at = self.started_at or now
            self.heartbeat_at = now
            update_fields.update({'started_at', 'heartbeat_at'})
        elif status in {
            self.STATUS_COMPLETED,
            self.STATUS_PARTIAL,
            self.STATUS_AWAITING_INPUT,
            self.STATUS_FAILED,
            self.STATUS_CANCELLED,
        }:
            self.finished_at = now
            self.heartbeat_at = now
            update_fields.update({'finished_at', 'heartbeat_at'})
        if error_code is not None:
            self.error_code = error_code
            update_fields.add('error_code')
        if error_message is not None:
            self.error_message = error_message
            update_fields.add('error_message')
        if completion_report is not None:
            self.completion_report = completion_report
            update_fields.add('completion_report')
        self.save(update_fields=update_fields)


class Dataset(models.Model):
    """A discoverable local or remote geospatial dataset."""

    SOURCE_LOCAL = "local"
    SOURCE_REMOTE = "remote"
    SOURCE_UPLOAD = "upload"
    SOURCE_CHOICES = [
        (SOURCE_LOCAL, "本地数据"),
        (SOURCE_REMOTE, "远程数据"),
        (SOURCE_UPLOAD, "用户上传"),
    ]

    STATUS_AVAILABLE = "available"
    STATUS_PENDING = "pending"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_AVAILABLE, "可用"),
        (STATUS_PENDING, "处理中"),
        (STATUS_FAILED, "失败"),
    ]

    dataset_id = models.CharField(max_length=200, unique=True, verbose_name="数据集ID")
    name = models.CharField(max_length=255, verbose_name="数据集名称")
    aliases = models.JSONField(default=list, blank=True, verbose_name="名称别名")
    source_type = models.CharField(
        max_length=20, choices=SOURCE_CHOICES, default=SOURCE_LOCAL, verbose_name="数据来源类型"
    )
    source_url = models.URLField(blank=True, verbose_name="数据来源地址")
    local_path = models.CharField(max_length=500, blank=True, verbose_name="本地相对路径")
    geometry_type = models.CharField(max_length=40, blank=True, verbose_name="几何类型")
    crs = models.CharField(max_length=100, blank=True, verbose_name="坐标系")
    bbox = models.JSONField(default=list, blank=True, verbose_name="空间范围")
    feature_count = models.PositiveBigIntegerField(null=True, blank=True, verbose_name="要素数量")
    license = models.CharField(max_length=255, blank=True, verbose_name="许可证")
    checksum = models.CharField(max_length=128, blank=True, verbose_name="校验哈希")
    version = models.CharField(max_length=100, default="1", verbose_name="数据版本")
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_AVAILABLE, verbose_name="状态"
    )
    metadata = models.JSONField(default=dict, blank=True, verbose_name="数据元信息")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "数据集"
        verbose_name_plural = "数据集"
        ordering = ["name", "dataset_id"]
        indexes = [
            models.Index(fields=["source_type", "status"]),
            models.Index(fields=["name"]),
        ]

    def __str__(self):
        return f"{self.name} ({self.dataset_id})"


class DatasetFeature(models.Model):
    """Normalized feature storage used by PostGIS spatial queries."""

    dataset = models.ForeignKey(
        Dataset,
        on_delete=models.CASCADE,
        related_name="features",
        verbose_name="所属数据集",
    )
    source_fid = models.CharField(max_length=255, verbose_name="源要素ID")
    geom = gis_models.GeometryField(srid=4326, spatial_index=True, verbose_name="几何")
    properties = models.JSONField(default=dict, blank=True, verbose_name="属性")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "数据集要素"
        verbose_name_plural = "数据集要素"
        constraints = [
            models.UniqueConstraint(
                fields=["dataset", "source_fid"],
                name="mapping_dataset_feature_source_uniq",
            )
        ]

    def __str__(self):
        return f"{self.dataset_id}:{self.source_fid}"


class GeneratedMap(models.Model):
    """生成的地图文件模型"""

    request = models.ForeignKey(MapRequest, on_delete=models.CASCADE, related_name='generated_maps', verbose_name='关联请求', blank=True, null=True)
    filename = models.CharField(max_length=255, verbose_name='文件名')
    file_path = models.CharField(max_length=500, verbose_name='文件路径')
    file_size = models.PositiveIntegerField(verbose_name='文件大小(字节)', null=True, blank=True)

    # 新增：版本号和会话ID
    version = models.PositiveIntegerField(default=1, verbose_name='版本号')
    session_id = models.CharField(max_length=100, verbose_name='会话ID', blank=True)

    # 新增：支持将图片数据直接存储在数据库中（可选）
    image_data = models.BinaryField(verbose_name='图片数据', blank=True, null=True)

    # 地图元数据
    map_extent = models.JSONField(default=list, verbose_name='地图范围', blank=True)
    layers_info = models.JSONField(default=list, verbose_name='图层信息', blank=True)

    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')

    class Meta:
        verbose_name = '生成的地图'
        verbose_name_plural = '生成的地图'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.filename} - {self.request.title or '未命名地图'} (v{self.version})"

    def delete(self, *args, **kwargs):
        """删除模型时同时删除文件"""
        import os
        from django.conf import settings

        # 如果有文件路径，尝试删除文件
        if self.file_path:
            full_path = os.path.join(settings.GENERATED_MAPS_DIR, self.file_path)
            if os.path.exists(full_path):
                try:
                    os.remove(full_path)
                    print(f"已删除文件: {full_path}")
                except Exception as e:
                    print(f"删除文件失败: {full_path}, 错误: {e}")

        # 调用父类的 delete 方法删除数据库记录
        super().delete(*args, **kwargs)


class ChatMessage(models.Model):
    """聊天消息模型"""

    MESSAGE_TYPES = [
        ('user', '用户消息'),
        ('assistant', '助手回复'),
        ('system', '系统消息'),
        ('log', '实时日志'),
    ]

    request = models.ForeignKey(MapRequest, on_delete=models.CASCADE, related_name='chat_messages', verbose_name='关联请求')
    client_message_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name='客户端消息ID',
    )
    message_type = models.CharField(max_length=20, choices=MESSAGE_TYPES, verbose_name='消息类型')
    content = models.TextField(verbose_name='消息内容')

    # 额外数据（如地图生成进度、错误信息等）
    extra_data = models.JSONField(default=dict, verbose_name='额外数据', blank=True)

    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')

    class Meta:
        verbose_name = '聊天消息'
        verbose_name_plural = '聊天消息'
        ordering = ['created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['request', 'client_message_id'],
                name='mapping_message_request_client_id_uniq',
            )
        ]

    def __str__(self):
        return f"{self.get_message_type_display()}: {self.content[:50]}..."


class ProcessLog(models.Model):
    """处理过程日志模型"""

    LOG_LEVELS = [
        ('info', '信息'),
        ('warning', '警告'),
        ('error', '错误'),
        ('debug', '调试'),
    ]

    request = models.ForeignKey(MapRequest, on_delete=models.CASCADE, related_name='process_logs', verbose_name='关联请求')
    run = models.ForeignKey(
        MapRun,
        on_delete=models.SET_NULL,
        related_name='process_logs',
        null=True,
        blank=True,
        verbose_name='关联运行',
    )
    level = models.CharField(max_length=20, choices=LOG_LEVELS, default='info', verbose_name='日志级别')
    message = models.TextField(verbose_name='日志消息')
    step = models.CharField(max_length=100, verbose_name='处理步骤', blank=True)
    progress = models.PositiveIntegerField(verbose_name='进度百分比', null=True, blank=True)

    # Structured trace fields. The legacy message/step fields remain the
    # compatibility projection used by the existing log endpoint.
    event_id = models.CharField(max_length=80, unique=True, default=_new_trace_event_id)
    event_seq = models.PositiveIntegerField(default=0, verbose_name='Trace序号')
    trace_id = models.CharField(max_length=255, blank=True, verbose_name='Trace ID')
    parent_event_id = models.CharField(max_length=80, blank=True, verbose_name='父事件ID')
    event_type = models.CharField(max_length=40, default='process_log', verbose_name='事件类型')
    phase = models.CharField(max_length=60, blank=True, verbose_name='业务阶段')
    actor = models.CharField(max_length=40, default='system', verbose_name='执行者')
    status = models.CharField(max_length=30, default='success', verbose_name='事件状态')
    started_at = models.DateTimeField(null=True, blank=True, verbose_name='开始时间')
    finished_at = models.DateTimeField(null=True, blank=True, verbose_name='结束时间')
    duration_ms = models.PositiveIntegerField(null=True, blank=True, verbose_name='耗时毫秒')
    input_data = models.JSONField(default=dict, blank=True, verbose_name='结构化输入')
    output_data = models.JSONField(default=dict, blank=True, verbose_name='结构化输出')
    attributes = models.JSONField(default=dict, blank=True, verbose_name='事件属性')
    error = models.JSONField(null=True, blank=True, default=None, verbose_name='结构化错误')

    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')

    class Meta:
        verbose_name = '处理日志'
        verbose_name_plural = '处理日志'
        ordering = ['created_at', 'id']
        indexes = [
            models.Index(fields=['run', 'event_seq']),
            models.Index(fields=['run', 'event_type', 'status']),
        ]

    def __str__(self):
        return f"{self.get_level_display()}: {self.message[:50]}..."
