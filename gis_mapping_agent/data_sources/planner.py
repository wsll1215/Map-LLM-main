"""Resolve natural-language layer roles to verified local datasets."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from .catalog import DatasetDescriptor, LocalDatasetCatalog
from ..utils.data_path_resolver import data_path_resolver


_CITY_LABEL_FIELDS = ("name", "NAME", "地名", "城市名", "城市", "名称")
_ROAD_TERMS = ("道路", "公路", "高速", "路网", "highway", "road")
_RAIL_TERMS = ("铁路", "高铁", "railway")
_RIVER_TERMS = ("河流", "河道", "水系", "river")
_CITY_TERMS = ("城市", "各市", "市区", "城镇", "所有城市")
_POI_TERMS = ("高校", "大学", "小学", "学校", "医院", "公园")


@dataclass(frozen=True)
class LayerIntent:
    """A user-requested semantic layer, independent of any data source."""

    role: str
    required: bool = True


@dataclass(frozen=True)
class LocationIntent:
    text: Optional[str]
    precision: Optional[str]


@dataclass(frozen=True)
class Intent:
    """The only result produced by natural-language interpretation."""

    location: LocationIntent
    layers: Tuple[LayerIntent, ...] = ()
    explicit_sources: Tuple[str, ...] = ()
    unknown_fields: Tuple[str, ...] = ()
    confidence: float = 0.0


@dataclass(frozen=True)
class LocationResolution:
    """A backend-verified place resolution used to scope source selection."""

    text: str
    precision: str
    bbox: Optional[Tuple[float, float, float, float]]
    geometry: Optional[Any]
    provider: str
    confidence: float
    error_code: Optional[str] = None


@dataclass(frozen=True)
class PlannedSource:
    """A source candidate after backend validation."""

    role: str
    source_type: str
    provider: str
    source_url: Optional[str]
    cache_path: Optional[str]
    bbox: Tuple[float, float, float, float] = ()
    feature_count: int = 0
    status: str = "planned"
    spatial_valid: Optional[bool] = None
    geometry_valid: Optional[bool] = None
    error_code: Optional[str] = None
    retryable: bool = False
    next_action: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SourcePlan:
    """The backend's source decision for one parsed intent."""

    intent: Intent
    location: Optional[LocationResolution]
    layers: Tuple[PlannedSource, ...]
    issues: Tuple[str, ...] = ()
    attempts: Tuple[Mapping[str, Any], ...] = ()

    @property
    def has_deliverable_source(self) -> bool:
        return any(layer.status == "available" for layer in self.layers)


def _contains_any(text: str, terms: Iterable[str]) -> bool:
    return any(term in text for term in terms)


_ROLE_TERMS = {
    "boundary": ("边界", "行政区", "行政区划", "boundary"),
    "road": _ROAD_TERMS,
    "railway": _RAIL_TERMS,
    "river": _RIVER_TERMS,
    "school": ("学校",),
    "primary_school": ("小学",),
    "university": ("高校", "大学"),
    "hospital": ("医院",),
    "park": ("公园",),
}

_LOCATION_ACTIONS = "绘制|画|制作|显示|标注|查询|添加|把|展示|查看"
_LOCATION_LAYER_TERMS = (
    "主要道路",
    "道路",
    "公路",
    "铁路",
    "河流",
    "边界",
    "行政区",
    "小学",
    "学校",
    "高校",
    "大学",
    "医院",
    "公园",
)


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "")).strip()


