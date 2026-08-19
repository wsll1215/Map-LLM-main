"""Unified GIS mapping tools public class."""

from .adjustments import AdjustmentOperationsMixin
from .base import UnifiedMappingToolsBase
from .constants import COLOR_PALETTE, LAYER_NAME_MAPPING
from .elements import ElementOperationsMixin
from .map_ops import MapOperationsMixin
from .rendering import RenderingMixin


class UnifiedMappingTools(
    UnifiedMappingToolsBase,
    MapOperationsMixin,
    RenderingMixin,
    ElementOperationsMixin,
    AdjustmentOperationsMixin,
):
    """Unified mapping API kept stable for existing agents and tools."""

    COLOR_PALETTE = COLOR_PALETTE
    LAYER_NAME_MAPPING = LAYER_NAME_MAPPING
