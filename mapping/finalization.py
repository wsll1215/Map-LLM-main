"""Single terminal decision for map execution results."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Set


@dataclass(frozen=True)
class LayerValidation:
    role: str
    required: bool
    source_type: Optional[str]
    feature_count: int
    spatial_valid: bool
    geometry_valid: bool = True
    source_valid: bool = True

    @property
    def valid(self) -> bool:
        return bool(
            self.source_valid
            and self.geometry_valid
            and self.spatial_valid
            and self.feature_count > 0
            and self.source_type in {"local", "remote", "upload"}
        )


@dataclass(frozen=True)
class ExecutionResult:
    status: str
    map_version: Optional[int]
    completion_report: Dict[str, Any]
    error_code: Optional[str]
    error_message: Optional[str]
    trace_id: Optional[str]


@dataclass(frozen=True)
class SpatialValidation:
    """Evidence that a source contains valid geometry in the resolved place."""

    role: str
    feature_count: int
    geometry_valid: bool
    spatial_valid: bool
    clipped: bool = False
    reason: Optional[str] = None
    clipped_frame: Any = None


def validate_source_spatial(source: Any, location: Any, role: str) -> SpatialValidation:
    """Validate geometry and place membership without treating bbox as proof."""
    try:
        from shapely.geometry import shape

        frame = getattr(source, "gdf", None)
        metadata = getattr(source, "data_source_meta", None) or {}
        dataset_id = metadata.get("dataset_id")
        if frame is None and dataset_id:
            from .dataset_reader import read_dataset_features

            frame = read_dataset_features(dataset_id, limit=100000)
        if frame is None:
            return SpatialValidation(
                role,
                int(getattr(source, "feature_count", 0) or 0),
                False,
                False,
                reason="dataset_not_registered",
            )
        if frame is None or len(frame) == 0:
            return SpatialValidation(role, 0, False, False, reason="empty_source")
        if getattr(frame, "crs", None) is None:
            return SpatialValidation(
                role,
                len(frame),
                False,
                False,
                reason="crs_missing",
            )
        frame_crs = frame.crs
        try:
            frame_epsg = frame_crs.to_epsg()
        except AttributeError:
            frame_epsg = None
        if frame_epsg != 4326 and str(frame_crs).upper() != "EPSG:4326":
            frame = frame.to_crs("EPSG:4326")
        geometries = frame.geometry
        geometry_valid = bool(
            geometries.notna().all()
            and geometries.is_valid.all()
            and (~geometries.is_empty).all()
        )
        if not geometry_valid:
            return SpatialValidation(role, len(frame), False, False, reason="invalid_geometry")
        target = getattr(location, "geometry", None)
        target = shape(target) if isinstance(target, dict) else target
        if target is None or target.is_empty or not target.is_valid:
            return SpatialValidation(role, len(frame), geometry_valid, False, reason="location_geometry_unavailable")
        if role in {"school", "primary_school", "university", "hospital", "park", "poi"}:
            inside = geometries.apply(lambda value: target.covers(value))
            spatial_valid = bool(inside.all())
            reason = None if spatial_valid else "features_outside_location"
            return SpatialValidation(
                role,
                len(frame),
                geometry_valid,
                spatial_valid,
                reason=reason,
            )
        if role in {"road", "river"}:
            intersects = geometries.apply(lambda value: value.intersects(target))
            clipped_frame = frame.loc[intersects].copy()
            if not clipped_frame.empty:
                clipped_frame["geometry"] = clipped_frame.geometry.intersection(target)
                clipped_frame = clipped_frame.loc[
                    clipped_frame.geometry.notna()
                    & ~clipped_frame.geometry.is_empty
                    & clipped_frame.geometry.is_valid
                ]
            spatial_valid = not clipped_frame.empty
            return SpatialValidation(
                role,
                len(clipped_frame),
                geometry_valid,
                spatial_valid,
                clipped=True,
                reason=None if spatial_valid else "no_features_in_location",
                clipped_frame=clipped_frame,
            )
        elif role == "boundary":
            ratios = geometries.apply(
                lambda value: value.intersection(target).area / target.area if target.area else 0.0
            )
            spatial_valid = bool(float(ratios.max()) >= 0.5)
        else:
            spatial_valid = bool(geometries.intersects(target).any())
        return SpatialValidation(role, len(frame), geometry_valid, spatial_valid)
    except Exception as exc:
        return SpatialValidation(
            role,
            int(getattr(source, "feature_count", 0) or 0),
            False,
            False,
            reason=str(exc),
        )


def _png_is_readable(path: Optional[Path]) -> bool:
    if not path or not path.is_file() or path.stat().st_size <= 0:
        return False
    try:
        from PIL import Image

        with Image.open(path) as image:
            image.verify()
        return True
    except (OSError, ValueError):
        return False


def finalize_execution(
    *,
    required_roles: Iterable[str],
    layers: Iterable[LayerValidation],
    png_path: Optional[Path],
    trace_id: Optional[str],
    map_version: Optional[int] = None,
    clarification_required: bool = False,
    execution_error_code: Optional[str] = None,
    execution_error_message: Optional[str] = None,
) -> ExecutionResult:
    """Validate deliverables and choose the only terminal execution status."""
    layer_values = list(layers)
    required: Set[str] = set(required_roles)
    valid_by_role = {
        layer.role: layer for layer in layer_values if layer.valid
    }
    missing = sorted(required - set(valid_by_role))
    invalid = sorted(
        layer.role for layer in layer_values if layer.role in required and not layer.valid
    )
    missing_or_invalid = sorted(set(missing + invalid))
    png_valid = _png_is_readable(png_path)
    available = sorted(valid_by_role)
    report = {
        "required_layers": sorted(required),
        "available_layers": available,
        "missing_layers": missing_or_invalid,
        "png_valid": png_valid,
        "layers": [asdict(layer) | {"valid": layer.valid} for layer in layer_values],
    }

    if clarification_required:
        return ExecutionResult(
            status="needs_clarification",
            map_version=map_version,
            completion_report=report,
            error_code="clarification_required",
            error_message="缺少继续制图所需的用户决策",
            trace_id=trace_id,
        )
    if not png_valid:
        return ExecutionResult(
            status="failed",
            map_version=map_version,
            completion_report=report,
            error_code=execution_error_code or "render_error",
            error_message=execution_error_message or "最终 PNG 不存在或无法读取",
            trace_id=trace_id,
        )
    if missing_or_invalid:
        status = "partial" if available else "failed"
        return ExecutionResult(
            status=status,
            map_version=map_version,
            completion_report=report,
            error_code=(
                execution_error_code
                if status == "failed" and execution_error_code
                else "resource_not_found" if status == "failed" else None
            ),
            error_message=(
                execution_error_message
                if status == "failed" and execution_error_message
                else "没有可交付的有效图层"
                if status == "failed"
                else f"缺少或校验失败的必需图层：{', '.join(missing_or_invalid)}"
            ),
            trace_id=trace_id,
        )
    if not available:
        return ExecutionResult(
            status="failed",
            map_version=map_version,
            completion_report=report,
            error_code=execution_error_code or "resource_not_found",
            error_message=execution_error_message or "没有可交付的有效图层",
            trace_id=trace_id,
        )
    return ExecutionResult(
        status="completed",
        map_version=map_version,
        completion_report=report,
        error_code=None,
        error_message=None,
        trace_id=trace_id,
    )
