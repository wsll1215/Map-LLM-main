"""Dataset discovery and acquisition integrations."""

from .catalog import DatasetDescriptor, LocalDatasetCatalog
from .planner import SemanticLayerPlan, plan_local_sources
from .remote import (
    extract_location_query,
    fetch_remote_boundary,
    fetch_remote_waterways,
    geocode_place,
    normalize_point_to_extent,
)

__all__ = [
    "DatasetDescriptor",
    "LocalDatasetCatalog",
    "SemanticLayerPlan",
    "plan_local_sources",
    "extract_location_query",
    "fetch_remote_boundary",
    "fetch_remote_waterways",
    "geocode_place",
    "normalize_point_to_extent",
]
