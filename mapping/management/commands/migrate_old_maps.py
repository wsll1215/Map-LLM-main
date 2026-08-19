"""
迁移旧的地图文件到新的分层存储结构

使用方法：
    python manage.py migrate_old_maps --dry-run  # 预览迁移
    python manage.py migrate_old_maps  # 实际执行迁移
"""

from django.core.management.base import BaseCommand
from django.conf import settings
from django.db import models
from pathlib import Path
import shutil
import json
from django.utils import timezone

from mapping.models import GeneratedMap


class Command(BaseCommand):
    help = '将旧的地图文件迁移到新的分层存储结构'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='仅预览，不实际迁移文件'
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        
        self.stdout.write(self.style.WARNING(
            f"\n{'='*60}\n"
            f"迁移旧地图文件到新存储结构\n"
            f"{'='*60}\n"
            f"模式: {'预览模式（不会实际迁移）' if dry_run else '实际迁移模式'}\n"
            f"{'='*60}\n"
        ))
        
        # 统计信息
        total_maps = 0
        migrated_maps = 0
        skipped_maps = 0
        failed_maps = 0
        
        # 获取所有需要迁移的地图（旧格式：包含 'generated_maps/' 或 static 路径的）
        # 新格式只包含：user_X/session_Y/filename
        old_maps = GeneratedMap.objects.filter(
            models.Q(file_path__contains='generated_maps/') |
            models.Q(file_path__contains='static/')
        )

        self.stdout.write(f"找到 {old_maps.count()} 个需要迁移的地图文件\n")

        # 按请求分组处理
        from collections import defaultdict
        maps_by_request = defaultdict(list)

        for map_obj in old_maps:
            maps_by_request[map_obj.request_id].append(map_obj)

        for request_id, maps in maps_by_request.items():
            total_maps += len(maps)

            # 获取请求对象
            if not maps:
                continue

            request = maps[0].request
            user_id = request.user.id
            session_id = f"session_{request_id}"

            self.stdout.write(f"\n处理会话 {request_id} (用户 {user_id}, {len(maps)} 个文件)")

            # 创建新目录结构
            base_dir = Path(settings.GENERATED_MAPS_DIR)
            user_dir = f"user_{user_id}"
            new_session_dir = base_dir / user_dir / session_id
            
            if not dry_run:
                new_session_dir.mkdir(parents=True, exist_ok=True)
            
            # 迁移每个地图文件
            for idx, map_obj in enumerate(sorted(maps, key=lambda m: m.created_at), start=1):
                try:
                    # 构建旧文件路径（尝试多种可能的路径）
                    old_file_path = None
                    possible_paths = [
                        Path(settings.BASE_DIR) / 'static' / map_obj.file_path,
                        Path(settings.BASE_DIR) / map_obj.file_path,
                        Path(map_obj.file_path),
                    ]

                    for path in possible_paths:
                        if path.exists():
                            old_file_path = path
                            break

                    if not old_file_path:
                        self.stdout.write(
                            self.style.WARNING(f"  [跳过] v{idx} - 文件不存在: {map_obj.file_path}")
                        )
                        skipped_maps += 1
                        continue
                    
                    # 生成新文件名
                    file_extension = old_file_path.suffix
                    # 从旧文件名中提取原始名称（去掉UUID前缀）
                    old_filename = old_file_path.stem
                    if '_' in old_filename:
                        # 去掉UUID前缀
                        parts = old_filename.split('_', 1)
                        if len(parts) > 1:
                            base_name = parts[1]
                        else:
                            base_name = old_filename
                    else:
                        base_name = old_filename
                    
                    new_filename = f"v{idx}_{base_name}{file_extension}"
                    new_file_path = new_session_dir / new_filename
                    new_relative_path = f"{user_dir}/{session_id}/{new_filename}"
                    
                    self.stdout.write(
                        f"  [迁移] v{idx}: {map_obj.filename} -> {new_filename}"
                    )
                    
                    if not dry_run:
                        # 复制文件到新位置
                        shutil.copy2(old_file_path, new_file_path)
                        
                        # 更新数据库记录
                        map_obj.filename = new_filename
                        map_obj.file_path = new_relative_path
                        map_obj.version = idx
                        map_obj.session_id = session_id
                        map_obj.save()
                        
                        # 删除旧文件
                        old_file_path.unlink()
                    
                    migrated_maps += 1
                    
                except Exception as e:
                    self.stdout.write(
                        self.style.ERROR(f"  [失败] v{idx}: {e}")
                    )
                    failed_maps += 1
            
            # 创建 metadata.json
            if not dry_run:
                self._create_metadata(request, new_session_dir, maps)
        
        # 清理空的旧目录
        if not dry_run:
            old_static_dir = Path(settings.BASE_DIR) / 'static' / 'generated_maps'
            if old_static_dir.exists():
                self.stdout.write(f"\n清理旧的 static/generated_maps 目录...")
                try:
                    shutil.rmtree(old_static_dir)
                    self.stdout.write(self.style.SUCCESS(f"✅ 已删除旧目录: {old_static_dir}"))
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f"❌ 删除旧目录失败: {e}"))
        
        # 输出统计信息
        self.stdout.write(
            self.style.SUCCESS(
                f"\n{'='*60}\n"
                f"迁移完成\n"
                f"{'='*60}\n"
                f"总文件数: {total_maps}\n"
                f"{'将要' if dry_run else '已'}迁移: {migrated_maps}\n"
                f"跳过: {skipped_maps}\n"
                f"失败: {failed_maps}\n"
                f"{'='*60}\n"
            )
        )
        
        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    "\n这是预览模式，没有实际迁移任何文件。\n"
                    "要实际执行迁移，请去掉 --dry-run 参数。\n"
                )
            )
    
    def _create_metadata(self, request, session_dir, maps):
        """创建 metadata.json"""
        try:
            import hashlib
            
            metadata = {
                "request_id": request.id,
                "user_id": request.user.id,
                "session_id": f"session_{request.id}",
                "created_at": request.created_at.isoformat(),
                "updated_at": timezone.now().isoformat(),
                "request_text": request.request_text[:200],
                "maps": []
            }
            
            for map_obj in sorted(maps, key=lambda m: m.created_at):
                file_path = session_dir / map_obj.filename
                
                # 计算校验和
                checksum = ""
                if file_path.exists():
                    with open(file_path, 'rb') as f:
                        checksum = f"sha256:{hashlib.sha256(f.read()).hexdigest()}"
                
                map_info = {
                    "version": map_obj.version,
                    "filename": map_obj.filename,
                    "size": map_obj.file_size or 0,
                    "checksum": checksum,
                    "created_at": map_obj.created_at.isoformat()
                }
                metadata["maps"].append(map_info)
            
            # 写入文件
            metadata_file = session_dir / 'metadata.json'
            with open(metadata_file, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, ensure_ascii=False, indent=2)
            
            self.stdout.write(f"  ✅ 创建元数据: {metadata_file}")
            
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"  ❌ 创建元数据失败: {e}"))

