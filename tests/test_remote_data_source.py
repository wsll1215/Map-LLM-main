import json
import math

import pytest
import requests

import gis_mapping_agent.data_sources.remote as remote
from gis_mapping_agent.data_sources.remote import (
    extract_location_query,
    extract_remote_poi_request,
    extract_remote_poi_query,
    fetch_remote_boundary,
    fetch_remote_pois,
    fetch_remote_roads,
    fetch_remote_named_poi,
    fetch_remote_waterways,
    geocode_place,
    normalize_point_to_extent,
)


def test_extract_location_query_from_natural_language() -> None:
    assert extract_location_query("帮我绘制石家庄的地图") == "石家庄"
    assert extract_location_query("绘制燕山大学西校区的地图") == "燕山大学西校区"
    assert extract_location_query("绘制广东省的地图，要标定出广东省下的所有城市以及道路河流") == "广东省"
    assert extract_location_query("请绘制石家庄地图，显示行政区边界") == "石家庄"
    assert extract_location_query("绘制北京的主要道路") == "北京"
    assert extract_location_query("请显示秦皇岛铁路") == "秦皇岛"


def test_extract_remote_poi_query_only_matches_batch_place_requests() -> None:
    assert extract_remote_poi_query("标注出秦皇岛各大高校的位置") == "秦皇岛"
    assert extract_remote_poi_query("显示石家庄高校分布") == "石家庄"
    assert extract_remote_poi_query("标注清华大学的位置") is None


def test_extract_remote_poi_request_supports_categories_without_hardcoding_places() -> None:
    assert extract_remote_poi_request("标注出秦皇岛各大高校的位置") == {
        "place": "秦皇岛",
        "category": "universities",
        "label": "高校",
    }
    assert extract_remote_poi_request("把小学画出来") == {
        "place": None,
        "category": "primary_schools",
        "label": "小学",
    }


def test_extract_remote_poi_request_removes_generic_scope_words_for_every_category():
    assert extract_remote_poi_request("标注秦皇岛所有小学的位置")["place"] == "秦皇岛"
    assert extract_remote_poi_request("显示石家庄各个医院")["place"] == "石家庄"
    assert extract_remote_poi_request("画北京所有公园")["place"] == "北京"


def test_extract_remote_poi_request_preserves_named_institution():
    assert extract_remote_poi_request("标注清华大学的位置") == {
        "place": "清华大学",
        "category": "universities",
        "label": "高校",
    }


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


def test_fetch_remote_roads_caches_named_line_features(tmp_path, monkeypatch) -> None:
    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "elements": [
                    {
                        "type": "way",
                        "id": 99,
                        "tags": {"highway": "primary", "name": "北京路"},
                        "geometry": [
                            {"lon": 116.3, "lat": 39.9},
                            {"lon": 116.4, "lat": 39.95},
                        ],
                    }
                ]
            }

    monkeypatch.setattr(
        "gis_mapping_agent.data_sources.remote.requests.post",
        lambda *args, **kwargs: (captured.update(kwargs) or Response()),
    )

    path = fetch_remote_roads("北京", [115.4, 39.4, 117.4, 41.1], cache_dir=tmp_path)

    assert path is not None
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["features"][0]["geometry"]["type"] == "LineString"
    assert payload["features"][0]["properties"]["name"] == "北京路"
    assert "highway" in captured["data"]["data"]


def test_fetch_remote_named_poi_uses_geocoded_name_instead_of_batch_query(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "gis_mapping_agent.data_sources.remote.geocode_place",
        lambda query: (116.326, 40.003, query),
    )

    path = fetch_remote_named_poi("清华大学", category="universities", cache_dir=tmp_path)

    assert path is not None
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["features"][0]["geometry"]["coordinates"] == [116.326, 40.003]
    assert payload["features"][0]["properties"]["name"] == "清华大学"


