"""Structured task specs."""

from .adjustment_patch import AdjustmentPatch, PatchOperation
from .generalization_spec import GeneralizationSpec
from .map_spec import MapSpec

__all__ = ["AdjustmentPatch", "PatchOperation", "GeneralizationSpec", "MapSpec"]
