from pathlib import Path
from types import SimpleNamespace

from shapely.geometry import Polygon, mapping

from gis_mapping_agent.data_sources.coordinator import build_source_plan
from gis_mapping_agent.data_sources.catalog import DjangoDatasetCatalog
from gis_mapping_agent.data_sources.planner import (
    Intent,
    LayerIntent,
    LocationIntent,
    LocationResolution,
    PlannedSource,
)


class Catalog:
    def __init__(self, sources=()):
        self.sources = list(sources)

    def scan(self):
        return list(self.sources)


def intent(*roles, place="甲市"):
    return Intent(
        location=LocationIntent(place, "city"),
        layers=tuple(LayerIntent(role) for role in roles),
        confidence=1.0,
    )


def location():
    return LocationResolution(
        text="甲市",
        precision="city",
        bbox=(120.0, 30.0, 121.0, 31.0),
        geometry=mapping(
            Polygon(
                [
                    (120.0, 30.0),
                    (121.0, 30.0),
                    (121.0, 31.0),
                    (120.0, 31.0),
                    (120.0, 30.0),
                ]
            )
        ),
        provider="test",
        confidence=1.0,
    )


def write_geojson(tmp_path, name="road.geojson"):
    path = Path(tmp_path) / name
    path.write_text(
        '{"type":"FeatureCollection","features":[{"type":"Feature","geometry":{"type":"LineString","coordinates":[[120,30],[120.1,30.1]]},"properties":{}}]}',
        encoding="utf-8",
    )
    return path


def write_outside_geojson(tmp_path):
    path = Path(tmp_path) / "outside-road.geojson"
    path.write_text(
        '{"type":"FeatureCollection","features":[{"type":"Feature","geometry":{"type":"LineString","coordinates":[[100,20],[100.1,20.1]]},"properties":{}}]}',
        encoding="utf-8",
    )
    return path


def test_coordinator_uses_verified_local_source_without_calling_remote():
    local = PlannedSource(
        role="road", source_type="local", provider="PostGIS", source_url=None,
        cache_path="road", bbox=location().bbox, feature_count=2, status="available",
    )
    calls = []

    def fetcher(*args, **kwargs):
        calls.append(args)
        return None

    plan = build_source_plan(
        intent("road"), catalog=Catalog([local]), location=location(), fetcher=fetcher
    )

    assert plan.layers[0].source_type == "local"
    assert calls == []


def test_coordinator_falls_back_to_remote_when_local_is_outside_location(tmp_path):
    local = PlannedSource(
        role="road", source_type="local", provider="PostGIS", source_url=None,
        cache_path="road", bbox=(100, 20, 101, 21), feature_count=2, status="available",
    )
    remote_path = write_geojson(tmp_path)

    def fetcher(role, place, bbox, **kwargs):
        assert (role, place, bbox) == ("road", "甲市", location().bbox)
        return remote_path

    plan = build_source_plan(
        intent("road"), catalog=Catalog([local]), location=location(), fetcher=fetcher
    )

    assert plan.layers[0].source_type == "remote"
    assert plan.layers[0].provider == "OpenStreetMap/Overpass"
    assert plan.layers[0].feature_count == 1
    assert plan.layers[0].cache_path == remote_path.as_posix()


def test_coordinator_preserves_typed_remote_failure():
    def fetcher(*args, **kwargs):
        from gis_mapping_agent.data_sources.remote import RemoteDataSourceError

        raise RemoteDataSourceError("timeout", code="network_error", retryable=True)

    plan = build_source_plan(
        intent("road"), catalog=Catalog(), location=location(), fetcher=fetcher
    )

    source = plan.layers[0]
    assert source.status == "failed"
    assert source.source_type == "remote"
    assert source.error_code == "network_error"
    assert source.retryable is True
    assert source.next_action == "retry_remote_source"


def test_coordinator_rejects_remote_source_outside_resolved_location(tmp_path):
    plan = build_source_plan(
        intent("road"),
        catalog=Catalog(),
        location=location(),
        fetcher=lambda *_args, **_kwargs: write_outside_geojson(tmp_path),
    )

    source = plan.layers[0]
    assert source.status == "failed"
    assert source.spatial_valid is False
    assert source.error_code == "spatial_mismatch"


