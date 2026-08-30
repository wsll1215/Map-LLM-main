"""Runtime-only readers backed by DatasetFeature/PostGIS."""

from __future__ import annotations

import json
import hashlib
import math
from pathlib import Path
from typing import Optional, Tuple

from django.contrib.gis.db.models.functions import Intersection
from django.contrib.gis.geos import GEOSGeometry, Polygon
from django.db import DatabaseError, connection

from .models import Dataset, DatasetFeature


class DatasetReadError(RuntimeError):
    def __init__(self, message: str, *, code: str = "resource_not_found"):
        super().__init__(message)
        self.error_code = code


def _get_dataset(dataset_id: str):
    if connection.vendor != "postgresql":
        raise DatasetReadError(
            "运行时空间数据必须来自 PostgreSQL/PostGIS",
            code="local_catalog_unavailable",
        )
    try:
        return Dataset.objects.get(
            dataset_id=dataset_id,
            status=Dataset.STATUS_AVAILABLE,
        )
    except Dataset.DoesNotExist as exc:
        raise DatasetReadError(
            f"数据集未注册或不可用: {dataset_id}", code="dataset_not_registered"
        ) from exc
    except Exception as exc:
        raise DatasetReadError(
            "PostGIS 数据目录暂时不可用", code="local_catalog_unavailable"
        ) from exc


def _validate_bbox(bbox: Optional[Tuple[float, float, float, float]]):
    if bbox is None:
        return None
    try:
        values = tuple(float(value) for value in bbox)
    except (TypeError, ValueError) as exc:
        raise DatasetReadError(
            "bbox 必须是有效的 minx,miny,maxx,maxy", code="validation_error"
        ) from exc
    if (
        len(values) != 4
        or not all(math.isfinite(value) for value in values)
        or values[0] >= values[2]
        or values[1] >= values[3]
    ):
        raise DatasetReadError("bbox 必须是有效的 minx,miny,maxx,maxy", code="validation_error")
    return values


def _bbox_geometry(bbox: Tuple[float, float, float, float]) -> Polygon:
    """Build a PostGIS-compatible WGS84 bbox geometry."""
    geometry = Polygon.from_bbox(bbox)
    geometry.srid = 4326
    return geometry


def _validate_tile_coordinates(z: int, x: int, y: int) -> Tuple[int, int, int]:
    try:
        zoom, tile_x, tile_y = int(z), int(x), int(y)
    except (TypeError, ValueError) as exc:
        raise DatasetReadError("瓦片坐标必须是整数", code="validation_error") from exc
    if zoom < 0 or zoom > 22:
        raise DatasetReadError("z 必须在 0 到 22 之间", code="validation_error")
    limit = 2**zoom
    if tile_x < 0 or tile_x >= limit or tile_y < 0 or tile_y >= limit:
        raise DatasetReadError("x 或 y 超出当前缩放级别范围", code="validation_error")
    return zoom, tile_x, tile_y


def read_dataset_features(
    dataset_id: str,
    bbox: Optional[Tuple[float, float, float, float]] = None,
    limit: Optional[int] = None,
    clip_geometry: Optional[dict] = None,
):
    """Return a GeoDataFrame from normalized PostGIS features only."""
    dataset = _get_dataset(dataset_id)
    bbox = _validate_bbox(bbox)
    if limit is not None and (int(limit) < 1 or int(limit) > 100000):
        raise DatasetReadError("limit 必须在 1 到 100000 之间", code="validation_error")

    query = DatasetFeature.objects.filter(dataset=dataset)
    if bbox is not None:
        query = query.filter(geom__intersects=_bbox_geometry(bbox))
    clip_shape = None
    if clip_geometry is not None:
        try:
            clip_shape = GEOSGeometry(json.dumps(clip_geometry), srid=4326)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise DatasetReadError(
                "scope_geometry 必须是合法的 GeoJSON geometry",
                code="validation_error",
            ) from exc
        if clip_shape.empty or not clip_shape.valid:
            raise DatasetReadError(
                "scope_geometry 必须是非空且有效的 geometry",
                code="validation_error",
            )
        query = query.filter(geom__intersects=clip_shape).annotate(
            _scoped_geom=Intersection("geom", clip_shape)
        )
    query = query.only("source_fid", "geom", "properties")
    if limit is not None:
        query = query[: int(limit)]

    features = []
    for item in query:
        features.append(
            {
                "type": "Feature",
                "id": item.source_fid,
                "geometry": json.loads(
                    getattr(item, "_scoped_geom", item.geom).geojson
                ),
                "properties": item.properties or {},
            }
        )
    import geopandas as gpd

    frame = gpd.GeoDataFrame.from_features(features, crs="EPSG:4326")
    if features and "id" in frame.columns:
        frame.index = [feature["id"] for feature in features]
    return frame


