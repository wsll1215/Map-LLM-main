"""
数据库管理模型
用于在 Django Admin 中管理两个数据库：
1. db.sqlite3 - Django 主数据库
2. map_states.db - 地图状态数据库
"""
import sqlite3
import os
from pathlib import Path
from datetime import datetime
from django.db import models
from django.conf import settings

MAP_STATES_DB = settings.BASE_DIR / 'outputs' / 'states' / 'map_states.db'


class MainDatabase(models.Model):
    """Django 主数据库模型（虚拟模型，用于 Admin 显示）"""

    name = models.CharField(max_length=255, verbose_name='数据库名称', default='Django 主数据库')
    db_type = models.CharField(max_length=50, default='main', editable=False)

    class Meta:
        verbose_name = 'Django主数据库'
        verbose_name_plural = 'Django主数据库'
        managed = False  # 不由 Django 管理
        app_label = 'mapping'
        db_table = 'mapping_maindatabase'  # 虚拟表名

    def __str__(self):
        return 'Django 主数据库 (db.sqlite3)'

    @staticmethod
    def get_table_name_mapping():
        """获取表名的中文映射"""
        return {
            'auth_user': '用户表',
            'auth_group': '用户组表',
            'auth_permission': '权限表',
            'auth_group_permissions': '用户组权限表',
            'auth_user_groups': '用户组关联表',
            'auth_user_user_permissions': '用户权限关联表',
            'django_session': '会话表',
            'django_admin_log': '管理日志表',
            'django_content_type': '内容类型表',
            'django_migrations': '数据库迁移表',
            'sqlite_sequence': 'SQLite序列表',
            'accounts_userprofile': '用户配置表',
            'mapping_maprequest': '地图请求表',
            'mapping_generatedmap': '生成地图表',
            'mapping_chatmessage': '聊天消息表',
            'mapping_processlog': '处理日志表',
        }

    @staticmethod
    def get_hidden_tables():
        """获取需要隐藏的系统表列表"""
        return [
            'django_migrations',                    # Django迁移表
            'sqlite_sequence',                      # SQLite序列表
            'django_content_type',                  # Django内容类型表
            'accounts_userprofile_groups',          # 用户组关系表
            'accounts_userprofile_user_permissions', # 用户权限关系表
            'auth_group_permissions',               # 用户组权限表
            'auth_permission',                      # 权限表
            'auth_group',                           # 用户组表
        ]

    @staticmethod
    def get_hidden_columns():
        """获取需要隐藏的字段列表（按表名分组）"""
        return {
            'accounts_userprofile': ['id', 'password', 'first_name', 'last_name'],
        }

    @staticmethod
    def get_column_name_mapping():
        """获取字段名的中文映射"""
        return {
            # 用户配置表
            'accounts_userprofile': {
                'username': '用户名',
                'email': '邮箱',
                'is_superuser': '超级管理员',
                'is_staff': '员工状态',
                'is_active': '激活状态',
                'date_joined': '加入时间',
                'last_login': '最后登录',
                'mpassword': '密码',
            },
            # 管理日志表
            'django_admin_log': {
                'id': 'ID',
                'action_time': '操作时间',
                'object_id': '对象ID',
                'object_repr': '对象描述',
                'change_message': '变更信息',
                'content_type_id': '内容类型ID',
                'user_id': '用户ID',
                'action_flag': '操作标志',
            },
            # Neo4j节点表
            'myneo4j_mynode': {
                'id': 'ID',
                'name': '名称',
                'leixing': '类型',
            },
            # Neo4j问答表
            'myneo4j_mywenda': {
                'id': 'ID',
                'question': '问题',
                'anster': '答案',
                'user_id': '用户ID',
            },
            # 会话表
            'django_session': {
                'session_key': '会话密钥',
                'session_data': '会话数据',
                'expire_date': '过期时间',
            },
            # 地图请求表
            'mapping_maprequest': {
                'id': 'ID',
                'title': '标题',
                'request_text': '请求内容',
                'status': '状态',
                'map_config': '地图配置',
                'result_message': '结果信息',
                'error_message': '错误信息',
                'created_at': '创建时间',
                'updated_at': '更新时间',
                'user_id': '用户ID',
            },
            # 聊天消息表
            'mapping_chatmessage': {
                'id': 'ID',
                'content': '内容',
                'extra_data': '额外数据',
                'created_at': '创建时间',
                'request_id': '请求ID',
                'message_type': '消息类型',
            },
            # 处理日志表
            'mapping_processlog': {
                'id': 'ID',
                'level': '级别',
                'message': '消息',
                'step': '步骤',
                'progress': '进度',
                'created_at': '创建时间',
                'request_id': '请求ID',
            },
            # 生成地图表
            'mapping_generatedmap': {
                'id': 'ID',
                'request_id': '请求ID',
                'filename': '文件名',
                'image_data': '图像数据',
                'file_size': '文件大小',
                'version': '版本',
                'session_id': '会话ID',
                'created_at': '创建时间',
                'file_path': '文件路径',
                'map_extent': '地图范围',
                'layers_info': '图层信息',
            },
        }

    @staticmethod
    def get_db_stats():
        """获取数据库统计信息"""
        db_path = getattr(settings, 'DJANGO_DB_PATH', Path(settings.BASE_DIR) / 'outputs' / 'django.db')
        if not os.path.exists(db_path):
            return None

        stats = {
            'path': db_path,
            'size': os.path.getsize(db_path),
            'created_at': datetime.fromtimestamp(os.path.getctime(db_path)),
            'modified_at': datetime.fromtimestamp(os.path.getmtime(db_path)),
            'tables': []
        }

        table_name_mapping = MainDatabase.get_table_name_mapping()
        hidden_tables = MainDatabase.get_hidden_tables()

        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = cursor.fetchall()

            for table in tables:
                table_name = table[0]

                # 跳过隐藏的系统表
                if table_name in hidden_tables:
                    continue

                cursor.execute(f"SELECT COUNT(*) FROM {table_name};")
                count = cursor.fetchone()[0]

                # 获取表结构信息
                cursor.execute(f"PRAGMA table_info({table_name});")
                columns = cursor.fetchall()

                stats['tables'].append({
                    'name': table_name,
                    'chinese_name': table_name_mapping.get(table_name, table_name),
                    'count': count,
                    'columns': [{'name': col[1], 'type': col[2]} for col in columns]
                })

            conn.close()
        except Exception as e:
            stats['error'] = str(e)

        return stats

    @staticmethod
    def get_table_data(table_name, limit=100, offset=0):
        """获取表数据"""
        db_path = getattr(settings, 'DJANGO_DB_PATH', Path(settings.BASE_DIR) / 'outputs' / 'django.db')
        if not os.path.exists(db_path):
            return None

        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()

            # 获取所有列名和主键信息
            cursor.execute(f"PRAGMA table_info({table_name});")
            all_columns_info = cursor.fetchall()
            all_columns = [col[1] for col in all_columns_info]

            # 找到主键列
            primary_key_column = None
            for col in all_columns_info:
                if col[5] == 1:  # col[5] 是 pk 字段
                    primary_key_column = col[1]
                    break
            if not primary_key_column:
                primary_key_column = all_columns[0] if all_columns else None

            # 获取隐藏字段配置
            hidden_columns_config = MainDatabase.get_hidden_columns()
            hidden_columns = hidden_columns_config.get(table_name, [])

            # 获取字段中文映射
            column_mapping_config = MainDatabase.get_column_name_mapping()
            column_mapping = column_mapping_config.get(table_name, {})

            # 过滤掉隐藏的字段
            visible_columns = [col for col in all_columns if col not in hidden_columns]

            # 构建SELECT语句，确保包含主键（即使主键被隐藏）
            select_columns = list(visible_columns)
            if primary_key_column and primary_key_column not in select_columns:
                select_columns.insert(0, primary_key_column)

            if select_columns:
                columns_str = ', '.join(select_columns)
                cursor.execute(f"SELECT {columns_str} FROM {table_name} LIMIT {limit} OFFSET {offset};")
                rows = cursor.fetchall()

                # 如果主键被隐藏，需要从结果中提取主键值
                if primary_key_column and primary_key_column not in visible_columns:
                    # 主键在第一列，需要单独提取
                    primary_key_values = [row[0] for row in rows]
                    # 从每行中移除主键列
                    rows = [row[1:] for row in rows]
                else:
                    # 主键在可见列中，找到它的索引
                    pk_index = visible_columns.index(primary_key_column) if primary_key_column in visible_columns else 0
                    primary_key_values = [row[pk_index] for row in rows]
            else:
                rows = []
                primary_key_values = []

            # 获取总数
            cursor.execute(f"SELECT COUNT(*) FROM {table_name};")
            total = cursor.fetchone()[0]

            conn.close()

            # 将字段名转换为中文（如果有映射）
            display_columns = [column_mapping.get(col, col) for col in visible_columns]

            return {
                'columns': display_columns,  # 显示中文字段名
                'columns_en': visible_columns,  # 保留英文字段名用于其他操作
                'rows': rows,
                'primary_key_values': primary_key_values,  # 主键值列表
                'primary_key_column': primary_key_column,  # 主键列名
                'total': total,
                'limit': limit,
                'offset': offset
            }
        except Exception as e:
            return {'error': str(e)}

    @staticmethod
    def delete_record(table_name, primary_key_column, primary_key_value):
        """删除表中的记录"""
        db_path = getattr(settings, 'DJANGO_DB_PATH', Path(settings.BASE_DIR) / 'outputs' / 'django.db')
        if not os.path.exists(db_path):
            return {'success': False, 'error': '数据库文件不存在'}

        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()

            # 使用参数化查询防止SQL注入
            query = f"DELETE FROM {table_name} WHERE {primary_key_column} = ?"
            cursor.execute(query, (primary_key_value,))

            conn.commit()
            affected_rows = cursor.rowcount
            conn.close()

            return {
                'success': True,
                'affected_rows': affected_rows,
                'message': f'成功删除 {affected_rows} 条记录'
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @staticmethod
    def get_primary_key(table_name):
        """获取表的主键列名"""
        db_path = getattr(settings, 'DJANGO_DB_PATH', Path(settings.BASE_DIR) / 'outputs' / 'django.db')
        if not os.path.exists(db_path):
            return None

        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()

            # 获取表结构信息
            cursor.execute(f"PRAGMA table_info({table_name});")
            columns = cursor.fetchall()

            conn.close()

            # 查找主键列（pk字段为1表示是主键）
            for col in columns:
                if col[5] == 1:  # col[5] 是 pk 字段
                    return col[1]  # col[1] 是列名

            # 如果没有找到主键，返回第一列
            return columns[0][1] if columns else None
        except Exception as e:
            return None


class MapStatesDatabase(models.Model):
    """地图状态数据库模型（虚拟模型，用于 Admin 显示）"""

    name = models.CharField(max_length=255, verbose_name='数据库名称', default='地图状态数据库')
    db_type = models.CharField(max_length=50, default='map_states', editable=False)

    class Meta:
        verbose_name = '地图状态数据库'
        verbose_name_plural = '地图状态数据库'
        managed = False  # 不由 Django 管理
        app_label = 'mapping'
        db_table = 'mapping_mapstatesdatabase'  # 虚拟表名

    def __str__(self):
        return '地图状态数据库 (map_states.db)'

    @staticmethod
    def get_table_name_mapping():
        """获取表名的中文映射"""
        return {
            'map_states': '地图状态表',
            'layer_states': '图层状态表',
            'style_states': '样式状态表',
            'query_history': '查询历史表',
        }

    @staticmethod
    def get_hidden_tables():
        """获取需要隐藏的系统表列表"""
        return [
            'sqlite_sequence',  # SQLite序列表
        ]

    @staticmethod
    def get_hidden_columns():
        """获取需要隐藏的字段列表（按表名分组）"""
        return {
            # 可以根据需要添加需要隐藏的字段
            # 'table_name': ['column1', 'column2'],
        }

    @staticmethod
    def get_column_name_mapping():
        """获取字段名的中文映射"""
        return {
            # sessions表
            'sessions': {
                'session_id': '会话ID',
                'session_name': '会话名称',
                'created_at': '创建时间',
                'last_accessed': '最后访问时间',
                'current_version': '当前版本',
            },
            # 地图状态表
            'map_states': {
                'id': 'ID',
                'session_id': '会话ID',
                'version': '版本',
                'map_id': '地图ID',
                'title': '标题',
                'extent': '范围',
                'crs': '坐标系',
                'background_color': '背景颜色',
                'figsize': '图形大小',
                'dpi': 'DPI',
                'maintain_data_aspect': '保持数据比例',
                'fit_figsize_to_extent': '适应图形大小',
                'auto_legend': '自动图例',
                'auto_scalebar': '自动比例尺',
                'auto_compass': '自动指北针',
                'scalebar': '比例尺',
                'compass': '指北针',
                'is_generalization_task': '是否泛化任务',
                'generalization_result': '泛化结果',
                'parent_version': '父版本',
                'description': '描述',
                'is_current': '是否当前',
                'created_at': '创建时间',
                'updated_at': '更新时间',
            },
            # 图层表
            'layers': {
                'id': 'ID',
                'state_id': '状态ID',
                'layer_id': '图层ID',
                'name': '名称',
                'data_source': '数据源',
                'geometry_type': '几何类型',
                'style': '样式',
                'label_column': '标签列',
                'label_style': '标签样式',
                'visible': '可见',
                'z_order': 'Z顺序',
                'created_at': '创建时间',
            },
            # 注记表
            'annotations': {
                'id': 'ID',
                'state_id': '状态ID',
                'text': '文本',
                'position': '位置',
                'style': '样式',
                'created_at': '创建时间',
            },
        }

    @staticmethod
    def get_db_stats():
        """获取数据库统计信息"""
        db_path = MAP_STATES_DB
        if not os.path.exists(db_path):
            return None

        stats = {
            'path': db_path,
            'size': os.path.getsize(db_path),
            'created_at': datetime.fromtimestamp(os.path.getctime(db_path)),
            'modified_at': datetime.fromtimestamp(os.path.getmtime(db_path)),
            'tables': []
        }

        table_name_mapping = MapStatesDatabase.get_table_name_mapping()
        hidden_tables = MapStatesDatabase.get_hidden_tables()

        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = cursor.fetchall()

            for table in tables:
                table_name = table[0]

                # 跳过隐藏的系统表
                if table_name in hidden_tables:
                    continue

                cursor.execute(f"SELECT COUNT(*) FROM {table_name};")
                count = cursor.fetchone()[0]

                # 获取表结构信息
                cursor.execute(f"PRAGMA table_info({table_name});")
                columns = cursor.fetchall()

                stats['tables'].append({
                    'name': table_name,
                    'chinese_name': table_name_mapping.get(table_name, table_name),
                    'count': count,
                    'columns': [{'name': col[1], 'type': col[2]} for col in columns]
                })

            conn.close()
        except Exception as e:
            stats['error'] = str(e)

        return stats

    @staticmethod
    def get_table_data(table_name, limit=100, offset=0):
        """获取表数据"""
        db_path = MAP_STATES_DB
        if not os.path.exists(db_path):
            return None

        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()

            # 获取所有列名和主键信息
            cursor.execute(f"PRAGMA table_info({table_name});")
            all_columns_info = cursor.fetchall()
            all_columns = [col[1] for col in all_columns_info]

            # 找到主键列
            primary_key_column = None
            for col in all_columns_info:
                if col[5] == 1:  # col[5] 是 pk 字段
                    primary_key_column = col[1]
                    break
            if not primary_key_column:
                primary_key_column = all_columns[0] if all_columns else None

            # 获取隐藏字段配置
            hidden_columns_config = MapStatesDatabase.get_hidden_columns()
            hidden_columns = hidden_columns_config.get(table_name, [])

            # 获取字段中文映射
            column_mapping_config = MapStatesDatabase.get_column_name_mapping()
            column_mapping = column_mapping_config.get(table_name, {})

            # 过滤掉隐藏的字段
            visible_columns = [col for col in all_columns if col not in hidden_columns]

            # 构建SELECT语句，确保包含主键（即使主键被隐藏）
            select_columns = list(visible_columns)
            if primary_key_column and primary_key_column not in select_columns:
                select_columns.insert(0, primary_key_column)

            if select_columns:
                columns_str = ', '.join(select_columns)
                cursor.execute(f"SELECT {columns_str} FROM {table_name} LIMIT {limit} OFFSET {offset};")
                rows = cursor.fetchall()

                # 如果主键被隐藏，需要从结果中提取主键值
                if primary_key_column and primary_key_column not in visible_columns:
                    # 主键在第一列，需要单独提取
                    primary_key_values = [row[0] for row in rows]
                    # 从每行中移除主键列
                    rows = [row[1:] for row in rows]
                else:
                    # 主键在可见列中，找到它的索引
                    pk_index = visible_columns.index(primary_key_column) if primary_key_column in visible_columns else 0
                    primary_key_values = [row[pk_index] for row in rows]
            else:
                rows = []
                primary_key_values = []

            # 获取总数
            cursor.execute(f"SELECT COUNT(*) FROM {table_name};")
            total = cursor.fetchone()[0]

            conn.close()

            # 将字段名转换为中文（如果有映射）
            display_columns = [column_mapping.get(col, col) for col in visible_columns]

            return {
                'columns': display_columns,  # 显示中文字段名
                'columns_en': visible_columns,  # 保留英文字段名用于其他操作
                'rows': rows,
                'primary_key_values': primary_key_values,  # 主键值列表
                'primary_key_column': primary_key_column,  # 主键列名
                'total': total,
                'limit': limit,
                'offset': offset
            }
        except Exception as e:
            return {'error': str(e)}

    @staticmethod
    def delete_record(table_name, primary_key_column, primary_key_value):
        """删除表中的记录"""
        db_path = MAP_STATES_DB
        if not os.path.exists(db_path):
            return {'success': False, 'error': '数据库文件不存在'}

        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()

            # 使用参数化查询防止SQL注入
            query = f"DELETE FROM {table_name} WHERE {primary_key_column} = ?"
            cursor.execute(query, (primary_key_value,))

            conn.commit()
            affected_rows = cursor.rowcount
            conn.close()

            return {
                'success': True,
                'affected_rows': affected_rows,
                'message': f'成功删除 {affected_rows} 条记录'
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @staticmethod
    def get_primary_key(table_name):
        """获取表的主键列名"""
        db_path = MAP_STATES_DB
        if not os.path.exists(db_path):
            return None

        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()

            # 获取表结构信息
            cursor.execute(f"PRAGMA table_info({table_name});")
            columns = cursor.fetchall()

            conn.close()

            # 查找主键列（pk字段为1表示是主键）
            for col in columns:
                if col[5] == 1:  # col[5] 是 pk 字段
                    return col[1]  # col[1] 是列名

            # 如果没有找到主键，返回第一列
            return columns[0][1] if columns else None
        except Exception as e:
            return None