def test_corrupt_remote_cache_is_not_reused(tmp_path, monkeypatch) -> None:
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "elements": [
                    {
                        "type": "way",
                        "id": 7,
                        "tags": {"highway": "primary", "name": "新路"},
                        "geometry": [
                            {"lon": 120.1, "lat": 30.1},
                            {"lon": 120.2, "lat": 30.2},
                        ],
                    }
                ]
            }

    calls = []

    def post(url, **kwargs):
        calls.append(url)
        return Response()

    monkeypatch.setattr("gis_mapping_agent.data_sources.remote.requests.post", post)
    first = fetch_remote_roads("甲市", [120, 30, 121, 31], cache_dir=tmp_path)
    assert first is not None
    first.write_text("not geojson", encoding="utf-8")

    second = fetch_remote_roads("甲市", [120, 30, 121, 31], cache_dir=tmp_path)

    assert second is not None
    assert len(calls) >= 2
    assert json.loads(second.read_text(encoding="utf-8"))["features"][0]["properties"]["name"] == "新路"


def test_remote_request_timeout_is_capped_and_failure_is_typed(monkeypatch) -> None:
    timeouts = []

    def post(url, **kwargs):
        timeouts.append(kwargs["timeout"])
        raise requests.Timeout("upstream timeout")

    monkeypatch.setattr(remote.requests, "post", post)
    monkeypatch.setattr(remote.time, "sleep", lambda _: None)

    try:
        remote._request_with_retries(
            "POST", "https://overpass.example", timeout=60
        )
    except remote.RemoteDataSourceError as exc:
        assert exc.error_code == "network_error"
        assert exc.retryable is True
    else:
        raise AssertionError("expected typed network failure")

    assert timeouts
    assert max(timeouts) <= remote.REMOTE_HTTP_TIMEOUT_SECONDS


@pytest.mark.parametrize(
    ("status_code", "error_code", "retryable"),
    [
        (400, "validation_error", False),
        (404, "resource_not_found", False),
    ],
)
def test_remote_http_client_classifies_non_retryable_statuses(
    monkeypatch, status_code, error_code, retryable
):
    calls = []

    class Response:
        def __init__(self):
            self.status_code = status_code

        def raise_for_status(self):
            raise requests.HTTPError(response=self)

    monkeypatch.setattr(
        remote.requests,
        "get",
        lambda *args, **kwargs: calls.append(kwargs) or Response(),
    )

    with pytest.raises(remote.RemoteDataSourceError) as caught:
        remote._request_with_retries("GET", "https://example.test", timeout=5)

    assert caught.value.error_code == error_code
    assert caught.value.retryable is retryable
    assert len(calls) == 1


def test_remote_http_client_retries_rate_limit_and_preserves_error_type(monkeypatch):
    calls = []

    class Response:
        status_code = 429
        headers = {"Retry-After": "0"}

        def raise_for_status(self):
            raise requests.HTTPError(response=self)

    monkeypatch.setattr(
        remote.requests,
        "post",
        lambda *args, **kwargs: calls.append(kwargs) or Response(),
    )
    monkeypatch.setattr(remote.time, "sleep", lambda _: None)

    with pytest.raises(remote.RemoteDataSourceError) as caught:
        remote._request_with_retries("POST", "https://example.test", timeout=5)

    assert caught.value.error_code == "rate_limited"
    assert caught.value.retryable is True
    assert len(calls) == remote.REMOTE_MAX_ATTEMPTS


def test_remote_roads_preserve_validation_error_instead_of_relabeling_as_network(
    monkeypatch,
):
    calls = []

    class Response:
        status_code = 400
        headers = {}

        def raise_for_status(self):
            raise requests.HTTPError(response=self)

    monkeypatch.setattr(
        remote.requests,
        "post",
        lambda *args, **kwargs: calls.append(args[0]) or Response(),
    )

    with pytest.raises(remote.RemoteDataSourceError) as caught:
        remote.fetch_remote_roads("甲市", [120, 30, 121, 31])

    assert caught.value.error_code == "validation_error"
    assert caught.value.retryable is False
    assert len(calls) == 1


