import geopandas as gpd
import mapbox_vector_tile
import mercantile
from shapely.geometry import LineString

from gis_mapping_agent.rendering.mvt import encode_tile


def test_encode_tile_returns_decodable_vector_tile():
    data = gpd.GeoDataFrame(
        {"name": ["road"]},
        geometry=[LineString([(116.0, 40.0), (116.1, 40.1)])],
        crs="EPSG:4326",
    )

    tile_coordinates = mercantile.tile(116.0, 40.0, 8)
    tile = encode_tile(data, "roads", tile_coordinates.z, tile_coordinates.x, tile_coordinates.y)
    decoded = mapbox_vector_tile.decode(tile)

    assert tile.startswith(b"\x1a")
    assert len(tile) > 20
    assert decoded["roads"]["features"]
    assert decoded["roads"]["features"][0]["properties"]["name"] == "road"