def test_coordinator_does_not_reselect_local_source_after_spatial_validation_fails(
    monkeypatch,
):
    local = PlannedSource(
        role="road",
        source_type="local",
        provider="PostGIS",
        source_url=None,
        cache_path="road",
        dataset_id="local-road",
        bbox=location().bbox,
        feature_count=2,
        status="available",
    )
    catalog = DjangoDatasetCatalog()
    catalog.scan = lambda: [local]

    def reject_source(source, _location):
        return PlannedSource(
            **{
                **source.__dict__,
                "status": "failed",
                "spatial_valid": False,
                "geometry_valid": False,
                "error_code": "spatial_mismatch",
            }
        )

    monkeypatch.setattr(
        "gis_mapping_agent.data_sources.coordinator._validate_source",
        reject_source,
    )

    plan = build_source_plan(
        intent("road"),
        catalog=catalog,
        location=location(),
        fetcher=lambda *_args, **_kwargs: None,
    )

    assert plan.layers[0].status == "failed"
    assert plan.layers[0].error_code == "resource_not_found"


def test_coordinator_does_not_create_global_extent_when_location_fails():
    plan = build_source_plan(
        intent("road"),
        catalog=Catalog(),
        location_resolver=lambda _: LocationResolution(
            text="甲市", precision="unknown", bbox=None, geometry=None,
            provider="test", confidence=0.0, error_code="location_not_resolved",
        ),
    )

    assert plan.location.bbox is None
    assert plan.layers[0].error_code == "location_not_resolved"
    assert plan.layers[0].bbox == ()


def test_coordinator_persists_scoped_line_result_for_runtime_reads(monkeypatch):
    import geopandas as gpd
    from shapely.geometry import LineString
    from gis_mapping_agent.data_sources import coordinator

    source = PlannedSource(
        role="road",
        source_type="remote",
        provider="OpenStreetMap/Overpass",
        source_url="https://overpass.example",
        cache_path="data_cache/roads.geojson",
        dataset_id="remote-roads",
        bbox=location().bbox,
        feature_count=2,
        status="available",
    )
    monkeypatch.setattr(
        "mapping.dataset_reader.read_dataset_features",
        lambda *_args, **_kwargs: gpd.GeoDataFrame(
            {"name": ["crossing", "outside"]},
            geometry=[
                LineString([(119.5, 30.5), (120.5, 30.5)]),
                LineString([(122.0, 32.0), (123.0, 33.0)]),
            ],
            crs="EPSG:4326",
        ),
    )

    checked = coordinator._validate_source(source, location())

    assert checked.status == "available"
    assert checked.feature_count == 1
    assert checked.metadata["clipped"] is True
    assert checked.metadata["scope_geometry"]["type"] == "Polygon"


def test_coordinator_emits_one_data_fetch_span_for_remote_acquisition(monkeypatch, tmp_path):
    from gis_mapping_agent.data_sources import coordinator
    import geopandas as gpd

    lifecycle = []
    span = SimpleNamespace(event_id="fetch-span-1")
    monkeypatch.setattr(
        coordinator,
        "_remote_source",
        lambda role, _path, bbox: PlannedSource(
            role=role,
            source_type="remote",
            provider="OpenStreetMap/Overpass",
            source_url="https://overpass.example/api/interpreter",
            cache_path=str(tmp_path / "road.geojson"),
            dataset_id="remote-road",
            bbox=bbox,
            feature_count=4,
            status="available",
            spatial_valid=True,
            geometry_valid=True,
        ),
    )
    monkeypatch.setattr(
        "mapping.trace.run_for_session",
        lambda _session_id: SimpleNamespace(id=3, request_id=7),
    )
    monkeypatch.setattr(
        "mapping.trace.start_trace_event",
        lambda **_kwargs: span,
    )
    monkeypatch.setattr(
        "mapping.trace.finish_trace_event",
        lambda event, **_kwargs: event,
    )
    monkeypatch.setattr(
        "mapping.trace.publish_trace_lifecycle",
        lambda _event, name: lifecycle.append(name),
    )
    monkeypatch.setattr(
        "mapping.trace.publish_trace_event",
        lambda _event: None,
    )
    monkeypatch.setattr(
        "mapping.dataset_reader.read_dataset_features",
        lambda _dataset_id, limit=None: gpd.read_file(tmp_path / "road.geojson"),
    )

    plan = build_source_plan(
        intent("road"),
        catalog=Catalog(),
        location=location(),
        session_id="web_session_7",
        fetcher=lambda *_args, **_kwargs: write_geojson(tmp_path),
    )

    assert plan.layers[0].status == "available"
    assert lifecycle == ["data_fetch_started", "data_fetch_finished"]
