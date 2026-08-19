import geopandas as gpd
from shapely.geometry import LineString

from gis_mapping_agent.generalization import GeneralizationResult


def test_generalization_result_keeps_legacy_shape():
    gdf = gpd.GeoDataFrame(geometry=[LineString([(0, 0), (1, 1)])])

    payload = GeneralizationResult(
        input_path="data/in.shp",
        output_path="out.png",
        input_gdf=gdf,
        output_gdf=gdf,
        metrics={"output_count": 1},
        params={"algorithm": "stroke", "keep_ratio": 0.5},
        meta={"stroke_count": 1},
    ).to_legacy_dict()

    assert payload["success"] is True
    assert payload["input_path"] == "data/in.shp"
    assert payload["filepath"] == "out.png"
    assert payload["statistics"]["output_count"] == 1
    assert payload["stroke_count"] == 1
