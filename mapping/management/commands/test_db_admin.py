"""
测试数据库管理功能的 Django 管理命令
"""
from django.core.management.base import BaseCommand
from mapping.db_models import MainDatabase, MapStatesDatabase


class Command(BaseCommand):
    help = '测试数据库管理功能'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('=' * 60))
        self.stdout.write(self.style.SUCCESS('测试 Django 主数据库'))
        self.stdout.write(self.style.SUCCESS('=' * 60))
        
        # 测试主数据库
        stats = MainDatabase.get_db_stats()
        
        if stats:
            self.stdout.write(f"\n📁 数据库路径: {stats['path']}")
            self.stdout.write(f"💾 文件大小: {stats['size'] / 1024:.2f} KB")
            self.stdout.write(f"📅 创建时间: {stats['created_at']}")
            self.stdout.write(f"🔄 最后修改: {stats['modified_at']}")
            self.stdout.write(f"\n📋 表列表 (共 {len(stats['tables'])} 个表):")
            self.stdout.write('-' * 60)
            
            for table in stats['tables']:
                self.stdout.write(f"\n表名: {table['name']}")
                self.stdout.write(f"中文名: {table['chinese_name']}")
                self.stdout.write(f"记录数: {table['count']}")
                self.stdout.write(f"列数: {len(table['columns'])}")
                
                if table['columns']:
                    self.stdout.write("列信息:")
                    for col in table['columns'][:5]:
                        self.stdout.write(f"  - {col['name']} ({col['type']})")
                    if len(table['columns']) > 5:
                        self.stdout.write(f"  ... 还有 {len(table['columns']) - 5} 列")
        else:
            self.stdout.write(self.style.ERROR("❌ 数据库不存在或无法访问"))
        
        # 测试地图状态数据库
        self.stdout.write('\n\n' + '=' * 60)
        self.stdout.write(self.style.SUCCESS('测试地图状态数据库'))
        self.stdout.write(self.style.SUCCESS('=' * 60))
        
        stats = MapStatesDatabase.get_db_stats()
        
        if stats:
            self.stdout.write(f"\n📁 数据库路径: {stats['path']}")
            self.stdout.write(f"💾 文件大小: {stats['size'] / 1024:.2f} KB")
            self.stdout.write(f"📅 创建时间: {stats['created_at']}")
            self.stdout.write(f"🔄 最后修改: {stats['modified_at']}")
            self.stdout.write(f"\n📋 表列表 (共 {len(stats['tables'])} 个表):")
            self.stdout.write('-' * 60)
            
            for table in stats['tables']:
                self.stdout.write(f"\n表名: {table['name']}")
                self.stdout.write(f"中文名: {table['chinese_name']}")
                self.stdout.write(f"记录数: {table['count']}")
                self.stdout.write(f"列数: {len(table['columns'])}")
                
                if table['columns']:
                    self.stdout.write("列信息:")
                    for col in table['columns']:
                        self.stdout.write(f"  - {col['name']} ({col['type']})")
        else:
            self.stdout.write(self.style.ERROR("❌ 数据库不存在或无法访问"))
        
        self.stdout.write('\n\n' + self.style.SUCCESS('✅ 测试完成!'))