def register_geodataframe_dataset(
    frame,
    *,
    dataset_id: str,
    name: str,
    source_type: str,
    role: str,
    local_path: Optional[str] = None,
    source_url: Optional[str] = None,
    provider: Optional[str] = None,
    attribution: Optional[str] = None,
) -> str:
    """Normalize an explicit import into DatasetFeature rows.

    File readers are intentionally confined to this import boundary. Every
    subsequent map operation reads the normalized Dataset through PostGIS.
    """
    if connection.vendor != "postgresql":
        raise DatasetReadError(
            "数据导入需要 PostgreSQL/PostGIS 主数据库",
            code="local_catalog_unavailable",
        )
    if source_type not in {
        Dataset.SOURCE_LOCAL,
        Dataset.SOURCE_REMOTE,
        Dataset.SOURCE_UPLOAD,
    }:
        raise DatasetReadError("source_type 无效", code="validation_error")
    if frame is None or getattr(frame, "crs", None) is None:
        raise DatasetReadError("数据集没有 CRS，无法导入", code="validation_error")

    try:
        normalized = frame.to_crs("EPSG:4326")
        rows = []
        bounds = []
        for index, record in normalized.iterrows():
            geometry = record.geometry
            if geometry is None or geometry.is_empty or not geometry.is_valid:
                continue
            properties = {
                str(key): _json_safe_value(value)
                for key, value in record.drop(labels=["geometry"], errors="ignore").items()
            }
            json.dumps(properties, allow_nan=False)
            rows.append((index, geometry, properties))
            bounds.append(geometry.bounds)
        if not rows:
            raise DatasetReadError("数据集没有有效几何", code="render_error")
        minx = min(item[0] for item in bounds)
        miny = min(item[1] for item in bounds)
        maxx = max(item[2] for item in bounds)
        maxy = max(item[3] for item in bounds)
        from django.contrib.gis.geos import GEOSGeometry
        from django.db import transaction

        dataset, _ = Dataset.objects.update_or_create(
            dataset_id=str(dataset_id),
            defaults={
                "name": name,
                "aliases": [role],
                "source_type": source_type,
                "source_url": source_url or "",
                "local_path": local_path or "",
                "geometry_type": rows[0][1].geom_type.lower(),
                "crs": "EPSG:4326",
                "bbox": [minx, miny, maxx, maxy],
                "feature_count": len(rows),
                "status": Dataset.STATUS_PENDING,
                "metadata": {
                    "role": role,
                    "provider": provider or source_type,
                    "attribution": attribution,
                    "cache_path": local_path,
                },
            },
        )
        feature_rows = [
            DatasetFeature(
                dataset=dataset,
                source_fid=str(index),
                geom=GEOSGeometry(geometry.wkt, srid=4326),
                properties=properties,
            )
            for index, geometry, properties in rows
        ]
        with transaction.atomic():
            DatasetFeature.objects.filter(dataset=dataset).delete()
            DatasetFeature.objects.bulk_create(feature_rows, batch_size=1000)
            dataset.feature_count = len(feature_rows)
            dataset.status = Dataset.STATUS_AVAILABLE
            dataset.save(update_fields=["feature_count", "status", "updated_at"])
        return str(dataset.dataset_id)
    except DatasetReadError:
        raise
    except DatabaseError as exc:
        raise DatasetReadError(
            "PostGIS 数据集导入失败，数据库暂时不可用",
            code="local_catalog_unavailable",
        ) from exc
    except (TypeError, ValueError, OverflowError) as exc:
        raise DatasetReadError(str(exc), code="render_error") from exc