def _extract_intent_location(text: str) -> Optional[str]:
    """Extract a place phrase without selecting a file or calling a provider."""
    # Keep the extractor deliberately semantic: it stops at a registered layer
    # role and never turns the complete user sentence into a geocoder query.
    position_match = re.search(
        rf"(?:{_LOCATION_ACTIONS})(?:一下|一张|出来|出)?(.+?)(?:的)?(?:位置|分布)",
        text,
        re.IGNORECASE,
    )
    if position_match:
        candidate = position_match.group(1).strip("的，,。；; ")
        for suffix in ("各大高校", "所有高校", "各高校", "高校", "所有大学", "大学分布"):
            if candidate.endswith(suffix) and candidate != suffix:
                candidate = candidate[: -len(suffix)].strip("的，,。；; ")
                break
        return candidate or None

    map_match = re.search(
        rf"(?:{_LOCATION_ACTIONS})(?:一下|一张|出来|出)?(.+?)(?:的)?地图",
        text,
        re.IGNORECASE,
    )
    if map_match:
        return map_match.group(1).strip("的，,。；; ") or None

    layer_pattern = "|".join(re.escape(term) for term in _LOCATION_LAYER_TERMS)
    match = re.search(
        rf"(?:{_LOCATION_ACTIONS})(?:一下|一张|出来|出)?(.+?)(?:的)?(?:{layer_pattern})",
        text,
        re.IGNORECASE,
    )
    if match:
        candidate = re.sub(r"(?:的)?(?:主要|所有|各个|各) $", "", match.group(1))
        candidate = candidate.strip("的，,。；; ")
        candidate = re.sub(r"(?:的)?(?:主要|所有|各个|各)$", "", candidate)
        return candidate or None

    return None


def _location_precision(text: Optional[str], layers: Iterable[LayerIntent]) -> Optional[str]:
    if not text:
        return None
    if any(layer.role in {"university", "school", "primary_school", "hospital", "park"} for layer in layers):
        return "place"
    if any(token in text for token in ("省", "市", "区", "县", "州", "镇")):
        return "city"
    return "place"


def parse_intent(user_request: str) -> Intent:
    """Parse semantic intent; source selection remains outside this function."""
    raw_text = str(user_request or "")
    text = _normalize_text(raw_text)
    explicit_sources = tuple(
        dict.fromkeys(
            re.findall(
                r"(?:[A-Za-z]:[\\/])?[^\s，,。；;]+\.(?:shp|geojson|gpkg)(?=[\s，,。；;]|$)",
                raw_text,
                re.IGNORECASE,
            )
        )
    )
    layers: List[LayerIntent] = []
    for role, terms in _ROLE_TERMS.items():
        if _contains_any(text.lower(), terms):
            layers.append(LayerIntent(role=role, required=True))

    if not layers and "地图" in text:
        layers.append(LayerIntent(role="boundary", required=False))

    location_text = _extract_intent_location(text)
    return Intent(
        location=LocationIntent(
            text=location_text,
            precision=_location_precision(location_text, layers),
        ),
        layers=tuple(layers),
        explicit_sources=explicit_sources,
        confidence=0.9 if location_text else 0.25,
    )


def resolve_local_location(query: Optional[str], catalog: Any) -> Optional[LocationResolution]:
    """Resolve a place from registered dataset metadata before using a geocoder."""
    needle = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", str(query or "").lower())
    if not needle or catalog is None:
        return None

    def comparable(value: str) -> str:
        normalized = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", str(value).lower())
        return re.sub(r"(?:省|市|区|县|州)$", "", normalized)

    comparable_needle = comparable(needle)
    if len(needle) < 2 or not comparable_needle:
        return None
    candidates = []
    for descriptor in catalog.scan():
        if not _source_role_matches(descriptor, "boundary"):
            continue
        values = [descriptor.name, *getattr(descriptor, "aliases", [])]
        normalized = [
            re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", str(value).lower())
            for value in values
        ]
        comparable_values = [comparable(value) for value in values]
        score = 100 if needle in normalized or comparable_needle in comparable_values else 0
        if score and len(getattr(descriptor, "bbox", []) or []) == 4:
            candidates.append((score, descriptor))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (-item[0], item[1].local_path))
    descriptor = candidates[0][1]
    return LocationResolution(
        text=str(query),
        precision="city",
        bbox=tuple(float(value) for value in descriptor.bbox),
        geometry=None,
        provider="PostGIS",
        confidence=0.95,
    )


def _source_bbox_intersects(
    left: Iterable[float], right: Optional[Iterable[float]]
) -> bool:
    if right is None:
        return True
    left_values = list(left)
    right_values = list(right)
    if len(left_values) != 4 or len(right_values) != 4:
        return False
    return not (
        left_values[2] < right_values[0]
        or left_values[0] > right_values[2]
        or left_values[3] < right_values[1]
        or left_values[1] > right_values[3]
    )