def test_remote_roads_switch_endpoint_when_response_schema_is_malformed(
    tmp_path, monkeypatch
):
    class MalformedResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return []

    class ValidResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "elements": [
                    {
                        "type": "way",
                        "id": 1,
                        "tags": {"highway": "primary", "name": "新路"},
                        "geometry": [
                            {"lon": 120.1, "lat": 30.1},
                            {"lon": 120.2, "lat": 30.2},
                        ],
                    }
                ]
            }

    responses = iter([MalformedResponse(), ValidResponse()])
    calls = []
    monkeypatch.setattr(remote, "OVERPASS_ENDPOINTS", ("https://one", "https://two"))
    monkeypatch.setattr(
        remote.requests,
        "post",
        lambda url, **kwargs: calls.append(url) or next(responses),
    )

    path = remote.fetch_remote_roads("甲市", [120, 30, 121, 31], cache_dir=tmp_path)

    assert path is not None
    assert calls == ["https://one", "https://two"]


def test_cache_writer_rejects_invalid_geojson_before_persisting(tmp_path):
    path = tmp_path / "invalid.geojson"

    with pytest.raises(remote.RemoteDataSourceError) as caught:
        remote._write_geojson_cache(
            path,
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [999, 999]},
                        "properties": {},
                    }
                ],
            },
        )

    assert caught.value.error_code == "data_invalid"
    assert not path.exists()


def test_cache_writer_reports_cross_process_lock_contention(tmp_path, monkeypatch):
    path = tmp_path / "locked.geojson"
    lock_path = path.with_name(f".{path.name}.lock")
    lock_path.write_text("other-process", encoding="utf-8")
    monkeypatch.setattr(remote, "REMOTE_CACHE_LOCK_TIMEOUT_SECONDS", 0.0)

    with pytest.raises(remote.RemoteDataSourceError) as caught:
        remote._write_geojson_cache(
            path,
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [120, 30]},
                        "properties": {},
                    }
                ],
            },
        )

    assert caught.value.error_code == "cache_lock_timeout"
    assert caught.value.retryable is True
    assert not path.exists()


def test_retry_after_is_clamped_to_a_non_negative_finite_delay(monkeypatch):
    sleeps = []

    class Response:
        status_code = 429
        headers = {"Retry-After": "-1"}

        def raise_for_status(self):
            raise requests.HTTPError(response=self)

    monkeypatch.setattr(remote.requests, "get", lambda *args, **kwargs: Response())
    monkeypatch.setattr(remote.time, "sleep", sleeps.append)

    with pytest.raises(remote.RemoteDataSourceError) as caught:
        remote._request_with_retries("GET", "https://example.test", timeout=5)

    assert caught.value.error_code == "rate_limited"
    assert all(delay >= 0 and math.isfinite(delay) for delay in sleeps)


@pytest.mark.parametrize(
    "bbox",
    [
        [float("nan"), 30, 121, 31],
        [120, 30, float("inf"), 31],
        [120, -91, 121, 31],
        [120, 30, 181, 31],
    ],
)
def test_remote_bbox_validation_rejects_non_finite_or_out_of_range_values(
    bbox,
):
    with pytest.raises(remote.RemoteDataSourceError) as caught:
        remote._validate_remote_bbox(bbox)

    assert caught.value.error_code == "validation_error"
    assert caught.value.retryable is False


def test_fetch_remote_pois_caches_named_point_features(tmp_path, monkeypatch) -> None:
    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "elements": [
                    {
                        "type": "node",
                        "id": 11,
                        "lat": 39.9,
                        "lon": 119.5,
                        "tags": {"amenity": "university", "name": "燕山大学"},
                    },
                    {
                        "type": "way",
                        "id": 12,
                        "center": {"lat": 39.95, "lon": 119.55},
                        "tags": {"amenity": "college", "name": "示例学院"},
                    },
                ]
            }

    monkeypatch.setattr(
        "gis_mapping_agent.data_sources.remote.requests.post",
        lambda *args, **kwargs: (captured.update(kwargs) or Response()),
    )

    path = fetch_remote_pois("秦皇岛", [119.2, 39.7, 119.8, 40.1], cache_dir=tmp_path)

    assert path is not None
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert [feature["properties"]["name"] for feature in payload["features"]] == [
        "燕山大学",
        "示例学院",
    ]
    assert payload["features"][0]["geometry"] == {"type": "Point", "coordinates": [119.5, 39.9]}
    assert "amenity" in captured["data"]["data"]


