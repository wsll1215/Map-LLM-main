"""Realtime map-building event publication.

This module is intentionally defensive: GIS agents can run in tests or scripts
without Django Channels installed/configured, so publication failures must never
break map generation.
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, Dict, Optional


MAX_PREVIEW_FILES_PER_REQUEST = 40


def publish_agent_map_event(
    *,
    session_id: Optional[str],
    iteration: int,
    tool_name: str,
    tool_input: Dict[str, Any],
    observation: str,
    map_state: Any = None,
    map_tools: Any = None,
) -> None:
    request_id = _request_id_from_session(session_id)
    if request_id is None:
        return

    preview = _save_matplotlib_preview(
        map_tools=map_tools,
        request_id=request_id,
        iteration=iteration,
        tool_name=tool_name,
    )

    payload = _build_payload(
        request_id=request_id,
        session_id=session_id,
        iteration=iteration,
        tool_name=tool_name,
        tool_input=tool_input or {},
        observation=observation,
        map_state=map_state,
        preview=preview,
    )
    publish_map_build_event(request_id, payload)


def publish_map_build_event(request_id: int, payload: Dict[str, Any]) -> str:
    """Publish a structured event to the SSE broker.

    The broker is Redis-backed when ``REDIS_URL`` is configured and falls back
    to an in-process queue for local development and tests.
    """
    try:
        from .sse_protocol import get_event_broker

        broker = get_event_broker()
        event_name = str(payload.get("type") or "message")
        return str(broker.publish_sync(str(request_id), event_name, payload) or "")
    except Exception:
        return ""


def _request_id_from_session(session_id: Optional[str]) -> Optional[int]:
    if not session_id:
        return None
    match = re.search(r"web_session_(\d+)", str(session_id))
    if not match:
        return None
    return int(match.group(1))


def _build_payload(
    *,
    request_id: int,
    session_id: Optional[str],
    iteration: int,
    tool_name: str,
    tool_input: Dict[str, Any],
    observation: str,
    map_state: Any,
    preview: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "type": _event_type_for_tool(tool_name),
        "request_id": request_id,
        "session_id": session_id,
        "iteration": iteration,
        "tool_name": tool_name,
        "tool_input": _summarize_tool_input(tool_input),
        "observation": str(observation)[:500],
        "created_at_ms": int(time.time() * 1000),
    }
    version_info = getattr(map_state, "version_info", None)
    map_version = getattr(version_info, "version", None) if version_info else None
    if map_version is not None:
        payload["map_version"] = map_version
        payload["snapshot_version"] = map_version

    if map_state is not None:
        payload["map"] = _map_summary(map_state)
        payload["view_state"] = _view_state(map_state, map_version)
        payload["elements"] = _elements_summary(map_state)

    target_layer = _target_layer_for_tool(map_state, tool_name, tool_input)
    if target_layer is not None:
        payload["layer"] = _layer_payload(target_layer, map_version)

    if tool_name == "map_save" and map_state is not None:
        payload["output_path"] = getattr(map_state, "output_path", None)

    if preview is not None:
        payload["preview"] = preview

    return payload


def _save_matplotlib_preview(
    *,
    map_tools: Any,
    request_id: int,
    iteration: int,
    tool_name: str,
) -> Optional[Dict[str, Any]]:
    """Save the current Matplotlib canvas as a browser-visible realtime preview."""
    try:
        if map_tools is None:
            return None

        figure = getattr(map_tools, "figure", None)
        map_state = getattr(map_tools, "current_map_state", None)
        if figure is None or map_state is None:
            return None

        redraw = getattr(map_tools, "_redraw_map", None)
        if callable(redraw) and getattr(map_tools, "ax", None) is not None:
            redraw()

        safe_tool_name = re.sub(r"[^a-zA-Z0-9_-]+", "_", str(tool_name or "tool")).strip("_") or "tool"
        timestamp_ms = int(time.time() * 1000)
        preview_dir = _generated_maps_dir() / "realtime_previews" / f"request_{request_id}"
        preview_dir.mkdir(parents=True, exist_ok=True)
        filename = f"step_{int(iteration):03d}_{safe_tool_name}_{timestamp_ms}.png"
        file_path = preview_dir / filename

        _save_figure_without_closing(figure, getattr(map_tools, "ax", None), file_path)
        _cleanup_preview_dir(preview_dir)

        return {
            "image_url": f"/generated_maps/realtime_previews/request_{request_id}/{filename}",
            "filename": filename,
            "iteration": iteration,
            "tool_name": tool_name,
            "created_at_ms": timestamp_ms,
        }
    except Exception as exc:
        return {
            "error": str(exc)[:300],
            "iteration": iteration,
            "tool_name": tool_name,
            "created_at_ms": int(time.time() * 1000),
        }


def _save_figure_without_closing(figure: Any, ax: Any, file_path: Path) -> None:
    """Save a Matplotlib figure using the same bbox strategy as final map_save."""
    figure.canvas.draw()
    renderer = figure.canvas.get_renderer()
    items_to_include = list(figure.get_children())
    if ax is not None and ax.get_legend():
        items_to_include.append(ax.get_legend())

    total_bbox = None
    try:
        from matplotlib.transforms import Bbox

        for item in items_to_include:
            if not hasattr(item, "get_window_extent"):
                continue
            bbox_display = item.get_window_extent(renderer=renderer)
            bbox_inches = bbox_display.transformed(figure.dpi_scale_trans.inverted())
            total_bbox = bbox_inches if total_bbox is None else Bbox.union([total_bbox, bbox_inches])
    except Exception:
        total_bbox = None

    save_kwargs = {
        "dpi": 180,
        "format": "png",
        "facecolor": "white",
        "edgecolor": "none",
    }
    if total_bbox is not None:
        save_kwargs["bbox_inches"] = total_bbox.padded(0.1)

    figure.savefig(str(file_path), **save_kwargs)


def _cleanup_preview_dir(preview_dir: Path) -> None:
    try:
        files = sorted(preview_dir.glob("*.png"), key=lambda item: item.stat().st_mtime, reverse=True)
        for old_file in files[MAX_PREVIEW_FILES_PER_REQUEST:]:
            old_file.unlink(missing_ok=True)
    except Exception:
        return


def _generated_maps_dir() -> Path:
    try:
        from django.conf import settings

        if getattr(settings, "configured", False) and getattr(settings, "GENERATED_MAPS_DIR", None):
            return Path(settings.GENERATED_MAPS_DIR)
    except Exception:
        pass

    return Path.cwd() / "generated_maps"


def _event_type_for_tool(tool_name: str) -> str:
    return {
        "init_map": "map_initialized",
        "add_layer": "layer_upserted",
        "style_layer": "layer_upserted",
        "map_save": "map_element_updated",
        "add_scalebar": "map_element_updated",
        "remove_scalebar": "map_element_updated",
        "add_compass": "map_element_updated",
        "remove_compass": "map_element_updated",
        "add_annotation": "map_element_updated",
        "modify_element": "map_element_updated",
        "clear_annotations": "map_element_updated",
    }.get(tool_name, "tool_finished")


def _map_summary(map_state: Any) -> Dict[str, Any]:
    config = getattr(map_state, "config", None)
    return {
        "title": getattr(config, "title", None),
        "extent": getattr(config, "extent", None),
        "crs": getattr(config, "crs", None),
        "background_color": getattr(config, "background_color", "white"),
        "layer_count": len(getattr(map_state, "layers", []) or []),
        "output_path": getattr(map_state, "output_path", None),
    }


def _view_state(map_state: Any, map_version: Optional[int] = None) -> Dict[str, Any]:
    """Build a versioned metadata-only browser-preview state."""
    return {
        "map": _map_summary(map_state),
        "map_version": map_version,
        "layers": [
            _layer_payload(layer, map_version)
            for layer in (getattr(map_state, "layers", []) or [])
        ],
        "legend_items": [_dump_model(item) for item in (getattr(map_state, "legend_items", []) or [])],
        "legends": [_dump_model(legend) for legend in (getattr(map_state, "legends", []) or [])],
        "annotations": [_dump_model(annotation) for annotation in (getattr(map_state, "annotations", []) or [])],
        "elements": _elements_summary(map_state),
        "output_path": getattr(map_state, "output_path", None),
    }


def _elements_summary(map_state: Any) -> Dict[str, Any]:
    return {
        "scalebar": getattr(map_state, "scalebar", None),
        "compass": getattr(map_state, "compass", None),
    }


def _target_layer_for_tool(map_state: Any, tool_name: str, tool_input: Dict[str, Any]) -> Any:
    if map_state is None:
        return None

    layers = getattr(map_state, "layers", []) or []
    if not layers:
        return None

    layer_name = tool_input.get("layer_name") or tool_input.get("name")
    if not layer_name and tool_name == "add_layer":
        return layers[-1]

    for layer in layers:
        if getattr(layer, "name", None) == layer_name:
            return layer
    return layers[-1] if tool_name in {"add_layer", "style_layer"} else None


def _layer_payload(layer: Any, version: Optional[int] = None) -> Dict[str, Any]:
    style = getattr(layer, "style", None)
    style_payload = style.model_dump() if hasattr(style, "model_dump") else dict(style or {})
    return {
        "id": getattr(layer, "layer_id", None),
        "name": getattr(layer, "name", None),
        "geometry_type": _enum_value(getattr(layer, "geometry_type", None)),
        "visible": getattr(layer, "visible", True),
        "z_order": getattr(layer, "z_order", 0),
        "data_source": getattr(layer, "data_source", None),
        "version": version,
        "data_hash": getattr(layer, "data_hash", None),
        "feature_count": getattr(layer, "feature_count", 0),
        "extent": getattr(layer, "extent", None),
        "render_mode": _effective_render_mode(layer),
        "data_url": getattr(layer, "data_url", None),
        "style": style_payload,
    }


def _effective_render_mode(layer: Any) -> str:
    explicit = getattr(layer, "render_mode", "geojson")
    if explicit in {"mvt", "pmtiles"}:
        return explicit
    feature_count = getattr(layer, "feature_count", 0) or 0
    try:
        from django.conf import settings

        geojson_limit = getattr(settings, "MAP_GEOJSON_LIMIT", 5000)
        worker_limit = getattr(settings, "MAP_WORKER_LIMIT", 30000)
        mvt_enabled = getattr(settings, "MAP_MVT_ENABLED", False)
    except Exception:
        geojson_limit, worker_limit, mvt_enabled = 5000, 30000, False
    if feature_count > worker_limit:
        return "mvt" if mvt_enabled else "geojson-worker"
    return "geojson-worker" if feature_count > geojson_limit else "geojson"


def _dump_model(value: Any) -> Dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, dict):
        return dict(value)
    result = {}
    for key in ("label", "type", "style", "title", "position", "items", "font_size",
                "background_color", "border", "annotation_id", "text", "color",
                "rotation", "alignment"):
        if hasattr(value, key):
            result[key] = getattr(value, key)
    return result


def _summarize_tool_input(tool_input: Dict[str, Any]) -> Dict[str, Any]:
    summary = {}
    for key, value in tool_input.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            summary[key] = value
        elif isinstance(value, (list, tuple)) and len(value) <= 10:
            summary[key] = value
        elif isinstance(value, dict):
            summary[key] = {str(k): str(v)[:80] for k, v in list(value.items())[:10]}
        else:
            summary[key] = str(value)[:120]
    return summary


def _enum_value(value: Any) -> Any:
    return getattr(value, "value", value)
