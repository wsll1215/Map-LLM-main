"""Stable metadata for local, remote, and uploaded layer sources."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "item"):
        try:
            return _json_safe(value.item())
        except (TypeError, ValueError):
            pass
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return str(value)


def source_metadata(path: Optional[str], *, status: str = "available", error: Optional[str] = None) -> Dict[str, Any]:
    normalized = str(path or "").replace("\\", "/")
    is_remote = "data_cache/" in normalized or "/data_cache/" in normalized
    if is_remote:
        if "remote_boundaries" in normalized:
            provider = "OpenStreetMap/Nominatim"
            source_url = "https://nominatim.openstreetmap.org/search"
        else:
            provider = "OpenStreetMap/Overpass"
            source_url = "https://overpass-api.de/api/interpreter"
        source_type = "remote"
        attribution = "© OpenStreetMap contributors"
    else:
        normalized_lower = normalized.lower()
        source_type = "upload" if normalized_lower.startswith("uploads/") or "/uploads/" in normalized_lower else "local"
        provider = "项目本地数据" if source_type == "local" else "用户上传"
        source_url = None
        attribution = None

    return {
        "source_type": source_type,
        "provider": provider,
        "source_url": source_url,
        "attribution": attribution,
        "cache_path": normalized or None,
        "status": status,
        "error": error,
    }


def source_metadata_from_path(path: Optional[str], existing: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    metadata = source_metadata(path)
    if existing:
        metadata.update(
            {key: _json_safe(value) for key, value in existing.items() if value is not None}
        )
    return metadata
