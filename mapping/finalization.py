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
    png_valid = _png_is_readable(png_path)
    available = sorted(valid_by_role)
    report = {
        "required_layers": sorted(required),
        "available_layers": available,
        "missing_layers": sorted(set(missing + invalid)),
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
            error_code="render_error",
            error_message="最终 PNG 不存在或无法读取",
            trace_id=trace_id,
        )
    if missing:
        status = "partial" if available else "failed"
        return ExecutionResult(
            status=status,
            map_version=map_version,
            completion_report=report,
            error_code="resource_not_found" if status == "failed" else None,
            error_message=(
                "没有可交付的有效图层"
                if status == "failed"
                else f"缺少必需图层：{', '.join(sorted(set(missing + invalid)))}"
            ),
            trace_id=trace_id,
        )
    if not available:
        return ExecutionResult(
            status="failed",
            map_version=map_version,
            completion_report=report,
            error_code="resource_not_found",
            error_message="没有可交付的有效图层",
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
