"""Small, deterministic MVT encoder used by the tile-generation worker."""

from typing import Any

import geopandas as gpd
import mercantile
from shapely.geometry import mapping


def encode_tile(gdf: gpd.GeoDataFrame, layer_name: str, zoom: int, x: int, y: int) -> bytes:
    """Encode one EPSG:3857 tile; callers must cache the returned bytes."""
    if not 0 <= zoom <= 30 or x < 0 or y < 0 or x >= 2**zoom or y >= 2**zoom:
        raise ValueError("invalid tile coordinates")
    if gdf.crs is None:
        raise ValueError("MVT source data must declare a CRS")

    import mapbox_vector_tile

    projected = gdf.to_crs("EPSG:3857")
    tile_bounds = mercantile.xy_bounds(x, y, zoom)
    bounds = (tile_bounds.left, tile_bounds.bottom, tile_bounds.right, tile_bounds.top)
    clipped = projected.cx[bounds[0] : bounds[2], bounds[1] : bounds[3]]
    features = []
    for feature_id, row in clipped.iterrows():
        geometry = row.geometry
        if geometry is None or geometry.is_empty:
            continue
        properties = {
            str(key): _json_value(value)
            for key, value in row.drop(labels="geometry").to_dict().items()
            if _json_value(value) is not None
        }
        features.append(
            {
                "geometry": mapping(geometry),
                "properties": properties,
                "id": int(feature_id) if isinstance(feature_id, int) else str(feature_id),
            }
        )
    return mapbox_vector_tile.encode(
        [{"name": layer_name, "features": features}],
        default_options={
            "quantize_bounds": bounds,
            "extents": 4096,
            "y_coord_down": True,
        },
    )


def _json_value(value: Any):
    if value is None:
        return None
    if hasattr(value, "item"):
        value = value.item()
    return value if isinstance(value, (str, int, float, bool)) else str(value)
