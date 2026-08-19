"""LangChain tool registry."""

from .adjustment_tools import (
    ClearAnnotationsTool,
    RemoveLayerTool,
    ToggleLayerVisibilityTool,
    UpdateMapTitleTool,
)
from .element_tools import (
    AddCompassTool,
    AddScalebarTool,
    RemoveCompassTool,
    RemoveScalebarTool,
)
from .generalization_tools import (
    GeneralizeRoadNetworkTool,
    ModifyGeneralizationParamsTool,
    VisualizeGeneralizationTool,
)
from .mapping_tools import (
    AddAnnotationTool,
    AddLayerTool,
    InitMapTool,
    MapSaveTool,
    StyleLayerTool,
)


ALL_UNIFIED_TOOLS = [
    InitMapTool(),
    AddLayerTool(),
    StyleLayerTool(),
    AddScalebarTool(),
    AddCompassTool(),
    AddAnnotationTool(),
    MapSaveTool(),
    RemoveLayerTool(),
    RemoveScalebarTool(),
    RemoveCompassTool(),
    UpdateMapTitleTool(),
    ToggleLayerVisibilityTool(),
    ClearAnnotationsTool(),
    GeneralizeRoadNetworkTool(),
    VisualizeGeneralizationTool(),
    ModifyGeneralizationParamsTool(),
]


__all__ = ["ALL_UNIFIED_TOOLS"]
