"""
GIS数据制图智能体

基于LangChain实现的自然语言驱动的地图制图工作流智能体。
"""

# from .agent import GISMappingAgent
from .agent import ConversationalMappingAgent, ThinkingGISMappingAgent
from .gis import DataLoader, calculate_extent_from_files, data_loader, format_extent_for_request
from .generalization import GeneralizationResult, RoadNetworkGeneralizationEngine
from .models.schemas import MapConfig, LayerConfig, LayerStyle, MapState, SessionInfo, MapVersion
from .rendering import MapQualityChecker
from .state import MapStateManager, get_state_manager

__version__ = "0.2.0"
__author__ = "GIS Mapping Agent Team"

__all__ = [
    "ThinkingGISMappingAgent",
    "ConversationalMappingAgent",
    # "GISMappingAgent",
    "MapConfig",
    "LayerConfig",
    "LayerStyle",
    "MapState",
    "SessionInfo",
    "MapVersion",
    "MapStateManager",
    "get_state_manager",
    "RoadNetworkGeneralizationEngine",
    "GeneralizationResult",
    "MapQualityChecker",
    "DataLoader",
    "data_loader",
    "calculate_extent_from_files",
    "format_extent_for_request",
]
