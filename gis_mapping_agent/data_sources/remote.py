"""Remote geospatial boundary acquisition for natural-language map requests."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import requests
from threading import RLock

from ..utils.config import Config
from ..utils.logger import get_logger
from .planner import LocationResolution


LOGGER = get_logger("RemoteDataSource")
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OVERPASS_ENDPOINTS = (
    OVERPASS_URL,
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
)
USER_AGENT = "MapLLM/1.0 (local GIS mapping application)"
REMOTE_MAX_ATTEMPTS = 3
REMOTE_BACKOFF_SECONDS = 0.5
REMOTE_HTTP_TIMEOUT_SECONDS = 15
REMOTE_TOTAL_TIMEOUT_SECONDS = 45
REMOTE_POI_CATEGORIES: Dict[str, Dict[str, Any]] = {
    "universities": {"label": "高校", "filter": "[amenity~'^(university|college)$']"},
    "primary_schools": {"label": "小学", "filter": "[amenity='school']"},
    "schools": {"label": "学校", "filter": "[amenity='school']"},
    "hospitals": {"label": "医院", "filter": "[amenity='hospital']"},
    "parks": {"label": "公园", "filter": "[leisure='park']"},
}
_CACHE_LOCK = RLock()


class RemoteDataSourceError(RuntimeError):
    """Typed remote-source failure that can be converted into a tool result."""

    def __init__(self, message: str, *, code: str, retryable: bool = False):
        super().__init__(message)
        self.error_code = code
        self.retryable = retryable


def _valid_geojson_cache(path: Path) -> bool:
    if not path.is_file() or path.stat().st_size <= 0:
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return (
            payload.get("type") == "FeatureCollection"
            and isinstance(payload.get("features"), list)
            and bool(payload["features"])
            and all(isinstance(feature, dict) and feature.get("geometry") for feature in payload["features"])
        )
    except (OSError, UnicodeDecodeError, TypeError, ValueError):
        return False


def _write_geojson_cache(path: Path, payload: Dict[str, Any]) -> None:
    with _CACHE_LOCK:
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, path)


def _request_with_retries(
    method: str,
    url: str,
    *,
    timeout: int,
    deadline: Optional[float] = None,
    **kwargs,
):
    """Retry transient HTTP failures without exceeding a bounded deadline."""
    last_error = None
    deadline = deadline or (time.monotonic() + REMOTE_TOTAL_TIMEOUT_SECONDS)
    for attempt in range(1, REMOTE_MAX_ATTEMPTS + 1):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            request_method = getattr(requests, method.lower())
            request_timeout = min(
                float(timeout), REMOTE_HTTP_TIMEOUT_SECONDS, remaining
            )
            response = request_method(url, timeout=request_timeout, **kwargs)
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            last_error = exc
            if attempt == REMOTE_MAX_ATTEMPTS:
                break
            delay = REMOTE_BACKOFF_SECONDS * (2 ** (attempt - 1))
            LOGGER.warning(f"远程请求失败，将在 {delay:.1f}s 后重试 ({attempt}/{REMOTE_MAX_ATTEMPTS - 1}): {url}: {exc}")
            time.sleep(min(delay, max(0.0, deadline - time.monotonic())))

    raise RemoteDataSourceError(
        f"远程服务暂时不可用: {url}: {last_error}",
        code="network_error",
        retryable=True,
    )


def extract_location_query(user_request: str) -> Optional[str]:
    """Extract the place phrase from a Chinese map-generation request."""
    text = re.sub(r"\s+", "", str(user_request or "")).strip()
    if not text:
        return None

    match = re.search(
        r"(?:帮我|请|给我)?(?:绘制|画|制作)(?:一下|一张|出)?(.+?)(?:的)?地图",
        text,
    )
    if match:
        place = match.group(1).strip("，,。；; ")
        return place or None

    match = re.search(
        r"(?:帮我|请|给我)?(?:绘制|画|制作|显示|标注|查询)(?:一下|一张|出|出来)?"
        r"(.+?)(?:的)?(?:主要道路|道路(?:地图)?|公路|河流|铁路)",
        text,
    )
    if match:
        place = match.group(1).strip("，,。；; ")
        return place or None

    match = re.search(r"(?:地图|map)(?:.*?)(?:在|关于|为)([^，,。；;]+)", text, re.I)
    if match:
        return match.group(1).strip()
    return None


def extract_remote_poi_request(user_request: str) -> Optional[Dict[str, Optional[str]]]:
    """Extract a generic POI category and optional place from natural language."""
    text = re.sub(r"\s+", "", str(user_request or "")).strip()
    if not text:
        return None

    category_patterns = (
        ("universities", "高校", r"(?:各大高校|所有高校|各高校|高校分布|高校位置|所有大学|大学分布|大学位置|大学|高校)"),
        ("primary_schools", "小学", r"(?:各小学|所有小学|小学分布|小学位置|小学)"),
        ("schools", "学校", r"(?:各学校|所有学校|学校分布|学校位置)"),
        ("hospitals", "医院", r"(?:各医院|所有医院|医院分布|医院位置|医院)"),
        ("parks", "公园", r"(?:各公园|所有公园|公园分布|公园位置|公园)"),
    )
    action_prefix = r"(?:标注|标记|显示|查询|添加|绘制|画|把)(?:出|一下|出来)?"

    def clean_place(value: str) -> Optional[str]:
        value = value.strip("的，,。；; ")
        value = re.sub(
            r"(?:各大高校|所有高校|各高校|高校|所有大学|大学分布|大学位置|"
            r"各个小学|所有小学|各小学|小学分布|小学位置|"
            r"各个学校|所有学校|各学校|学校分布|学校位置|"
            r"各个医院|所有医院|各医院|医院分布|医院位置|"
            r"各个公园|所有公园|各公园|公园分布|公园位置)$",
            "",
            value,
        )
        value = re.sub(r"(?:各个|所有|各|主要)$", "", value)
        return value.strip("的，,。；; ") or None

    named_match = re.search(action_prefix + r"(.+?)(?:的)?(?:位置|分布)", text)
    if named_match:
        candidate = clean_place(named_match.group(1))
        for category, label, category_pattern in category_patterns:
            if candidate:
                if re.search(category_pattern, named_match.group(1)):
                    return {"place": candidate, "category": category, "label": label}
    for category, label, category_pattern in category_patterns:
        match = re.search(action_prefix + r"(.+?)" + category_pattern, text)
        if match:
            place = clean_place(match.group(1))
            return {"place": place, "category": category, "label": label}
        if re.search(category_pattern, text):
            return {"place": None, "category": category, "label": label}
    return None


def resolve_location(query: str, *, timeout: int = 30) -> LocationResolution:
    """Resolve one semantic place and reject unusable or global extents."""
    place = str(query or "").strip()
    if not place:
        return LocationResolution(
            text=place,
            precision="unknown",
            bbox=None,
            geometry=None,
            provider="OpenStreetMap/Nominatim",
            confidence=0.0,
            error_code="location_not_resolved",
        )

    try:
        deadline = time.monotonic() + min(timeout, REMOTE_TOTAL_TIMEOUT_SECONDS)
        response = _request_with_retries(
            "GET",
            NOMINATIM_URL,
            deadline=deadline,
            params={
                "q": f"{place}, 中国",
                "format": "jsonv2",
                "polygon_geojson": 1,
                "limit": 1,
            },
            headers={"User-Agent": USER_AGENT},
            timeout=timeout,
        )
        results = response.json()
    except RemoteDataSourceError as exc:
        return LocationResolution(
            text=place,
            precision="unknown",
            bbox=None,
            geometry=None,
            provider="OpenStreetMap/Nominatim",
            confidence=0.0,
            error_code=exc.error_code,
        )
    except (ValueError, TypeError, requests.RequestException):
        return LocationResolution(
            text=place,
            precision="unknown",
            bbox=None,
            geometry=None,
            provider="OpenStreetMap/Nominatim",
            confidence=0.0,
            error_code="location_not_resolved",
        )

    if not isinstance(results, list) or not results:
        return LocationResolution(
            text=place,
            precision="unknown",
            bbox=None,
            geometry=None,
            provider="OpenStreetMap/Nominatim",
            confidence=0.0,
            error_code="location_not_resolved",
        )

    item = results[0] if isinstance(results[0], dict) else {}
    geometry = item.get("geojson")
    bbox = None
    try:
        if geometry:
            from shapely.geometry import shape

            bounds = shape(geometry).bounds
            bbox = tuple(float(value) for value in bounds)
        else:
            raw_bbox = [float(value) for value in item.get("boundingbox", [])]
            if len(raw_bbox) == 4:
                bbox = (raw_bbox[2], raw_bbox[0], raw_bbox[3], raw_bbox[1])
    except (TypeError, ValueError, KeyError):
        bbox = None

    if not bbox or not _is_usable_location_bbox(bbox):
        return LocationResolution(
            text=place,
            precision="unknown",
            bbox=None,
            geometry=None,
            provider="OpenStreetMap/Nominatim",
            confidence=0.0,
            error_code="location_not_resolved",
        )

    precision = "city" if item.get("type") in {"city", "town", "county", "administrative"} else "place"
    return LocationResolution(
        text=place,
        precision=precision,
        bbox=bbox,
        geometry=geometry,
        provider="OpenStreetMap/Nominatim",
        confidence=0.98,
    )


def _is_usable_location_bbox(bbox: Tuple[float, float, float, float]) -> bool:
    west, south, east, north = bbox
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        return False
    # A geocoder result spanning the world is not a usable place resolution.
    return (east - west) < 350 and (north - south) < 170


def extract_remote_poi_query(user_request: str) -> Optional[str]:
    """Return a place only for batch POI requests across registered categories."""
    request = extract_remote_poi_request(user_request)
    if not request:
        return None
    text = str(user_request or "")
    if re.search(r"(?:的)?位置", text) and not re.search(r"各|所有|分布|主要", text):
        return None
    return request["place"]


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
    with _CACHE_LOCK:
        if _valid_geojson_cache(output_path):
            return output_path

    deadline = time.monotonic() + min(timeout, REMOTE_TOTAL_TIMEOUT_SECONDS)
    response = _request_with_retries(
        "GET",
        NOMINATIM_URL,
        deadline=deadline,
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
    _write_geojson_cache(output_path, payload)
    LOGGER.info(f"已缓存远程地点边界: {place} -> {output_path}")
    return output_path


def fetch_remote_waterways(
    query: str,
    bbox: list[float],
    *,
    cache_dir: Optional[Path] = None,
    timeout: int = 60,
) -> Optional[Path]:
    """Fetch named river lines for a place and cache them as GeoJSON."""
    place = str(query or "").strip()
    try:
        values = [float(value) for value in bbox]
    except (TypeError, ValueError):
        return None
    if not place or len(values) != 4:
        return None
    west, south, east, north = values
    if west >= east or south >= north:
        return None

    root = Path(cache_dir or (Config.DATA_CACHE_DIR / "remote_waterways"))
    root.mkdir(parents=True, exist_ok=True)
    cache_key = hashlib.sha256(
        f"named-rivers-v2:{place.casefold()}:{west:.6f},{south:.6f},{east:.6f},{north:.6f}".encode("utf-8")
    ).hexdigest()[:16]
    output_path = root / f"{cache_key}.geojson"
    with _CACHE_LOCK:
        if _valid_geojson_cache(output_path):
            return output_path

    overpass_query = (
        f"[out:json][timeout:{timeout}];"
        f"way[waterway='river'][name]({south},{west},{north},{east});"
        "out tags geom;"
    )
    features = []
    errors = []
    deadline = time.monotonic() + min(timeout, REMOTE_TOTAL_TIMEOUT_SECONDS)
    for endpoint in OVERPASS_ENDPOINTS:
        try:
            response = _request_with_retries(
                "POST",
                endpoint,
                deadline=deadline,
                data={"data": overpass_query},
                headers={"User-Agent": USER_AGENT},
                timeout=timeout,
            )
            response.raise_for_status()
            elements = response.json().get("elements", [])
        except (RemoteDataSourceError, requests.RequestException, ValueError, TypeError) as exc:
            errors.append(f"{endpoint}: {exc}")
            LOGGER.warning(f"远程河流数据端点失败: {place}: {endpoint}: {exc}")
            continue

        for element in elements:
            geometry = element.get("geometry") or []
            coordinates = [
                [point["lon"], point["lat"]]
                for point in geometry
                if "lon" in point and "lat" in point
            ]
            if len(coordinates) < 2:
                continue
            features.append(
                {
                    "type": "Feature",
                    "id": f"way-{element.get('id', len(features))}",
                    "properties": element.get("tags") or {},
                    "geometry": {"type": "LineString", "coordinates": coordinates},
                }
            )
        if features:
            break

        LOGGER.warning(f"远程河流数据端点无结果: {place}: {endpoint}")

    if not features:
        detail = f"；失败端点：{' | '.join(errors)}" if errors else ""
        LOGGER.warning(f"远程河流数据为空: {place}{detail}")
        if errors:
            raise RemoteDataSourceError(
                f"远程河流数据源不可用: {place}{detail}",
                code="network_error",
                retryable=True,
            )
        return None

    _write_geojson_cache(
        output_path, {"type": "FeatureCollection", "features": features}
    )
    LOGGER.info(f"已缓存远程河流数据: {place} ({len(features)} 条) -> {output_path}")
    return output_path


def fetch_remote_roads(
    query: str,
    bbox: list[float],
    *,
    cache_dir: Optional[Path] = None,
    timeout: int = 60,
) -> Optional[Path]:
    """Fetch named OSM road lines for a place and cache them as GeoJSON."""
    place = str(query or "").strip()
    try:
        values = [float(value) for value in bbox]
    except (TypeError, ValueError):
        return None
    if not place or len(values) != 4:
        return None
    west, south, east, north = values
    if west >= east or south >= north:
        return None

    root = Path(cache_dir or (Config.DATA_CACHE_DIR / "remote_roads"))
    root.mkdir(parents=True, exist_ok=True)
    cache_key = hashlib.sha256(
        f"named-roads-v1:{place.casefold()}:{west:.6f},{south:.6f},{east:.6f},{north:.6f}".encode(
            "utf-8"
        )
    ).hexdigest()[:16]
    output_path = root / f"{cache_key}.geojson"
    with _CACHE_LOCK:
        if _valid_geojson_cache(output_path):
            return output_path

    overpass_query = (
        f"[out:json][timeout:{timeout}];"
        f"way[highway~'^(motorway|trunk|primary|secondary|tertiary)$'][name]"
        f"({south},{west},{north},{east});"
        "out tags geom;"
    )
    features = []
    errors = []
    deadline = time.monotonic() + min(timeout, REMOTE_TOTAL_TIMEOUT_SECONDS)
    for endpoint in OVERPASS_ENDPOINTS:
        try:
            response = _request_with_retries(
                "POST",
                endpoint,
                deadline=deadline,
                data={"data": overpass_query},
                headers={"User-Agent": USER_AGENT},
                timeout=timeout,
            )
            elements = response.json().get("elements", [])
        except (RemoteDataSourceError, requests.RequestException, ValueError, TypeError) as exc:
            errors.append(f"{endpoint}: {exc}")
            LOGGER.warning(f"远程道路数据端点失败: {place}: {endpoint}: {exc}")
            continue

        for element in elements:
            geometry = element.get("geometry") or []
            coordinates = [
                [point["lon"], point["lat"]]
                for point in geometry
                if "lon" in point and "lat" in point
            ]
            if len(coordinates) < 2:
                continue
            features.append(
                {
                    "type": "Feature",
                    "id": f"way-{element.get('id', len(features))}",
                    "properties": {
                        **(element.get("tags") or {}),
                        "source": "OpenStreetMap/Overpass",
                        "place": place,
                    },
                    "geometry": {"type": "LineString", "coordinates": coordinates},
                }
            )
        if features:
            break
        LOGGER.warning(f"远程道路数据端点无结果: {place}: {endpoint}")

    if not features:
        detail = f"；失败端点：{' | '.join(errors)}" if errors else ""
        LOGGER.warning(f"远程道路数据为空: {place}{detail}")
        if errors:
            raise RemoteDataSourceError(
                f"远程道路数据源不可用: {place}{detail}",
                code="network_error",
                retryable=True,
            )
        return None

    _write_geojson_cache(
        output_path, {"type": "FeatureCollection", "features": features}
    )
    LOGGER.info(f"已缓存远程道路数据: {place} ({len(features)} 条) -> {output_path}")
    return output_path


def fetch_remote_pois(
    query: str,
    bbox: list[float],
    *,
    cache_dir: Optional[Path] = None,
    timeout: int = 60,
    category: str = "universities",
    amenity_types: tuple[str, ...] = ("university", "college"),
) -> Optional[Path]:
    """Fetch named POI points from OpenStreetMap using a registered category.

    The result is cached as a Point GeoJSON file so the normal layer renderer
    can consume it without a separate runtime data format.
    """
    place = str(query or "").strip()
    try:
        values = [float(value) for value in bbox]
    except (TypeError, ValueError):
        return None
    category_spec = REMOTE_POI_CATEGORIES.get(category)
    if not place or len(values) != 4 or not category_spec:
        return None
    west, south, east, north = values
    if west >= east or south >= north:
        return None

    root = Path(cache_dir or (Config.DATA_CACHE_DIR / "remote_pois"))
    root.mkdir(parents=True, exist_ok=True)
    categories = category if category != "universities" else ",".join(sorted(amenity_types))
    cache_key = hashlib.sha256(
        f"pois-v2:{category}:{place.casefold()}:{categories}:{west:.6f},{south:.6f},{east:.6f},{north:.6f}".encode(
            "utf-8"
        )
    ).hexdigest()[:16]
    output_path = root / f"{cache_key}.geojson"
    with _CACHE_LOCK:
        if _valid_geojson_cache(output_path):
            return output_path

    overpass_query = (
        f"[out:json][timeout:{timeout}];"
        f"nwr{category_spec['filter']}[name]({south},{west},{north},{east});"
        "out center tags;"
    )
    features = []
    errors = []
    deadline = time.monotonic() + min(timeout, REMOTE_TOTAL_TIMEOUT_SECONDS)
    for endpoint in OVERPASS_ENDPOINTS:
        try:
            response = _request_with_retries(
                "POST",
                endpoint,
                deadline=deadline,
                data={"data": overpass_query},
                headers={"User-Agent": USER_AGENT},
                timeout=timeout,
            )
            response.raise_for_status()
            elements = response.json().get("elements", [])
        except (RemoteDataSourceError, requests.RequestException, ValueError, TypeError) as exc:
            errors.append(f"{endpoint}: {exc}")
            LOGGER.warning(f"远程{category_spec['label']}数据端点失败: {place}: {endpoint}: {exc}")
            continue

        for element in elements:
            tags = element.get("tags") or {}
            name = str(tags.get("name") or "").strip()
            if not name:
                continue
            if category == "primary_schools":
                school_type = str(tags.get("school") or "").lower()
                isced_level = str(tags.get("isced:level") or "").lower()
                if not (
                    "primary" in school_type
                    or "小学" in name
                    or re.search(r"(?:^|;)\s*[12](?:;|$)", isced_level)
                ):
                    continue
            center = element.get("center") or {}
            longitude = element.get("lon", center.get("lon"))
            latitude = element.get("lat", center.get("lat"))
            try:
                coordinates = [float(longitude), float(latitude)]
            except (TypeError, ValueError):
                continue
            features.append(
                {
                    "type": "Feature",
                    "id": f"{element.get('type', 'element')}-{element.get('id', len(features))}",
                    "properties": {
                        **tags,
                        "source": "OpenStreetMap/Overpass",
                        "place": place,
                        "poi_category": category,
                    },
                    "geometry": {"type": "Point", "coordinates": coordinates},
                }
            )
        if features:
            break
        LOGGER.warning(f"远程{category_spec['label']}数据端点无结果: {place}: {endpoint}")

    if not features:
        detail = f"；失败端点：{' | '.join(errors)}" if errors else ""
        LOGGER.warning(f"远程{category_spec['label']}数据为空: {place}{detail}")
        if errors:
            raise RemoteDataSourceError(
                f"远程{category_spec['label']}数据源不可用: {place}{detail}",
                code="network_error",
                retryable=True,
            )
        return None

    _write_geojson_cache(
        output_path, {"type": "FeatureCollection", "features": features}
    )
    LOGGER.info(
        f"已缓存远程{category_spec['label']}点位: {place} ({len(features)} 个) -> {output_path}"
    )
    return output_path


def fetch_remote_named_poi(
    query: str,
    *,
    category: str = "universities",
    cache_dir: Optional[Path] = None,
) -> Optional[Path]:
    """Resolve one named POI as one point instead of querying a whole bbox."""
    category_spec = REMOTE_POI_CATEGORIES.get(category)
    place = str(query or "").strip()
    if not place or not category_spec:
        return None

    root = Path(cache_dir or (Config.DATA_CACHE_DIR / "remote_pois"))
    root.mkdir(parents=True, exist_ok=True)
    cache_key = hashlib.sha256(
        f"named-poi-v1:{category}:{place.casefold()}".encode("utf-8")
    ).hexdigest()[:16]
    output_path = root / f"{cache_key}.geojson"
    with _CACHE_LOCK:
        if _valid_geojson_cache(output_path):
            return output_path

    resolved = geocode_place(place)
    if not resolved:
        return None
    longitude, latitude, display_name = resolved
    payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": f"named-{cache_key}",
                "properties": {
                    "name": place,
                    "display_name": display_name,
                    "source": "OpenStreetMap/Nominatim",
                    "poi_category": category,
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": [float(longitude), float(latitude)],
                },
            }
        ],
    }
    _write_geojson_cache(output_path, payload)
    return output_path


def geocode_place(query: str, *, timeout: int = 30) -> Optional[Tuple[float, float, str]]:
    """Return a place centroid as ``(longitude, latitude, display_name)``."""
    place = str(query or "").strip()
    if not place:
        return None
    deadline = time.monotonic() + min(timeout, REMOTE_TOTAL_TIMEOUT_SECONDS)
    response = _request_with_retries(
        "GET",
        NOMINATIM_URL,
        deadline=deadline,
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