def _valid_bbox(values: Optional[Iterable[float]]) -> bool:
    try:
        numbers = [float(value) for value in (values or ())]
    except (TypeError, ValueError):
        return False
    return (
        len(numbers) == 4
        and all(number == number and abs(number) != float("inf") for number in numbers)
        and numbers[0] < numbers[2]
        and numbers[1] < numbers[3]
    )


def _source_role_matches(source: Any, role: str) -> bool:
    source_role = getattr(source, "role", None)
    if source_role:
        return source_role == role
    metadata = getattr(source, "metadata", {}) or {}
    roles = metadata.get("roles", ())
    if role in roles:
        return True
    name = str(getattr(source, "name", "")).lower()
    aliases = [str(value).lower() for value in getattr(source, "aliases", ()) or ()]
    return any(_contains_any(value, _ROLE_TERMS.get(role, ())) for value in [name, *aliases])


def _as_planned_source(source: Any, role: str) -> PlannedSource:
    if isinstance(source, PlannedSource):
        return source
    bbox = tuple(float(value) for value in (getattr(source, "bbox", ()) or ()))
    return PlannedSource(
        role=role,
        source_type=getattr(source, "source_type", "local"),
        provider=getattr(source, "provider", "PostGIS"),
        source_url=getattr(source, "source_url", None),
        cache_path=getattr(source, "cache_path", None)
        or getattr(source, "local_path", None),
        bbox=bbox,
        feature_count=int(getattr(source, "feature_count", 0) or 0),
        status=getattr(source, "status", "available"),
        metadata=getattr(source, "metadata", {}) or {},
    )


