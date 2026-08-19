"""
清理旧地图文件的管理命令

使用方法：
    python manage.py cleanup_old_maps --days 30  # 清理30天前的文件
    python manage.py cleanup_old_maps --days 30 --dry-run  # 仅预览，不实际删除
"""

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.conf import settings
from pathlib import Path
from datetime import timedelta
import shutil

from mapping.models import MapRequest, GeneratedMap


class Command(BaseCommand):
    help = '清理指定天数之前的旧地图文件'

    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            default=30,
            help='清理多少天之前的文件（默认30天）'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='仅预览，不实际删除文件'
        )
        parser.add_argument(
            '--keep-sessions',
            type=int,
            default=5,
            help='每个用户至少保留最近N个会话（默认5个）'
        )

    def handle(self, *args, **options):
        days = options['days']
        dry_run = options['dry_run']
        keep_sessions = options['keep_sessions']
        
        cutoff_date = timezone.now() - timedelta(days=days)
        
        self.stdout.write(self.style.WARNING(
            f"\n{'='*60}\n"
            f"清理旧地图文件\n"
            f"{'='*60}\n"
            f"清理时间点: {cutoff_date.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"保留策略: 每个用户至少保留最近 {keep_sessions} 个会话\n"
            f"模式: {'预览模式（不会实际删除）' if dry_run else '实际删除模式'}\n"
            f"{'='*60}\n"
        ))
        
        # 统计信息
        total_sessions = 0
        total_files = 0
        total_size = 0
        deleted_sessions = 0
        deleted_files = 0
        deleted_size = 0
        
        # 按用户分组处理
        from django.contrib.auth import get_user_model
        User = get_user_model()
        
        for user in User.objects.all():
            # 获取该用户的所有请求，按创建时间倒序
            user_requests = MapRequest.objects.filter(user=user).order_by('-created_at')
            
            if user_requests.count() == 0:
                continue
            
            self.stdout.write(f"\n处理用户: {user.username} (ID: {user.id})")
            self.stdout.write(f"  总会话数: {user_requests.count()}")
            
            # 保留最近的N个会话，其余的如果超过时间则删除
            for idx, request in enumerate(user_requests):
                total_sessions += 1
                session_maps = request.generated_maps.all()
                
                if session_maps.count() == 0:
                    continue
                
                # 计算会话大小
                session_size = sum(m.file_size or 0 for m in session_maps)
                total_files += session_maps.count()
                total_size += session_size
                
                # 判断是否应该删除
                should_delete = False
                if idx >= keep_sessions:  # 不在保留范围内
                    if request.created_at < cutoff_date:  # 且超过时间
                        should_delete = True
                
                if should_delete:
                    deleted_sessions += 1
                    deleted_files += session_maps.count()
                    deleted_size += session_size
                    
                    self.stdout.write(
                        self.style.WARNING(
                            f"  [删除] 会话 {request.id} "
                            f"({request.created_at.strftime('%Y-%m-%d')}, "
                            f"{session_maps.count()} 个文件, "
                            f"{session_size / 1024 / 1024:.2f} MB)"
                        )
                    )
                    
                    if not dry_run:
                        # 删除文件
                        for map_obj in session_maps:
                            file_path = Path(settings.GENERATED_MAPS_DIR) / map_obj.file_path
                            if file_path.exists():
                                file_path.unlink()

                        # 删除会话目录
                        session_dir = Path(settings.GENERATED_MAPS_DIR) / f"user_{user.id}" / f"session_{request.id}"
                        if session_dir.exists():
                            shutil.rmtree(session_dir)

                        # 删除数据库记录
                        session_maps.delete()
                else:
                    self.stdout.write(
                        f"  [保留] 会话 {request.id} "
                        f"({request.created_at.strftime('%Y-%m-%d')}, "
                        f"{session_maps.count()} 个文件, "
                        f"{session_size / 1024 / 1024:.2f} MB)"
                    )
        
        # 清理空的用户目录
        if not dry_run:
            base_dir = Path(settings.GENERATED_MAPS_DIR)
            if base_dir.exists():
                for user_dir in base_dir.iterdir():
                    if user_dir.is_dir() and not any(user_dir.iterdir()):
                        user_dir.rmdir()
                        self.stdout.write(f"删除空目录: {user_dir}")
        
        # 输出统计信息
        self.stdout.write(
            self.style.SUCCESS(
                f"\n{'='*60}\n"
                f"清理完成\n"
                f"{'='*60}\n"
                f"总会话数: {total_sessions}\n"
                f"总文件数: {total_files}\n"
                f"总大小: {total_size / 1024 / 1024:.2f} MB\n"
                f"\n"
                f"{'将要' if dry_run else '已'}删除会话数: {deleted_sessions}\n"
                f"{'将要' if dry_run else '已'}删除文件数: {deleted_files}\n"
                f"{'将要' if dry_run else '已'}释放空间: {deleted_size / 1024 / 1024:.2f} MB\n"
                f"\n"
                f"保留会话数: {total_sessions - deleted_sessions}\n"
                f"保留文件数: {total_files - deleted_files}\n"
                f"保留空间: {(total_size - deleted_size) / 1024 / 1024:.2f} MB\n"
                f"{'='*60}\n"
            )
        )
        
        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    "\n这是预览模式，没有实际删除任何文件。\n"
                    "要实际执行删除，请去掉 --dry-run 参数。\n"
                )
            )

