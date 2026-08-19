from django.contrib import admin
from .models import MapRequest, GeneratedMap, ChatMessage, ProcessLog

# 导入增强版的 Admin 配置（已在 admin_enhanced.py 中注册，无需重复注册）
from . import admin_enhanced

# 导入数据库管理模块（已在 db_admin.py 中注册）
from . import db_admin

# 注意：ChatMessage、ProcessLog 和 GeneratedMap 已在 admin_enhanced.py 中注册
# 这里不再注册它们，以保持首页快捷操作的简洁性
