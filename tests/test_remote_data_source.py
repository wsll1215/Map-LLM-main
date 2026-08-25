import json

from gis_mapping_agent.data_sources.remote import (
    extract_location_query,
    fetch_remote_boundary,
    fetch_remote_waterways,
    geocode_place,
    normalize_point_to_extent,
)


def test_extract_location_query_from_natural_language() -> None:
    assert extract_location_query("帮我绘制石家庄的地图") == "石家庄"
    assert extract_location_query("绘制燕山大学西校区的地图") == "燕山大学西校区"


def test_fetch_remote_boundary_caches_geojson(tmp_path, monkeypatch) -> None:
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return [
                {
                    "display_name": "石家庄市, 河北省, 中国",
                    "osm_type": "relation",
                    "osm_id": 3009732,
                    "geojson": {
                        "type": "Polygon",
                        "coordinates": [[[114.0, 38.0], [115.0, 38.0], [115.0, 39.0], [114.0, 38.0]]],
                    },
                }
            ]

    monkeypatch.setattr(
        "gis_mapping_agent.data_sources.remote.requests.get",
        lambda *args, **kwargs: Response(),
    )

    path = fetch_remote_boundary("石家庄", cache_dir=tmp_path)

    assert path is not None
    assert path.exists()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["type"] == "FeatureCollection"
    assert payload["features"][0]["properties"]["display_name"] == "石家庄市, 河北省, 中国"


def test_geocode_place_returns_wgs84_centroid(monkeypatch) -> None:
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return [{"lon": "116.326", "lat": "40.003", "display_name": "清华大学"}]

    monkeypatch.setattr(
        "gis_mapping_agent.data_sources.remote.requests.get",
        lambda *args, **kwargs: Response(),
    )

    assert geocode_place("清华大学") == (116.326, 40.003, "清华大学")


def test_fetch_remote_waterways_caches_lines(tmp_path, monkeypatch) -> None:
    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "elements": [
                    {
                        "id": 42,
                        "tags": {"waterway": "river", "name": "珠江"},
                        "geometry": [
                            {"lon": 113.8, "lat": 23.0},
                            {"lon": 113.9, "lat": 23.1},
                        ],
                    }
                ]
            }

    monkeypatch.setattr(
        "gis_mapping_agent.data_sources.remote.requests.post",
        lambda *args, **kwargs: (captured.update(kwargs) or Response()),
    )

    path = fetch_remote_waterways("广东省", [109.6, 20.2, 117.4, 25.6], cache_dir=tmp_path)

    assert path is not None
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["features"][0]["geometry"]["type"] == "LineString"
    assert payload["features"][0]["properties"]["name"] == "珠江"
    assert "waterway='river'][name]" in captured["data"]["data"]


def test_normalize_point_to_extent_preserves_real_location() -> None:
    position = normalize_point_to_extent(116.326, 40.003, [116.025, 39.871, 116.406, 40.173])

    assert 0.78 < position[0] < 0.80
    assert 0.43 < position[1] < 0.45
