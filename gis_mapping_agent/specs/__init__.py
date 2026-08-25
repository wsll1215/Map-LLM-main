"""Structured task specs."""

from .adjustment_patch import AdjustmentPatch, PatchOperation
from .generalization_spec import GeneralizationSpec
from .map_spec import LayerManifest, MapLayerSpec, MapSpec, MapSpecStyle

__all__ = [
    "AdjustmentPatch",
    "PatchOperation",
    "GeneralizationSpec",
    "LayerManifest",
    "MapLayerSpec",
    "MapSpec",
    "MapSpecStyle",
]
