"""Dataset discovery and acquisition integrations."""

from .catalog import DatasetDescriptor, LocalDatasetCatalog
from .remote import extract_location_query, fetch_remote_boundary, geocode_place, normalize_point_to_extent

__all__ = [
    "DatasetDescriptor",
    "LocalDatasetCatalog",
    "extract_location_query",
    "fetch_remote_boundary",
    "geocode_place",
    "normalize_point_to_extent",
]
