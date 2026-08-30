"""Backend-owned location resolution and source acquisition coordination."""

from __future__ import annotations

import json
from pathlib import Path
from dataclasses import replace
from types import SimpleNamespace
from typing import Any, Callable, Dict, Mapping, Optional, Tuple

from .catalog import DjangoDatasetCatalog
from .planner import (
    Intent,
    LocationResolution,
    PlannedSource,
    SourcePlan,
    plan_sources,
    resolve_local_location,
)
from .remote import (
    RemoteDataSourceError,
    extract_remote_poi_request,
    extract_remote_poi_query,
    fetch_remote_boundary,
    fetch_remote_pois,
    fetch_remote_named_poi,
    fetch_remote_roads,
    fetch_remote_waterways,
    resolve_location,
)


REMOTE_PROVIDER_BY_ROLE = {
    "boundary": "OpenStreetMap/Nominatim",
    "road": "OpenStreetMap/Overpass",
    "river": "OpenStreetMap/Overpass",
    "university": "OpenStreetMap/Overpass",
    "primary_school": "OpenStreetMap/Overpass",
    "school": "OpenStreetMap/Overpass",
    "hospital": "OpenStreetMap/Overpass",
    "park": "OpenStreetMap/Overpass",
}
REMOTE_URL_BY_ROLE = {
    "boundary": "https://nominatim.openstreetmap.org/search",
    "road": "https://overpass-api.de/api/interpreter",
    "river": "https://overpass-api.de/api/interpreter",
    "university": "https://overpass-api.de/api/interpreter",
    "primary_school": "https://overpass-api.de/api/interpreter",
    "school": "https://overpass-api.de/api/interpreter",
    "hospital": "https://overpass-api.de/api/interpreter",
    "park": "https://overpass-api.de/api/interpreter",
}
POI_CATEGORY_BY_ROLE = {
    "university": "universities",
    "primary_school": "primary_schools",
    "school": "schools",
    "hospital": "hospitals",
    "park": "parks",
}


