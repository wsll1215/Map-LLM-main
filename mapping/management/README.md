# 管理命令说明

本目录包含用于管理地图文件的 Django 管理命令。

## 可用命令

### 1. migrate_old_maps - 迁移旧文件

将旧的平铺式存储结构迁移到新的分层存储结构。

**使用方法：**
```bash
# 预览迁移（推荐先执行）
python manage.py migrate_old_maps --dry-run

# 实际执行迁移
python manage.py migrate_old_maps
```

**功能：**
- 自动识别旧格式的文件（file_path 不包含 user_ 前缀）
- 按用户和会话重新组织文件
- 生成版本号和会话ID
- 创建 metadata.json
- 删除旧文件

**注意：**
- 建议先备份文件再执行
- 使用 `--dry-run` 可以先预览迁移计划

### 2. cleanup_old_maps - 清理旧文件

清理指定天数之前的旧地图文件。

**使用方法：**
```bash
# 预览清理（推荐先执行）
python manage.py cleanup_old_maps --days 30 --dry-run

# 实际清理30天前的文件，每个用户保留最近5个会话
python manage.py cleanup_old_maps --days 30 --keep-sessions 5

# 更激进的清理：7天前的文件，只保留最近3个会话
python manage.py cleanup_old_maps --days 7 --keep-sessions 3
```

**参数说明：**
- `--days N`: 清理N天之前的文件（默认30天）
- `--keep-sessions N`: 每个用户至少保留最近N个会话（默认5个）
- `--dry-run`: 仅预览，不实际删除

**功能：**
- 按时间清理旧文件
- 保留每个用户最近N个会话
- 自动删除空目录
- 详细的统计报告

**清理策略：**
1. 获取每个用户的所有会话
2. 按创建时间倒序排列
3. 保留最近N个会话（无论时间）
4. 其余会话如果超过指定天数则删除

## 定时任务设置

### Linux/Mac (crontab)

```bash
# 编辑 crontab
crontab -e

# 添加定时任务：每天凌晨3点清理30天前的文件
0 3 * * * cd /path/to/xy_neo4j_roadqa_v3 && /path/to/python manage.py cleanup_old_maps --days 30
```

### Windows (任务计划程序)

1. 打开"任务计划程序"
2. 创建基本任务
3. 名称：清理旧地图文件
4. 触发器：每天凌晨3:00
5. 操作：启动程序
   - 程序：`C:\path\to\python.exe`
   - 参数：`manage.py cleanup_old_maps --days 30`
   - 起始于：`C:\path\to\xy_neo4j_roadqa_v3`

## 使用示例

### 场景1：首次部署，迁移旧文件

```bash
# 1. 备份现有文件
tar -czf backup_maps_$(date +%Y%m%d).tar.gz static/generated_maps/

# 2. 预览迁移
python manage.py migrate_old_maps --dry-run

# 3. 确认无误后执行迁移
python manage.py migrate_old_maps

# 4. 验证迁移结果
ls -la static/generated_maps/user_*/session_*/
```

### 场景2：定期清理旧文件

```bash
# 1. 先预览将要删除的文件
python manage.py cleanup_old_maps --days 30 --dry-run

# 2. 确认无误后执行清理
python manage.py cleanup_old_maps --days 30 --keep-sessions 5

# 3. 检查磁盘使用情况
du -sh static/generated_maps/
```

### 场景3：紧急清理（磁盘空间不足）

```bash
# 更激进的清理策略
python manage.py cleanup_old_maps --days 7 --keep-sessions 3

# 或者只保留最近2个会话
python manage.py cleanup_old_maps --days 1 --keep-sessions 2
```

## 常见问题

### Q: 迁移命令会删除旧文件吗？

A: 是的。迁移命令会：
1. 复制文件到新位置
2. 更新数据库记录
3. 删除旧文件

建议先备份再执行。

### Q: 清理命令会删除正在使用的文件吗？

A: 不会。清理策略确保：
- 每个用户至少保留最近N个会话
- 只删除超过指定天数的旧会话

### Q: 如何恢复被删除的文件？

A: 如果有备份，可以从备份恢复：
```bash
tar -xzf backup_maps_YYYYMMDD.tar.gz
```

如果没有备份，文件将无法恢复。

### Q: 可以只清理特定用户的文件吗？

A: 当前命令不支持。如需清理特定用户，可以手动删除：
```bash
rm -rf static/generated_maps/user_X/
```

然后在数据库中删除对应记录：
```python
from mapping.models import GeneratedMap, MapRequest
GeneratedMap.objects.filter(request__user_id=X).delete()
```

## 监控和维护

### 检查磁盘使用

```bash
# Linux/Mac
du -sh static/generated_maps/
du -sh static/generated_maps/user_*/

# Windows PowerShell
Get-ChildItem -Path static\generated_maps -Recurse | Measure-Object -Property Length -Sum
```

### 检查文件数量

```bash
# 总文件数
find static/generated_maps -name "*.png" | wc -l

# 每个用户的文件数
for dir in static/generated_maps/user_*; do
    echo "$dir: $(find $dir -name "*.png" | wc -l)"
done
```

### 检查数据库记录

```python
from mapping.models import GeneratedMap, MapRequest
from django.contrib.auth import get_user_model

User = get_user_model()

# 每个用户的地图数量
for user in User.objects.all():
    count = GeneratedMap.objects.filter(request__user=user).count()
    print(f"用户 {user.username}: {count} 个地图")

# 每个会话的地图数量
for request in MapRequest.objects.all():
    count = request.generated_maps.count()
    print(f"会话 {request.id}: {count} 个地图")
```

## 更多信息

详细文档请参考：
- `../STORAGE_GUIDE.md` - 完整的存储方案说明
- `../MIGRATION_STEPS.md` - 迁移步骤指南
- `../CHANGES_SUMMARY.md` - 修改总结

