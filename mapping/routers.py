"""
数据库路由器 - 将特定模型路由到不同的数据库
"""


class MapStatesRouter:
    """
    将 map_states 相关的模型路由到 map_states 数据库
    """
    
    # 需要路由到 map_states 数据库的模型
    map_states_models = {
        'MapStateSession',
        'MapState',
        'MapStateLayer',
        'MapStateLegend',
        'MapStateAnnotation',
        'MapStateModificationRecord',
    }
    
    def db_for_read(self, model, **hints):
        """
        读操作路由
        """
        if model.__name__ in self.map_states_models:
            return 'map_states'
        return None
    
    def db_for_write(self, model, **hints):
        """
        写操作路由
        """
        if model.__name__ in self.map_states_models:
            return 'map_states'
        return None
    
    def allow_relation(self, obj1, obj2, **hints):
        """
        允许关系
        """
        # 不允许跨数据库的关系
        db1 = self.db_for_read(type(obj1))
        db2 = self.db_for_read(type(obj2))
        
        if db1 is not None and db2 is not None:
            return db1 == db2
        return None
    
    def allow_migrate(self, db, app_label, model_name=None, **hints):
        """
        迁移路由 - map_states 模型不需要迁移
        """
        if model_name in [m.lower() for m in self.map_states_models]:
            return db == 'map_states'
        return None

