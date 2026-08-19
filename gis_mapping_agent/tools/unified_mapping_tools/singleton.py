"""单例模式实现

提供全局统一工具实例的访问接口
"""

from typing import Optional

# 全局工具实例
_unified_tools_instance: Optional['UnifiedMappingTools'] = None


def get_unified_tools() -> 'UnifiedMappingTools':
    """获取全局统一工具实例（单例模式）
    
    这是一个全局单例，在整个应用程序生命周期中只创建一次。
    所有工具类都应该使用这个实例，而不是创建新的实例。
    
    Returns:
        UnifiedMappingTools: 全局统一工具实例
    """
    global _unified_tools_instance
    if _unified_tools_instance is None:
        # 延迟导入避免循环依赖
        from .core import UnifiedMappingTools
        _unified_tools_instance = UnifiedMappingTools()
    return _unified_tools_instance


def reset_unified_tools():
    """重置全局统一工具实例

    主要用于测试，清除全局状态。
    先调用实例的reset()方法清理资源（如关闭matplotlib图形），
    然后将全局实例设置为None，下次调用get_unified_tools()时会创建新实例。
    """
    global _unified_tools_instance
    if _unified_tools_instance is not None:
        # 先清理实例内部资源（关闭图形等）
        try:
            _unified_tools_instance.reset()
        except Exception as e:
            # 如果reset失败，记录错误但继续重置
            print(f"警告：重置工具实例时出错: {e}")
        # 然后将实例设置为None，让垃圾回收器处理
        _unified_tools_instance = None

