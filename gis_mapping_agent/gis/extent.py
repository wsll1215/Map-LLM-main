"""Compatibility entrypoint for extent calculation."""

from ..utils.extent_calculator import calculate_extent_from_files, format_extent_for_request

__all__ = ["calculate_extent_from_files", "format_extent_for_request"]
