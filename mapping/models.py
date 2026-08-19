from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone
import json
import os
import shutil
from pathlib import Path

User = get_user_model()


class MapRequest(models.Model):
    """地图制作请求模型"""
    
    STATUS_CHOICES = [
        ('pending', '等待处理'),
        ('processing', '处理中'),
        ('completed', '已完成'),
        ('failed', '失败'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name='用户')
    title = models.CharField(max_length=200, verbose_name='地图标题', blank=True)
    request_text = models.TextField(verbose_name='制图需求描述')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', verbose_name='状态')
    
    # 地图配置参数（JSON格式存储）
    map_config = models.JSONField(default=dict, verbose_name='地图配置', blank=True)
    
    # 处理结果
    result_message = models.TextField(verbose_name='处理结果消息', blank=True)
    error_message = models.TextField(verbose_name='错误信息', blank=True)
    
    # 时间戳
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')
    
    class Meta:
        verbose_name = '地图制作请求'
        verbose_name_plural = '地图制作请求'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.user.username} - {self.title or '未命名地图'} ({self.get_status_display()})"
    
    def set_config(self, config_dict):
        """设置地图配置"""
        self.map_config = config_dict
        self.save()
    
    def get_config(self):
        """获取地图配置"""
        return self.map_config

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
    message_type = models.CharField(max_length=20, choices=MESSAGE_TYPES, verbose_name='消息类型')
    content = models.TextField(verbose_name='消息内容')

    # 额外数据（如地图生成进度、错误信息等）
    extra_data = models.JSONField(default=dict, verbose_name='额外数据', blank=True)

    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')

    class Meta:
        verbose_name = '聊天消息'
        verbose_name_plural = '聊天消息'
        ordering = ['created_at']

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
    level = models.CharField(max_length=20, choices=LOG_LEVELS, default='info', verbose_name='日志级别')
    message = models.TextField(verbose_name='日志消息')
    step = models.CharField(max_length=100, verbose_name='处理步骤', blank=True)
    progress = models.PositiveIntegerField(verbose_name='进度百分比', null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')

    class Meta:
        verbose_name = '处理日志'
        verbose_name_plural = '处理日志'
        ordering = ['created_at']

    def __str__(self):
        return f"{self.get_level_display()}: {self.message[:50]}..."
