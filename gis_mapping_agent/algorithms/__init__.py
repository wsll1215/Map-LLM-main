"""
路网综合算法模块

包含多种路网综合算法：
- Stroke构建算法
- 网眼密度计算
- 层次选取算法
"""

from .stroke_builder import StrokeBuilder
from .mesh_density import MeshDensityCalculator
from .hierarchy_selector import HierarchySelector


def __getattr__(name):
    if name == "RoadNetworkGeneralizationEngine":
        from ..generalization import RoadNetworkGeneralizationEngine
        return RoadNetworkGeneralizationEngine
    if name == "GeneralizationResult":
        from ..generalization import GeneralizationResult
        return GeneralizationResult
    raise AttributeError(name)

__all__ = [
    'StrokeBuilder',
    'MeshDensityCalculator',
    'HierarchySelector',
    'RoadNetworkGeneralizationEngine',
    'GeneralizationResult',
]
