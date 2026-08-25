"""Remote geospatial boundary acquisition for natural-language map requests."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Optional
from typing import Tuple

import requests

from ..utils.config import Config
from ..utils.logger import get_logger


LOGGER = get_logger("RemoteDataSource")
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "MapLLM/1.0 (local GIS mapping application)"


def extract_location_query(user_request: str) -> Optional[str]:
    """Extract the place phrase from a Chinese map-generation request."""
    text = re.sub(r"\s+", "", str(user_request or "")).strip()
    if not text:
        return None

    match = re.search(
        r"(?:帮我|请|给我)?(?:绘制|画|制作)(?:一下|一张|出)?(.+?)(?:的)?地图(?:[。！!？?].*)?$",
        text,
    )
    if match:
        place = match.group(1).strip("，,。；; ")
        return place or None

    match = re.search(r"(?:地图|map)(?:.*?)(?:在|关于|为)([^，,。；;]+)", text, re.I)
    if match:
        return match.group(1).strip()
    return None


def fetch_remote_boundary(
    query: str,
    *,
    cache_dir: Optional[Path] = None,
    timeout: int = 30,
) -> Optional[Path]:
    """Fetch and cache a GeoJSON boundary for a place name.

    Nominatim returns OSM boundary geometry. The cached file is a standard
    GeoJSON FeatureCollection so the existing GeoPandas layer loader can read it.
    """
    place = str(query or "").strip()
    if not place:
        return None

    root = Path(cache_dir or (Config.DATA_CACHE_DIR / "remote_boundaries"))
    root.mkdir(parents=True, exist_ok=True)
    cache_key = hashlib.sha256(place.casefold().encode("utf-8")).hexdigest()[:16]
    output_path = root / f"{cache_key}.geojson"
    if output_path.is_file() and output_path.stat().st_size > 0:
        return output_path

    response = requests.get(
        NOMINATIM_URL,
        params={
            "q": f"{place}, 中国",
            "format": "jsonv2",
            "polygon_geojson": 1,
            "limit": 1,
        },
        headers={"User-Agent": USER_AGENT},
        timeout=timeout,
    )
    response.raise_for_status()
    results = response.json()
    if not results or not results[0].get("geojson"):
        LOGGER.warning(f"远程地理编码未返回边界: {place}")
        return None

    item = results[0]
    payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": f"{item.get('osm_type', 'place')}-{item.get('osm_id', cache_key)}",
                "properties": {
                    "name": place,
                    "display_name": item.get("display_name", place),
                    "source": "OpenStreetMap/Nominatim",
                    "osm_type": item.get("osm_type"),
                    "osm_id": item.get("osm_id"),
                },
                "geometry": item["geojson"],
            }
        ],
    }
    output_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    LOGGER.info(f"已缓存远程地点边界: {place} -> {output_path}")
    return output_path


def geocode_place(query: str, *, timeout: int = 30) -> Optional[Tuple[float, float, str]]:
    """Return a place centroid as ``(longitude, latitude, display_name)``."""
    place = str(query or "").strip()
    if not place:
        return None
    response = requests.get(
        NOMINATIM_URL,
        params={"q": f"{place}, 中国", "format": "jsonv2", "limit": 1},
        headers={"User-Agent": USER_AGENT},
        timeout=timeout,
    )
    response.raise_for_status()
    results = response.json()
    if not results:
        LOGGER.warning(f"远程地理编码未返回地点: {place}")
        return None
    item = results[0]
    try:
        return float(item["lon"]), float(item["lat"]), item.get("display_name", place)
    except (KeyError, TypeError, ValueError):
        LOGGER.warning(f"远程地理编码坐标无效: {place}")
        return None


def normalize_point_to_extent(
    longitude: float, latitude: float, extent: list[float]
) -> list[float]:
    """Convert WGS84 coordinates into normalized figure coordinates."""
    min_lon, min_lat, max_lon, max_lat = (float(value) for value in extent)
    if min_lon >= max_lon or min_lat >= max_lat:
        raise ValueError("地图范围无效，无法计算注记位置")
    x = (float(longitude) - min_lon) / (max_lon - min_lon)
    y = (float(latitude) - min_lat) / (max_lat - min_lat)
    return [max(0.02, min(0.98, x)), max(0.02, min(0.98, y))]
