"""Resolve natural-language layer roles to verified local datasets."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Optional, Tuple

from .catalog import DatasetDescriptor, LocalDatasetCatalog
from ..utils.data_path_resolver import data_path_resolver


_CITY_LABEL_FIELDS = ("name", "NAME", "地名", "城市名", "城市", "名称")
_ROAD_TERMS = ("道路", "公路", "高速", "路网", "highway", "road")
_RAIL_TERMS = ("铁路", "高铁", "railway")
_RIVER_TERMS = ("河流", "河道", "水系", "river")
_CITY_TERMS = ("城市", "各市", "市区", "城镇", "所有城市")


def _contains_any(text: str, terms: Iterable[str]) -> bool:
    return any(term in text for term in terms)


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
    city_label_column: Optional[str] = None
    requested_roles: Tuple[str, ...] = ()
    issues: Tuple[str, ...] = ()

    def role_for_layer(self, layer_name: str) -> Optional[str]:
        text = (layer_name or "").lower()
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
        return None

    def requires_layer(self, layer_name: str) -> bool:
        role = self.role_for_layer(layer_name)
        return bool(role and role in self.requested_roles)

    def prompt_instructions(self) -> str:
        """Create compact, explicit constraints for the tool-calling model."""
        lines = ["系统已核验本次需求的本地数据源，调用 add_layer 时必须遵守以下映射："]
        if self.boundary_path:
            label = (
                f"，并使用 label_column='{self.city_label_column}' 标注所有城市"
                if self.city_label_column
                else ""
            )
            lines.append(f"- 广东省边界/城市：{self.boundary_path}{label}")
        if self.road_path:
            lines.append(f"- 道路：{self.road_path}")
        if self.river_path:
            lines.append(f"- 河流：{self.river_path}")
        lines.append("不要把省界文件重复用作道路或河流；如果某项数据源缺失，必须报告缺失，不得猜测路径。")
        return "\n".join(lines)


def plan_local_sources(
    user_request: str,
    *,
    catalog: Optional[LocalDatasetCatalog] = None,
) -> SemanticLayerPlan:
    """Plan local files for a request without trusting model-invented paths."""
    text = (user_request or "").lower()
    catalog = catalog or LocalDatasetCatalog()
    descriptors = list(catalog.scan())
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

    road = None
    if _contains_any(text, _RAIL_TERMS):
        road = _choose(descriptors, names=("Railway",), directory=directory, geometry="line")
    elif _contains_any(text, _ROAD_TERMS):
        road = _choose(
            descriptors,
            names=("Highway", "Road", "道路", "公路"),
            directory=directory,
            geometry="line",
            spatial_bbox=boundary.bbox if boundary else None,
        )

    river = None
    if _contains_any(text, _RIVER_TERMS):
        river = _choose(
            descriptors,
            names=("River", "河流", "河道"),
            geometry=("line", "polygon"),
            spatial_bbox=boundary.bbox if boundary else None,
        )

    issues = []
    if _contains_any(text, _ROAD_TERMS) and road is None:
        issues.append("未找到可用的道路线数据")
    if _contains_any(text, _RIVER_TERMS) and river is None:
        issues.append("未找到可用的河流数据")
    if _contains_any(text, _CITY_TERMS) and _city_label_column(boundary) is None:
        issues.append("边界数据缺少城市名称字段，无法标注所有城市")

    return SemanticLayerPlan(
        boundary_path=_data_path(boundary) if boundary else None,
        road_path=_data_path(road) if road else None,
        river_path=_data_path(river) if river else None,
        city_label_column=_city_label_column(boundary) if _contains_any(text, _CITY_TERMS) else None,
        requested_roles=tuple(
            role
            for role, requested in (
                ("road", _contains_any(text, _ROAD_TERMS) or _contains_any(text, _RAIL_TERMS)),
                ("river", _contains_any(text, _RIVER_TERMS)),
                ("boundary", bool(boundary)),
            )
            if requested
        ),
        issues=tuple(issues),
    )