def plan_sources(
    intent: Intent,
    *,
    location: Optional[LocationResolution],
    catalog: Any,
    remote_sources: Optional[Mapping[str, PlannedSource]] = None,
    remote_errors: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> SourcePlan:
    """Select validated local sources, then consume explicit remote results."""
    candidates = list(catalog.scan()) if catalog is not None else []
    remote_sources = remote_sources or {}
    remote_errors = remote_errors or {}
    planned: List[PlannedSource] = []
    issues: List[str] = []

    explicit_sources = tuple(
        str(source).replace("\\", "/").lower() for source in intent.explicit_sources
    )
    for layer in intent.layers:
        matches = [
            _as_planned_source(candidate, layer.role)
            for candidate in candidates
            if _source_role_matches(candidate, layer.role)
            and getattr(candidate, "source_type", "local") == "local"
            and int(getattr(candidate, "feature_count", 0) or 0) > 0
            and (
                not explicit_sources
                or any(
                    str(getattr(candidate, "local_path", "") or getattr(candidate, "cache_path", ""))
                    .replace("\\", "/")
                    .lower()
                    .endswith(source)
                    for source in explicit_sources
                )
            )
            and _valid_bbox(getattr(candidate, "bbox", None))
        ]
        location_bbox = (
            location.bbox
            if location and not location.error_code and _valid_bbox(location.bbox)
            else None
        )
        local = next(
            (
                candidate
                for candidate in matches
                if location_bbox is not None
                and _source_bbox_intersects(candidate.bbox, location_bbox)
            ),
            None,
        )
        if local is not None:
            planned.append(
                PlannedSource(
                    **{
                        **local.__dict__,
                        "status": "available",
                        "spatial_valid": True,
                        "geometry_valid": True,
                    }
                )
            )
            continue

        rejected = next(iter(matches), None)
        rejected_source = None
        if rejected is not None:
            rejected_source = PlannedSource(
                **{
                    **rejected.__dict__,
                    "status": "rejected",
                    "spatial_valid": False,
                    "geometry_valid": None,
                    "error_code": "resource_not_found",
                    "next_action": "use_remote_source",
                }
            )
            planned.append(rejected_source)

        remote = remote_sources.get(layer.role)
        remote_is_valid = bool(
            remote is not None
            and remote.role == layer.role
            and remote.status == "available"
            and remote.feature_count > 0
            and remote.spatial_valid is not False
            and _valid_bbox(remote.bbox)
            and location_bbox is not None
            and _source_bbox_intersects(remote.bbox, location_bbox)
        )
        if remote_is_valid:
            if rejected is None:
                planned.append(remote)
            else:
                planned[-1] = remote
            continue

        error = remote_errors.get(layer.role)
        if error:
            failure = PlannedSource(
                role=layer.role,
                source_type="remote",
                provider=str(error.get("provider", "OpenStreetMap")),
                source_url=error.get("source_url"),
                cache_path=error.get("cache_path"),
                bbox=tuple(location.bbox or ()) if location and location.bbox else (),
                status="failed",
                error_code=error.get("error_code", "internal_error"),
                retryable=bool(error.get("retryable", False)),
                next_action=error.get("next_action"),
            )
            if rejected is None:
                planned.append(failure)
            else:
                planned[-1] = failure
            issues.append(f"{layer.role}:{failure.error_code}")
            continue

        failure = PlannedSource(
            role=layer.role,
            source_type="remote",
            provider="unresolved",
            source_url=None,
            cache_path=None,
            bbox=tuple(location.bbox or ()) if location and location.bbox else (),
            status="failed",
            spatial_valid=False if location_bbox is not None else None,
            error_code="location_not_resolved"
            if location_bbox is None
            else "resource_not_found",
            next_action="use_remote_source",
        )
        if rejected is None:
            planned.append(failure)
        else:
            planned[-1] = failure
        issues.append(f"{layer.role}:resource_not_found")

    return SourcePlan(
        intent=intent,
        location=location,
        layers=tuple(planned),
        issues=tuple(issues),
    )


def _data_path(descriptor: DatasetDescriptor) -> str:
    return f"data/{descriptor.local_path}"


def _preferred(descriptor: DatasetDescriptor, directory: Optional[str]) -> bool:
    return bool(directory and descriptor.local_path.startswith(f"{directory}/"))


def _geometry_matches(actual: str, expected: Optional[object]) -> bool:
    if expected is None:
        return True
    expected_types = (expected,) if isinstance(expected, str) else tuple(expected)
    actual = actual.lower()
    return any(str(value).lower() in actual for value in expected_types)


def _bbox_intersects(left: Iterable[float], right: Optional[Iterable[float]]) -> bool:
    if right is None:
        return True
    left_values = list(left)
    right_values = list(right)
    if len(left_values) != 4 or len(right_values) != 4:
        return False
    return not (
        left_values[2] < right_values[0]
        or left_values[0] > right_values[2]
        or left_values[3] < right_values[1]
        or left_values[1] > right_values[3]
    )


def _bbox_overlap_ratio(left: Iterable[float], right: Iterable[float]) -> float:
    left_values = list(left)
    right_values = list(right)
    if len(left_values) != 4 or len(right_values) != 4:
        return 0.0
    overlap_width = max(0.0, min(left_values[2], right_values[2]) - max(left_values[0], right_values[0]))
    overlap_height = max(0.0, min(left_values[3], right_values[3]) - max(left_values[1], right_values[1]))
    overlap = overlap_width * overlap_height
    target_area = max(0.0, (right_values[2] - right_values[0]) * (right_values[3] - right_values[1]))
    return overlap / target_area if target_area else 0.0


def _choose(
    descriptors: Iterable[DatasetDescriptor],
    *,
    names: Iterable[str],
    directory: Optional[str] = None,
    geometry: Optional[object] = None,
    spatial_bbox: Optional[Iterable[float]] = None,
) -> Optional[DatasetDescriptor]:
    names = {name.lower() for name in names}
    candidates = []
    for descriptor in descriptors:
        if getattr(descriptor, "source_type", "local") != "local":
            continue
        if descriptor.name.lower() not in names:
            continue
        if not _geometry_matches(descriptor.geometry_type, geometry):
            continue
        if not _bbox_intersects(descriptor.bbox, spatial_bbox):
            continue
        candidates.append(descriptor)
    candidates.sort(key=lambda item: (not _preferred(item, directory), item.local_path))
    return candidates[0] if candidates else None


def _city_label_column(descriptor: Optional[DatasetDescriptor]) -> Optional[str]:
    if descriptor is None:
        return None
    fields = set(descriptor.metadata.get("fields", []))
    return next((field for field in _CITY_LABEL_FIELDS if field in fields), None)


@dataclass(frozen=True)
class SemanticLayerPlan:
    """Verified source files for semantic map-layer roles."""

    boundary_path: Optional[str] = None
    road_path: Optional[str] = None
    river_path: Optional[str] = None
    poi_path: Optional[str] = None
    poi_category: Optional[str] = None
    poi_label: Optional[str] = None
    city_label_column: Optional[str] = None
    requested_roles: Tuple[str, ...] = ()
    issues: Tuple[str, ...] = ()

    def role_for_layer(self, layer_name: str) -> Optional[str]:
        text = (layer_name or "").lower()
        if _contains_any(text, _POI_TERMS):
            return "poi"
        if _contains_any(text, _RIVER_TERMS):
            return "river"
        if _contains_any(text, _RAIL_TERMS) or _contains_any(text, _ROAD_TERMS):
            return "road"
        if _contains_any(text, ("城市", "市", "省", "边界", "行政", "boundary")):
            return "boundary"
        return None

    def path_for_layer(self, layer_name: str) -> Optional[str]:
        """Return the verified source for a model-proposed layer name."""
        role = self.role_for_layer(layer_name)
        if role == "river":
            return self.river_path
        if role == "road":
            return self.road_path
        if role == "boundary":
            return self.boundary_path
        if role == "poi":
            return self.poi_path
        return None

    def requires_layer(self, layer_name: str) -> bool:
        role = self.role_for_layer(layer_name)
        return bool(role and role in self.requested_roles)

    def prompt_instructions(self) -> str:
        """Create compact, explicit constraints for the tool-calling model."""
        lines = ["系统已核验本次需求的数据源，调用 add_layer 时必须遵守以下映射："]
        if self.boundary_path:
            label = (
                f"，并使用 label_column='{self.city_label_column}' 标注所有城市"
                if self.city_label_column
                else ""
            )
            source_label = "远程" if "data_cache" in self.boundary_path else "本地"
            lines.append(f"- {source_label}边界/城市：{self.boundary_path}{label}")
        if self.road_path:
            source_label = "远程" if "data_cache" in self.road_path else "本地"
            lines.append(f"- {source_label}道路：{self.road_path}")
        if self.river_path:
            source_label = "远程" if "data_cache" in self.river_path else "本地"
            lines.append(f"- {source_label}河流：{self.river_path}")
        if self.poi_path:
            source_label = "远程" if "data_cache" in self.poi_path else "本地"
            lines.append(f"- {source_label}{self.poi_label or 'POI'}：{self.poi_path}")
        lines.append("不要把省界文件重复用作道路或河流；如果已核验数据源仍缺失，必须报告缺失，不得猜测路径。")
        return "\n".join(lines)


def plan_local_sources(
    user_request: str,
    *,
    catalog: Optional[LocalDatasetCatalog] = None,
    boundary_path: Optional[str] = None,
    location_bbox: Optional[Iterable[float]] = None,
) -> SemanticLayerPlan:
    """Plan local files for a request without trusting model-invented paths."""
    text = (user_request or "").lower()
    catalog = catalog or LocalDatasetCatalog()
    descriptors = list(catalog.scan())
    if location_bbox is not None and not isinstance(catalog, LocalDatasetCatalog):
        # Runtime planning must use the registered database catalog. The path
        # resolver has legacy heuristics that infer a directory from place
        # names, which is not an explicit user source selection.
        directory, files = None, []
    else:
        directory, files = data_path_resolver.extract_data_info(user_request or "")

    boundary = None
    if files and directory:
        requested_name = re.sub(r"\.shp$", "", files[0], flags=re.IGNORECASE).lower()
        boundary = _choose(descriptors, names=(requested_name,), directory=directory)
    if boundary is None and directory:
        boundary = next(
            (
                descriptor
                for descriptor in descriptors
                if _preferred(descriptor, directory)
                and "polygon" in descriptor.geometry_type.lower()
                and _city_label_column(descriptor)
            ),
            None,
        )

    if boundary is None and location_bbox:
        boundary_candidates = [
            descriptor
            for descriptor in descriptors
            if _source_role_matches(descriptor, "boundary")
            and _bbox_intersects(descriptor.bbox, location_bbox)
            and descriptor.feature_count
            and descriptor.feature_count > 0
        ]
        boundary_candidates.sort(
            key=lambda descriptor: (
                -_bbox_overlap_ratio(descriptor.bbox, location_bbox),
                descriptor.local_path,
            )
        )
        boundary = boundary_candidates[0] if boundary_candidates else None

    resolved_boundary_path = _data_path(boundary) if boundary else boundary_path

    road = None
    if _contains_any(text, _RAIL_TERMS):
        road = _choose(descriptors, names=("Railway",), directory=directory, geometry="line")
    elif _contains_any(text, _ROAD_TERMS):
        road = _choose(
            descriptors,
            names=("Highway", "Road", "道路", "公路"),
            directory=directory,
            geometry="line",
            spatial_bbox=location_bbox or (boundary.bbox if boundary else None),
        )

    river = None
    if _contains_any(text, _RIVER_TERMS):
        river = _choose(
            descriptors,
            names=("River", "河流", "河道"),
            geometry=("line", "polygon"),
            spatial_bbox=location_bbox or (boundary.bbox if boundary else None),
        )

    poi_role = next(
        (
            role
            for role, terms in (
                ("primary_school", ("小学",)),
                ("university", ("高校", "大学")),
                ("school", ("学校",)),
                ("hospital", ("医院",)),
                ("park", ("公园",)),
            )
            if _contains_any(text, terms)
        ),
        None,
    )
    poi = None
    if poi_role:
        poi_candidates = [
            descriptor
            for descriptor in descriptors
            if getattr(descriptor, "source_type", "local") == "local"
            and getattr(descriptor, "role", None) == poi_role
            and int(getattr(descriptor, "feature_count", 0) or 0) > 0
            and _bbox_intersects(getattr(descriptor, "bbox", ()), location_bbox)
        ]
        poi_candidates.sort(
            key=lambda descriptor: (
                not _preferred(descriptor, directory),
                descriptor.local_path,
            )
        )
        poi = poi_candidates[0] if poi_candidates else None

    issues = []
    if _contains_any(text, _ROAD_TERMS) and road is None:
        issues.append("未找到可用的道路线数据")
    if _contains_any(text, _RIVER_TERMS) and river is None:
        issues.append("未找到可用的河流数据")
    if _contains_any(text, _CITY_TERMS) and _city_label_column(boundary) is None:
        issues.append("边界数据缺少城市名称字段，无法标注所有城市")

    return SemanticLayerPlan(
        boundary_path=resolved_boundary_path,
        road_path=_data_path(road) if road else None,
        river_path=_data_path(river) if river else None,
        poi_path=_data_path(poi) if poi else None,
        poi_category={
            "primary_school": "primary_schools",
            "university": "universities",
            "school": "schools",
            "hospital": "hospitals",
            "park": "parks",
        }.get(poi_role),
        poi_label={
            "primary_school": "小学",
            "university": "高校",
            "school": "学校",
            "hospital": "医院",
            "park": "公园",
        }.get(poi_role),
        city_label_column=_city_label_column(boundary) if _contains_any(text, _CITY_TERMS) else None,
        requested_roles=tuple(
            role
            for role, requested in (
                ("road", _contains_any(text, _ROAD_TERMS) or _contains_any(text, _RAIL_TERMS)),
                ("river", _contains_any(text, _RIVER_TERMS)),
                ("boundary", bool(resolved_boundary_path)),
                ("poi", _contains_any(text, _POI_TERMS)),
            )
            if requested
        ),
        issues=tuple(issues),
    )
