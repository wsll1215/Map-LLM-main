from types import SimpleNamespace

import geopandas as gpd
from shapely.geometry import LineString, Point, Polygon, mapping

from mapping.finalization import validate_source_spatial
from gis_mapping_agent.agent.thinking import ThinkingGISMappingAgent
from gis_mapping_agent.data_sources.planner import LocationResolution, SourcePlan


def _location():
    return LocationResolution(
        text="甲市",
        precision="city",
        bbox=(0.0, 0.0, 10.0, 10.0),
        geometry=None,
        provider="test",
        confidence=1.0,
    )


def test_point_layer_requires_resolved_location_geometry_not_only_bbox():
    source = SimpleNamespace(
        gdf=gpd.GeoDataFrame({"geometry": [Point(5, 5), Point(20, 20)]}, crs="EPSG:4326"),
        feature_count=2,
    )

    result = validate_source_spatial(source, _location(), "school")

    assert result.geometry_valid is True
    assert result.spatial_valid is False
    assert result.reason == "location_geometry_unavailable"


def test_invalid_geometry_is_not_a_valid_source():
    source = SimpleNamespace(
        gdf=gpd.GeoDataFrame(
            {"geometry": [Polygon([(0, 0), (1, 1), (0, 1), (1, 0), (0, 0)])]},
            crs="EPSG:4326",
        ),
        feature_count=1,
    )

    result = validate_source_spatial(source, _location(), "boundary")

    assert result.geometry_valid is False
    assert result.spatial_valid is False


def test_point_layer_requires_every_feature_to_be_inside_location():
    source = SimpleNamespace(
        gdf=gpd.GeoDataFrame(
            {"geometry": [Point(5, 5), Point(20, 20)]}, crs="EPSG:4326"
        ),
        feature_count=2,
    )
    location = LocationResolution(
        text="甲市",
        precision="city",
        bbox=(0.0, 0.0, 10.0, 10.0),
        geometry=mapping(Polygon([(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)])),
        provider="test",
        confidence=1.0,
    )

    result = validate_source_spatial(source, location, "school")

    assert result.spatial_valid is False
    assert result.reason == "features_outside_location"


def test_spatial_validation_rejects_data_without_crs():
    source = SimpleNamespace(
        gdf=gpd.GeoDataFrame({"geometry": [Point(5, 5)]}), feature_count=1
    )
    location = LocationResolution(
        text="甲市",
        precision="city",
        bbox=(0.0, 0.0, 10.0, 10.0),
        geometry=mapping(Polygon([(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)])),
        provider="test",
        confidence=1.0,
    )

    result = validate_source_spatial(source, location, "school")

    assert result.geometry_valid is False
    assert result.spatial_valid is False
    assert result.reason == "crs_missing"


def test_spatial_validation_converts_projected_data_before_membership_check():
    location_shape = Polygon([(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)])
    location = LocationResolution(
        text="甲市",
        precision="city",
        bbox=(0.0, 0.0, 1.0, 1.0),
        geometry=mapping(location_shape),
        provider="test",
        confidence=1.0,
    )
    source = SimpleNamespace(
        gdf=gpd.GeoDataFrame(
            {"geometry": [Point(0.5, 0.5)]}, crs="EPSG:4326"
        ).to_crs("EPSG:3857"),
        feature_count=1,
    )

    result = validate_source_spatial(source, location, "school")

    assert result.geometry_valid is True
    assert result.spatial_valid is True


def test_line_layer_is_clipped_to_location_before_it_is_validated():
    source = SimpleNamespace(
        gdf=gpd.GeoDataFrame(
            {"name": ["crossing", "outside"]},
            geometry=[
                LineString([(-5, 5), (5, 5)]),
                LineString([(20, 20), (21, 21)]),
            ],
            crs="EPSG:4326",
        ),
        feature_count=2,
    )
    location = LocationResolution(
        text="甲市",
        precision="city",
        bbox=(0.0, 0.0, 10.0, 10.0),
        geometry=mapping(Polygon([(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)])),
        provider="test",
        confidence=1.0,
    )

    result = validate_source_spatial(source, location, "road")

    assert result.spatial_valid is True
    assert result.clipped is True
    assert result.feature_count == 1
    assert result.clipped_frame is not None
    assert len(result.clipped_frame) == 1
    assert result.clipped_frame.geometry.iloc[0].bounds == (0.0, 5.0, 5.0, 5.0)


def test_source_plan_serialization_keeps_resolved_location_geometry():
    location = LocationResolution(
        text="甲市",
        precision="city",
        bbox=(0.0, 0.0, 10.0, 10.0),
        geometry=mapping(Polygon([(0, 0), (0, 10), (10, 10), (10, 0), (0, 0)])),
        provider="test",
        confidence=1.0,
    )
    serialized = ThinkingGISMappingAgent._serialize_source_plan(
        SourcePlan(intent=None, location=location, layers=())
    )

    assert serialized["location"]["geometry"]["type"] == "Polygon"