def test_fetch_remote_pois_retries_transient_network_failure(tmp_path, monkeypatch) -> None:
    calls = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "elements": [
                    {
                        "type": "node",
                        "id": 11,
                        "lat": 39.9,
                        "lon": 119.5,
                        "tags": {"amenity": "university", "name": "燕山大学"},
                    }
                ]
            }

    def post(url, **kwargs):
        calls.append(url)
        if len(calls) == 1:
            raise requests.RequestException("temporary network failure")
        return Response()

    monkeypatch.setattr(remote, "OVERPASS_ENDPOINTS", ("https://overpass.example",))
    monkeypatch.setattr(remote.requests, "post", post)
    monkeypatch.setattr(remote.time, "sleep", lambda _: None)

    path = fetch_remote_pois("秦皇岛", [119.2, 39.7, 119.8, 40.1], cache_dir=tmp_path)

    assert path is not None
    assert calls == ["https://overpass.example", "https://overpass.example"]


def test_fetch_remote_pois_filters_primary_school_category(tmp_path, monkeypatch) -> None:
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "elements": [
                    {
                        "type": "node",
                        "id": 1,
                        "lat": 39.9,
                        "lon": 119.5,
                        "tags": {"amenity": "school", "school": "primary", "name": "第一小学"},
                    },
                    {
                        "type": "node",
                        "id": 2,
                        "lat": 39.91,
                        "lon": 119.51,
                        "tags": {"amenity": "school", "school": "secondary", "name": "第二中学"},
                    },
                ]
            }

    monkeypatch.setattr(remote.requests, "post", lambda *args, **kwargs: Response())

    path = fetch_remote_pois(
        "秦皇岛",
        [119.2, 39.7, 119.8, 40.1],
        cache_dir=tmp_path,
        category="primary_schools",
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert [feature["properties"]["name"] for feature in payload["features"]] == ["第一小学"]


def test_fetch_remote_waterways_retries_configured_overpass_endpoints(tmp_path, monkeypatch) -> None:
    calls = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "elements": [
                    {
                        "id": 7,
                        "tags": {"waterway": "river", "name": "珠江"},
                        "geometry": [
                            {"lon": 113.8, "lat": 23.0},
                            {"lon": 113.9, "lat": 23.1},
                        ],
                    }
                ]
            }

    def post(url, **kwargs):
        calls.append(url)
        if len(calls) <= remote.REMOTE_MAX_ATTEMPTS:
            raise requests.RequestException("first endpoint unavailable")
        return Response()

    monkeypatch.setattr(remote, "OVERPASS_ENDPOINTS", ("https://first.example", "https://second.example"))
    monkeypatch.setattr(remote.requests, "post", post)
    monkeypatch.setattr(remote.time, "sleep", lambda _: None)

    path = fetch_remote_waterways("广东省", [109.6, 20.2, 117.4, 25.6], cache_dir=tmp_path)

    assert path is not None
    assert calls == [
        "https://first.example",
        "https://first.example",
        "https://first.example",
        "https://second.example",
    ]


def test_fetch_remote_waterways_reports_network_failure_as_typed_error(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(remote, "OVERPASS_ENDPOINTS", ("https://overpass.example",))
    monkeypatch.setattr(
        remote.requests,
        "post",
        lambda *args, **kwargs: (_ for _ in ()).throw(requests.Timeout("offline")),
    )
    monkeypatch.setattr(remote.time, "sleep", lambda _: None)

    try:
        fetch_remote_waterways(
            "北京", [115.4, 39.4, 117.4, 41.1], cache_dir=tmp_path, timeout=1
        )
    except remote.RemoteDataSourceError as exc:
        assert exc.error_code == "network_error"
        assert exc.retryable is True
    else:
        raise AssertionError("expected typed network failure")


def test_normalize_point_to_extent_preserves_real_location() -> None:
    position = normalize_point_to_extent(116.326, 40.003, [116.025, 39.871, 116.406, 40.173])

    assert 0.78 < position[0] < 0.80
    assert 0.43 < position[1] < 0.45