def _path_metadata(path: Path, *, role: str, bbox: Tuple[float, ...]) -> Tuple[int, Tuple[float, ...]]:
    """Read only the downloaded artifact metadata; runtime feature reads come later."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        features = payload.get("features", [])
        count = len(features) if isinstance(features, list) else 0
        return count, bbox
    except (OSError, UnicodeDecodeError, TypeError, ValueError):
        return 0, bbox


def _remote_source(role: str, path: Optional[Path], bbox: Tuple[float, ...]) -> Optional[PlannedSource]:
    if not path:
        return None
    count, resolved_bbox = _path_metadata(path, role=role, bbox=bbox)
    if count <= 0:
        return None
    from mapping.dataset_reader import register_geojson_dataset

    dataset_id = register_geojson_dataset(
        path,
        role=role,
        provider=REMOTE_PROVIDER_BY_ROLE.get(role, "OpenStreetMap"),
        source_url=REMOTE_URL_BY_ROLE.get(role),
        attribution="© OpenStreetMap contributors",
    )
    if not dataset_id:
        return PlannedSource(
            role=role,
            source_type="remote",
            provider=REMOTE_PROVIDER_BY_ROLE.get(role, "OpenStreetMap"),
            source_url=REMOTE_URL_BY_ROLE.get(role),
            cache_path=path.as_posix(),
            bbox=resolved_bbox,
            feature_count=count,
            status="failed",
            spatial_valid=False,
            geometry_valid=None,
            error_code="local_catalog_unavailable",
            retryable=True,
            next_action="retry_dataset_registration",
            metadata={"attribution": "© OpenStreetMap contributors", "role": role},
        )
    return PlannedSource(
        role=role,
        source_type="remote",
        provider=REMOTE_PROVIDER_BY_ROLE.get(role, "OpenStreetMap"),
        source_url=REMOTE_URL_BY_ROLE.get(role),
        cache_path=path.as_posix(),
        dataset_id=dataset_id,
        bbox=resolved_bbox,
        feature_count=count,
        status="available",
        spatial_valid=True,
        geometry_valid=True,
        metadata={"attribution": "© OpenStreetMap contributors", "role": role},
    )


def _validate_source(source: PlannedSource, location: LocationResolution) -> PlannedSource:
    """Attach geometry and place evidence before a source becomes available."""
    try:
        frame = None
        if source.dataset_id:
            from mapping.dataset_reader import read_dataset_features

            frame = read_dataset_features(source.dataset_id, limit=100000)
        # ``cache_path`` is provenance only. Runtime validation must use the
        # normalized DatasetFeature rows just like runtime rendering does.
        evidence = __import__("mapping.finalization", fromlist=["validate_source_spatial"]).validate_source_spatial(
            SimpleNamespace(
                gdf=frame,
                feature_count=source.feature_count,
                data_source_meta={"dataset_id": source.dataset_id} if source.dataset_id else {},
            ),
            location,
            source.role,
        )
    except Exception as exc:
        error_code = getattr(exc, "error_code", None) or "spatial_validation_error"
        retryable = bool(getattr(exc, "retryable", False))
        return replace(
            source,
            status="failed",
            geometry_valid=False,
            spatial_valid=False,
            error_code=error_code,
            retryable=retryable,
            next_action="retry_dataset_read" if retryable else "choose_another_source",
            metadata={**dict(source.metadata), "validation_error": str(exc)[:200]},
        )
    if not evidence.geometry_valid or not evidence.spatial_valid:
        return replace(
            source,
            status="failed",
            geometry_valid=evidence.geometry_valid,
            spatial_valid=evidence.spatial_valid,
            error_code="spatial_mismatch" if not evidence.spatial_valid else "invalid_geometry",
            retryable=False,
            next_action="choose_another_source",
            metadata={**dict(source.metadata), "validation_reason": evidence.reason},
        )
    scope_geometry = getattr(location, "geometry", None)
    if scope_geometry is not None and not isinstance(scope_geometry, dict):
        try:
            from shapely.geometry import mapping

            scope_geometry = mapping(scope_geometry)
        except (ImportError, TypeError, ValueError):
            scope_geometry = None
    return replace(
        source,
        feature_count=evidence.feature_count,
        geometry_valid=True,
        spatial_valid=True,
        metadata={
            **dict(source.metadata),
            "clipped": evidence.clipped,
            "scope_geometry": scope_geometry,
        },
    )
def _failure(role: str, location: Optional[LocationResolution], error: Exception) -> Mapping[str, Any]:
    return {
        "role": role,
        "provider": REMOTE_PROVIDER_BY_ROLE.get(role, "OpenStreetMap"),
        "source_url": REMOTE_URL_BY_ROLE.get(role),
        "bbox": tuple(location.bbox or ()) if location and location.bbox else (),
        "error_code": getattr(error, "error_code", "internal_error"),
        "retryable": bool(getattr(error, "retryable", False)),
        "next_action": "retry_remote_source" if getattr(error, "retryable", False) else "inspect_source_plan",
        "message": str(error),
    }


def _run_data_fetch_with_trace(
    *,
    session_id: Optional[str],
    role: str,
    place: str,
    bbox: Tuple[float, float, float, float],
    operation: Callable[[], Optional[PlannedSource]],
) -> Optional[PlannedSource]:
    """Run one source acquisition and close one data-fetch span."""
    span = None
    trace_module = None
    try:
        from mapping import trace as trace_module

        run = trace_module.run_for_session(session_id)
        if run:
            span = trace_module.start_trace_event(
                run=run,
                event_type="data_fetch",
                phase="data_source",
                actor="system",
                summary=f"获取{role}数据",
                input_data={"role": role, "place": place, "bbox": list(bbox)},
                attributes={"source_type": "remote"},
            )
            trace_module.publish_trace_lifecycle(span, "data_fetch_started")
    except Exception:
        span = None
        trace_module = None

    try:
        source = operation()
    except Exception as exc:
        if span is not None and trace_module is not None:
            try:
                span = trace_module.finish_trace_event(
                    span,
                    status="error",
                    output_data={},
                    error={
                        "error_code": getattr(exc, "error_code", "internal_error"),
                        "retryable": bool(getattr(exc, "retryable", False)),
                        "next_action": (
                            "retry_remote_source"
                            if bool(getattr(exc, "retryable", False))
                            else "inspect_source_plan"
                        ),
                    },
                )
                trace_module.publish_trace_lifecycle(span, "data_fetch_finished")
                trace_module.publish_trace_event(span)
            except Exception:
                pass
        raise

    if span is not None and trace_module is not None:
        try:
            span = trace_module.finish_trace_event(
                span,
                status="success" if source is not None else "warning",
                output_data={
                    "source_type": source.source_type if source else "remote",
                    "provider": source.provider if source else None,
                    "dataset_id": source.dataset_id if source else None,
                    "cache_path": source.cache_path if source else None,
                    "feature_count": source.feature_count if source else 0,
                },
                attributes={
                    "source_type": source.source_type if source else "remote",
                    "provider": source.provider if source else None,
                    "feature_count": source.feature_count if source else 0,
                    "retry_count": max(len(source.attempts) - 1, 0) if source else 0,
                },
                error=(
                    {
                        "error_code": "resource_not_found",
                        "retryable": False,
                        "next_action": "choose_another_source",
                    }
                    if source is None
                    else None
                ),
            )
            trace_module.publish_trace_lifecycle(span, "data_fetch_finished")
            trace_module.publish_trace_event(span)
        except Exception:
            pass
    return source


def _fetch_for_role(
    role: str,
    place: str,
    bbox: Tuple[float, float, float, float],
    *,
    request_text: str,
) -> Optional[Path]:
    if role == "boundary":
        return fetch_remote_boundary(place)
    if role == "road":
        return fetch_remote_roads(place, list(bbox))
    if role == "river":
        return fetch_remote_waterways(place, list(bbox))
    category = POI_CATEGORY_BY_ROLE.get(role)
    if category:
        poi = extract_remote_poi_request(request_text)
        named = extract_remote_poi_query(request_text) is None and poi and poi.get("place")
        if named and poi and poi.get("place"):
            return fetch_remote_named_poi(str(poi["place"]), category=category)
        return fetch_remote_pois(place, list(bbox), category=category)
    raise RemoteDataSourceError(
        f"未注册远程数据源角色: {role}", code="resource_not_found", retryable=False
    )


def build_source_plan(
    intent: Intent,
    *,
    request_text: str = "",
    catalog: Any = None,
    location: Optional[LocationResolution] = None,
    session_id: Optional[str] = None,
    location_resolver: Callable[[str], LocationResolution] = resolve_location,
    fetcher: Callable[..., Optional[Path]] = _fetch_for_role,
) -> SourcePlan:
    """Resolve a place, choose verified local data, then acquire remote fallbacks.

    The LLM supplies only ``Intent``.  All paths, URLs, bboxes and source
    status in the returned plan are produced by this backend function.
    """
    catalog = catalog if catalog is not None else DjangoDatasetCatalog()
    place = intent.location.text
    if location is None and place:
        location = resolve_local_location(place, catalog)
        if location is None:
            location = location_resolver(place)

    if place and (location is None or location.error_code or not location.bbox):
        error = location.error_code if location else "location_not_resolved"
        return plan_sources(
            intent,
            location=LocationResolution(
                text=place,
                precision=intent.location.precision or "unknown",
                bbox=None,
                geometry=None,
                provider=getattr(location, "provider", "unknown"),
                confidence=0.0,
                error_code=error,
                retryable=bool(getattr(location, "retryable", False)),
                next_action=getattr(location, "next_action", None)
                or ("provide_location" if error == "location_not_resolved" else None),
                status_code=getattr(location, "status_code", None),
            ),
            catalog=catalog,
            remote_errors={
                layer.role: {
                    "error_code": error,
                    "retryable": bool(getattr(location, "retryable", False)),
                    "next_action": getattr(location, "next_action", None)
                    or ("provide_location" if error == "location_not_resolved" else None),
                    "status_code": getattr(location, "status_code", None),
                    "provider": getattr(location, "provider", "unknown"),
                }
                for layer in intent.layers
            },
        )

    if not place and intent.layers:
        return plan_sources(intent, location=None, catalog=catalog)

    local_plan = plan_sources(intent, location=location, catalog=catalog)
    catalog_error = getattr(catalog, "last_error", None)
    if catalog_error:
        return plan_sources(
            intent,
            location=location,
            catalog=None,
            remote_errors={layer.role: catalog_error for layer in intent.layers},
        )

    # A Django catalog only exposes metadata during planning. Validate each
    # selected DatasetFeature-backed source before allowing it to remain local.
    # Lightweight test catalogs and explicit import callers retain the older
    # planner-only contract; production catalog entries always have a dataset_id.
    validated_local: Dict[str, PlannedSource] = {}
    if isinstance(catalog, DjangoDatasetCatalog):
        for source in local_plan.layers:
            if source.source_type != "local" or source.status != "available":
                continue
            if not source.dataset_id:
                continue
            checked = _validate_source(source, location)
            if checked.status == "available":
                validated_local[source.role] = checked
            local_plan = replace(
                local_plan,
                layers=tuple(
                    checked if item.role == source.role else item
                    for item in local_plan.layers
                ),
            )
        # Rebuild from the validated local decisions. This prevents the final
        # planner pass from reselecting a source using bbox-only evidence.
        local_plan = plan_sources(
            intent,
            location=location,
            catalog=None,
            remote_sources=validated_local,
        )
    missing_roles = {
        layer.role for layer in local_plan.layers if layer.status != "available"
    }
    remote_sources: Dict[str, PlannedSource] = {}
    remote_errors: Dict[str, Mapping[str, Any]] = {}
    bbox = tuple(location.bbox) if location and location.bbox else ()
    for role in sorted(missing_roles):
        if len(bbox) != 4:
            remote_errors[role] = {
                "error_code": "location_not_resolved",
                "retryable": False,
                "next_action": "provide_location",
            }
            continue
        try:
            source = _run_data_fetch_with_trace(
                session_id=session_id,
                role=role,
                place=place,
                bbox=bbox,
                operation=lambda: _remote_source(
                    role,
                    fetcher(role, place, bbox, request_text=request_text),
                    bbox,
                ),
            )
            if source is not None:
                source = _validate_source(source, location)
            if source is None:
                remote_errors[role] = {
                    "error_code": "resource_not_found",
                    "retryable": False,
                    "next_action": "choose_another_source",
                }
            elif source.status != "available":
                remote_errors[role] = {
                    "error_code": source.error_code or "spatial_mismatch",
                    "retryable": source.retryable,
                    "next_action": source.next_action or "choose_another_source",
                }
            else:
                remote_sources[role] = source
        except Exception as exc:
            remote_errors[role] = _failure(role, location, exc)

    # Do not scan the catalog again here. A second bbox-only scan could
    # resurrect a Dataset that failed geometry or spatial validation above.
    selected_sources = {
        source.role: source
        for source in local_plan.layers
        if source.status == "available"
    }
    selected_sources.update(remote_sources)
    return plan_sources(
        intent,
        location=location,
        catalog=None,
        remote_sources=selected_sources,
        remote_errors=remote_errors,
    )
