from shapely.geometry import LineString, Point

from gis_mapping_agent.tools.unified_mapping_tools.rendering import _safe_label_point


def test_safe_label_point_skips_empty_geometry_without_raising():
    assert _safe_label_point(Point()) is None


def test_safe_label_point_returns_a_point_for_valid_geometry():
    point = _safe_label_point(LineString([(0, 0), (2, 2)]))

    assert point is not None
    assert point.x == 1
    assert point.y == 1