def _json_safe_value(value):
    if value is None:
        return None
    if hasattr(value, "item"):
        return _json_safe_value(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {str(key): _json_safe_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe_value(item) for item in value]
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def read_dataset_tile(
    dataset_id: str,
    z: int,
    x: int,
    y: int,
    clip_geometry: Optional[dict] = None,
) -> bytes:
    """Encode an MVT tile in PostGIS without materializing the full dataset."""
    _get_dataset(dataset_id)
    z, x, y = _validate_tile_coordinates(z, x, y)
    scope_select = "geom"
    scope_filter = ""
    select_params = []
    filter_params = []
    if clip_geometry is not None:
        try:
            clip_shape = GEOSGeometry(json.dumps(clip_geometry), srid=4326)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise DatasetReadError(
                "scope_geometry 必须是合法的 GeoJSON geometry",
                code="validation_error",
            ) from exc
        if clip_shape.empty or not clip_shape.valid:
            raise DatasetReadError(
                "scope_geometry 必须是非空且有效的 geometry",
                code="validation_error",
            )
        scope_geojson = json.dumps(clip_geometry, separators=(",", ":"))
        scope_select = "ST_Intersection(geom, ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326))"
        scope_filter = "AND ST_Intersects(geom, ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326))"
        select_params = [scope_geojson]
        filter_params = [scope_geojson]
    query = f"""
        WITH tile AS (
            SELECT
                source_fid AS feature_id,
                properties,
                ST_AsMVTGeom(
                    ST_Transform({scope_select}, 3857),
                    ST_TileEnvelope(%s, %s, %s),
                    4096,
                    64,
                    true
                ) AS geom
            FROM mapping_datasetfeature
            WHERE dataset_id = (
                SELECT id FROM mapping_dataset WHERE dataset_id = %s
            )
              AND geom && ST_Transform(ST_TileEnvelope(%s, %s, %s), 4326)
              {scope_filter}
        )
        SELECT COALESCE(ST_AsMVT(tile, %s, 4096, 'geom'), ''::bytea)
        FROM tile
        WHERE geom IS NOT NULL
    """
    layer_name = str(dataset_id)[:50] or "layer"
    parameters = select_params + [z, x, y, dataset_id, z, x, y] + filter_params
    with connection.cursor() as cursor:
        cursor.execute(query, parameters + [layer_name])
        value = cursor.fetchone()[0]
    return bytes(value or b"")


def register_geojson_dataset(
    path: Path,
    *,
    role: str,
    provider: str,
    source_url: Optional[str],
    attribution: str,
) -> Optional[str]:
    """Register a downloaded GeoJSON and normalize it into PostGIS."""
    if connection.vendor != "postgresql":
        raise DatasetReadError(
            "远程数据已下载，但运行时数据库不是 PostgreSQL/PostGIS，无法注册",
            code="local_catalog_unavailable",
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        raw_features = payload.get("features", [])
        if not isinstance(raw_features, list) or not raw_features:
            raise DatasetReadError("远程数据为空", code="resource_not_found")
        from django.contrib.gis.geos import GEOSGeometry
        from django.db import transaction
        from shapely.geometry import shape

        dataset_id = "remote-" + hashlib.sha1(
            f"{role}:{path.resolve()}".encode("utf-8")
        ).hexdigest()[:24]
        geometries = []
        bounds = []
        for index, feature in enumerate(raw_features):
            geometry = feature.get("geometry") if isinstance(feature, dict) else None
            if not geometry:
                continue
            value = shape(geometry)
            if value.is_empty or not value.is_valid:
                continue
            geometries.append((index, feature, value))
            bounds.append(value.bounds)
        if not geometries:
            raise DatasetReadError("远程数据没有有效几何", code="render_error")
        minx = min(item[0] for item in bounds)
        miny = min(item[1] for item in bounds)
        maxx = max(item[2] for item in bounds)
        maxy = max(item[3] for item in bounds)
        geometry_type = geometries[0][2].geom_type.lower()
        dataset, _ = Dataset.objects.update_or_create(
            dataset_id=dataset_id,
            defaults={
                "name": f"{role}:{path.stem}",
                "aliases": [role],
                "source_type": Dataset.SOURCE_REMOTE,
                "source_url": source_url or "",
                "local_path": path.as_posix(),
                "geometry_type": geometry_type,
                "crs": "EPSG:4326",
                "bbox": [minx, miny, maxx, maxy],
                "feature_count": len(geometries),
                "status": Dataset.STATUS_PENDING,
                "metadata": {
                    "role": role,
                    "provider": provider,
                    "attribution": attribution,
                    "cache_path": path.as_posix(),
                },
            },
        )
        feature_rows = []
        for index, feature, value in geometries:
            # GEOSGeometry avoids a GDAL dependency during the normalized
            # PostGIS import path; the source geometry has already been
            # validated by Shapely above.
            geom = GEOSGeometry(value.wkt, srid=4326)
            feature_rows.append(
                DatasetFeature(
                    dataset=dataset,
                    source_fid=str(feature.get("id", index)),
                    geom=geom,
                    properties=feature.get("properties") or {},
                )
            )
        with transaction.atomic():
            DatasetFeature.objects.filter(dataset=dataset).delete()
            DatasetFeature.objects.bulk_create(feature_rows, batch_size=1000)
            dataset.status = Dataset.STATUS_AVAILABLE
            dataset.save(update_fields=["status", "updated_at"])
        return dataset_id
    except DatasetReadError:
        raise
    except DatabaseError as exc:
        raise DatasetReadError(
            "PostGIS 数据集注册失败，数据库暂时不可用",
            code="local_catalog_unavailable",
        ) from exc
    except (OSError, UnicodeDecodeError, TypeError, ValueError, KeyError) as exc:
        raise DatasetReadError(str(exc), code="render_error") from exc
