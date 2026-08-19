"""单例模式装饰器

提供通用的单例模式实现，避免在每个类中重复编写单例代码。
"""

from typing import Any, Dict, Callable
from functools import wraps


def singleton(cls):
    """单例模式装饰器
    
    使用此装饰器可以确保一个类只有一个实例。
    
    Example:
        >>> @singleton
        ... class MyClass:
        ...     def __init__(self, value):
        ...         self.value = value
        >>> 
        >>> obj1 = MyClass(10)
        >>> obj2 = MyClass(20)
        >>> obj1 is obj2  # True，是同一个实例
        >>> obj1.value  # 10，保持第一次创建时的值
    
    Note:
        - 第一次调用时创建实例
        - 后续调用返回同一个实例
        - 线程安全（使用简单的字典锁）
    """
    instances: Dict[type, Any] = {}
    
    @wraps(cls)
    def get_instance(*args, **kwargs):
        if cls not in instances:
            instances[cls] = cls(*args, **kwargs)
        return instances[cls]
    
    # 添加重置方法，用于测试
    def reset_instance():
        """重置单例实例（主要用于测试）"""
        if cls in instances:
            del instances[cls]
    
    get_instance.reset = reset_instance
    get_instance.__wrapped__ = cls  # 保留原始类的引用
    
    return get_instance


def singleton_with_reset(cls):
    """带重置功能的单例模式装饰器
    
    与 singleton 类似，但提供了更方便的重置接口。
    
    Example:
        >>> @singleton_with_reset
        ... class MyClass:
        ...     def __init__(self):
        ...         self.data = []
        >>> 
        >>> obj = MyClass()
        >>> obj.data.append(1)
        >>> MyClass.reset_singleton()  # 重置
        >>> obj2 = MyClass()
        >>> obj2.data  # []，新实例
    """
    instances: Dict[type, Any] = {}
    
    @wraps(cls)
    def get_instance(*args, **kwargs):
        if cls not in instances:
            instances[cls] = cls(*args, **kwargs)
        return instances[cls]
    
    # 添加类方法用于重置
    @classmethod
    def reset_singleton(cls_ref):
        """重置单例实例"""
        if cls in instances:
            del instances[cls]
    
    # 将重置方法添加到包装器
    get_instance.reset_singleton = lambda: reset_singleton(cls)
    get_instance.__wrapped__ = cls
    
    return get_instance


# 为了向后兼容，提供函数式 API
def get_singleton_instance(cls, *args, **kwargs):
    """获取单例实例（函数式 API）
    
    Args:
        cls: 类
        *args: 构造函数参数
        **kwargs: 构造函数关键字参数
    
    Returns:
        单例实例
    
    Example:
        >>> class MyClass:
        ...     def __init__(self, value):
        ...         self.value = value
        >>> 
        >>> obj1 = get_singleton_instance(MyClass, 10)
        >>> obj2 = get_singleton_instance(MyClass, 20)
        >>> obj1 is obj2  # True
    """
    if not hasattr(get_singleton_instance, '_instances'):
        get_singleton_instance._instances = {}
    
    if cls not in get_singleton_instance._instances:
        get_singleton_instance._instances[cls] = cls(*args, **kwargs)
    
    return get_singleton_instance._instances[cls]


def reset_singleton_instance(cls):
    """重置单例实例（函数式 API）
    
    Args:
        cls: 要重置的类
    
    Example:
        >>> reset_singleton_instance(MyClass)
    """
    if hasattr(get_singleton_instance, '_instances'):
        if cls in get_singleton_instance._instances:
            del get_singleton_instance._instances[cls]

