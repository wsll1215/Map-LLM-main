from dataclasses import dataclass

import gis_mapping_agent.data_sources.remote as remote
from gis_mapping_agent.data_sources.planner import (
    LocationResolution,
    PlannedSource,
    SourcePlan,
    parse_intent,
    plan_sources,
    resolve_local_location,
)
from gis_mapping_agent.data_sources.catalog import DjangoDatasetCatalog


@dataclass
class Catalog:
    datasets: list

    def scan(self):
        return list(self.datasets)


class FakeDatasetManager:
    def __init__(self, rows):
        self.rows = rows

    def filter(self, **kwargs):
        return [
            row
            for row in self.rows
            if all(getattr(row, key, None) == value for key, value in kwargs.items())
        ]


class FakeDatasetModel:
    STATUS_AVAILABLE = "available"
    SOURCE_LOCAL = "local"


def test_runtime_catalog_reads_registered_datasets_without_scanning_files():
    class Features:
        def count(self):
            return 3

    row = type(
        "DatasetRow",
        (),
        {
            "status": "available",
            "dataset_id": "local-road",
            "name": "Highway",
            "aliases": [],
            "source_type": "local",
            "local_path": "data/road.shp",
            "geometry_type": "LineString",
            "crs": "EPSG:4326",
            "bbox": [120, 30, 121, 31],
            "feature_count": 3,
            "metadata": {},
            "features": Features(),
        },
    )()
    FakeDatasetModel.objects = FakeDatasetManager([row])

    descriptors = DjangoDatasetCatalog(FakeDatasetModel).scan()

    assert len(descriptors) == 1
    assert descriptors[0].role == "road"
    assert descriptors[0].feature_count == 3


def test_runtime_catalog_excludes_remote_and_upload_datasets_from_local_candidates():
    rows = []
    for source_type in ("remote", "upload"):
        rows.append(
            type(
                "DatasetRow",
                (),
                {
                    "status": "available",
                    "dataset_id": source_type,
                    "name": "Highway",
                    "aliases": [],
                    "source_type": source_type,
                    "local_path": "data/road.geojson",
                    "geometry_type": "LineString",
                    "crs": "EPSG:4326",
                    "bbox": [120, 30, 121, 31],
                    "feature_count": 3,
                    "metadata": {},
                    "features": type("Features", (), {"count": lambda self: 3})(),
                },
            )()
        )
    FakeDatasetModel.objects = FakeDatasetManager(rows)

    assert DjangoDatasetCatalog(FakeDatasetModel).scan() == []


def test_runtime_catalog_preserves_registered_poi_role():
    row = type(
        "DatasetRow",
        (),
        {
            "status": "available",
            "dataset_id": "local-primary-schools",
            "name": "学校点位",
            "aliases": [],
            "source_type": "local",
            "local_path": "poi/schools.geojson",
            "geometry_type": "Point",
            "crs": "EPSG:4326",
            "bbox": [120, 30, 121, 31],
            "feature_count": 3,
            "metadata": {"role": "primary_school"},
            "features": type("Features", (), {"count": lambda self: 3})(),
        },
    )()
    FakeDatasetModel.objects = FakeDatasetManager([row])

    descriptors = DjangoDatasetCatalog(FakeDatasetModel).scan()

    assert descriptors[0].role == "primary_school"


def test_local_location_index_is_used_before_remote_geocoding():
    descriptor = type(
        "Descriptor",
        (),
        {
            "name": "甲市",
            "aliases": ["甲市市"],
            "role": "boundary",
            "bbox": [120, 30, 121, 31],
            "local_path": "data/a.shp",
        },
    )()

    resolution = resolve_local_location("甲市", Catalog([descriptor]))

    assert resolution.provider == "PostGIS"
    assert resolution.bbox == (120.0, 30.0, 121.0, 31.0)


def test_local_location_index_does_not_treat_a_generic_suffix_as_a_place():
    descriptor = type(
        "Descriptor",
        (),
        {
            "name": "甲市",
            "aliases": [],
            "role": "boundary",
            "bbox": [120, 30, 121, 31],
            "local_path": "data/a.shp",
        },
    )()

    assert resolve_local_location("市", Catalog([descriptor])) is None


def test_parse_intent_extracts_location_and_required_roles_without_prompt_branch():
    intent = parse_intent("请把石家庄市的主要道路和公园展示出来")

    assert intent.location.text == "石家庄市"
    assert {layer.role for layer in intent.layers} == {"road", "park"}
    assert all(layer.required for layer in intent.layers)


def test_parse_intent_does_not_send_the_full_sentence_to_geocoding():
    intent = parse_intent("绘制北京的地图，要显示主要的道路")

    assert intent.location.text == "北京"
    assert {layer.role for layer in intent.layers} == {"road"}


def test_plan_sources_rejects_a_local_dataset_outside_the_resolved_location():
    intent = parse_intent("绘制甲市道路")
    location = LocationResolution(
        text="甲市",
        precision="city",
        bbox=(120.0, 30.0, 121.0, 31.0),
        geometry=None,
        provider="test",
        confidence=1.0,
    )
    catalog = Catalog(
        [
            PlannedSource(
                role="road",
                source_type="local",
                provider="PostGIS",
                source_url=None,
                cache_path="local/road.geojson",
                bbox=(100.0, 20.0, 101.0, 21.0),
                feature_count=10,
                status="available",
            )
        ]
    )

    plan = plan_sources(intent, location=location, catalog=catalog)

    assert plan.layers[0].status == "failed"
    assert plan.layers[0].source_type == "remote"
    assert plan.layers[0].error_code == "resource_not_found"
    assert plan.layers[0].spatial_valid is False


def test_plan_sources_does_not_accept_local_source_without_verified_location():
    intent = parse_intent("绘制甲市道路")
    catalog = Catalog(
        [
            PlannedSource(
                role="road",
                source_type="local",
                provider="PostGIS",
                source_url=None,
                cache_path="local/road.geojson",
                bbox=(100.0, 20.0, 101.0, 21.0),
                feature_count=10,
                status="available",
            )
        ]
    )

    plan = plan_sources(intent, location=None, catalog=catalog)

    assert plan.layers[0].status == "failed"
    assert plan.layers[0].error_code == "location_not_resolved"


def test_plan_sources_uses_remote_source_after_local_spatial_miss():
    intent = parse_intent("绘制甲市道路")
    location = LocationResolution(
        text="甲市",
        precision="city",
        bbox=(120.0, 30.0, 121.0, 31.0),
        geometry=None,
        provider="test",
        confidence=1.0,
    )
    remote = PlannedSource(
        role="road",
        source_type="remote",
        provider="OpenStreetMap/Overpass",
        source_url="https://example.test/overpass",
        cache_path="data_cache/road.geojson",
        bbox=location.bbox,
        feature_count=4,
        status="available",
        spatial_valid=True,
    )

    plan = plan_sources(
        intent,
        location=location,
        catalog=Catalog([]),
        remote_sources={"road": remote},
    )

    assert plan.layers[0] == remote
    assert plan.layers[0].source_type == "remote"
    assert plan.layers[0].status == "available"


def test_plan_sources_rejects_remote_source_with_wrong_role_or_empty_data():
    intent = parse_intent("绘制甲市道路")
    location = LocationResolution(
        text="甲市", precision="city", bbox=(120.0, 30.0, 121.0, 31.0),
        geometry=None, provider="test", confidence=1.0,
    )
    remote = PlannedSource(
        role="river", source_type="remote", provider="Overpass", source_url=None,
        cache_path="remote/river.geojson", bbox=location.bbox,
        feature_count=0, status="available",
    )

    plan = plan_sources(intent, location=location, catalog=Catalog([]), remote_sources={"road": remote})

    assert plan.layers[0].status == "failed"
    assert plan.layers[0].error_code == "resource_not_found"


def test_explicit_source_restricts_runtime_candidates_to_that_source():
    intent = parse_intent("请用 data/road.geojson 绘制甲市道路")
    location = LocationResolution(
        text="甲市", precision="city", bbox=(120.0, 30.0, 121.0, 31.0),
        geometry=None, provider="test", confidence=1.0,
    )
    catalog = Catalog([
        PlannedSource(
            role="road", source_type="local", provider="PostGIS", source_url=None,
            cache_path="data/other.geojson", bbox=location.bbox,
            feature_count=10, status="available",
        )
    ])

    plan = plan_sources(intent, location=location, catalog=catalog)

    assert plan.layers[0].status == "failed"
    assert plan.layers[0].error_code == "resource_not_found"


def test_plan_sources_rejects_invalid_source_bbox_instead_of_interpreting_it():
    intent = parse_intent("绘制甲市道路")
    location = LocationResolution(
        text="甲市", precision="city", bbox=(120.0, 30.0, 121.0, 31.0),
        geometry=None, provider="test", confidence=1.0,
    )
    catalog = Catalog([
        PlannedSource(
            role="road", source_type="local", provider="PostGIS", source_url=None,
            cache_path="data/road.geojson", bbox=(121, 31, 120, 30),
            feature_count=10, status="available",
        )
    ])

    plan = plan_sources(intent, location=location, catalog=catalog)

    assert plan.layers[0].status == "failed"
    assert plan.layers[0].error_code == "resource_not_found"


def test_plan_sources_keeps_remote_failure_as_structured_result():
    intent = parse_intent("绘制甲市道路")
    location = LocationResolution(
        text="甲市",
        precision="city",
        bbox=(120.0, 30.0, 121.0, 31.0),
        geometry=None,
        provider="test",
        confidence=1.0,
    )

    plan = plan_sources(
        intent,
        location=location,
        catalog=Catalog([]),
        remote_errors={
            "road": {
                "error_code": "network_error",
                "retryable": True,
                "next_action": "retry_remote_source",
            }
        },
    )

    assert plan.layers[0].status == "failed"
    assert plan.layers[0].error_code == "network_error"
    assert plan.layers[0].retryable is True
    assert plan.layers[0].next_action == "retry_remote_source"


def test_local_miss_and_remote_failure_returns_remote_failure_not_local_rejection():
    intent = parse_intent("绘制甲市道路")
    location = LocationResolution(
        text="甲市", precision="city", bbox=(120.0, 30.0, 121.0, 31.0),
        geometry=None, provider="test", confidence=1.0,
    )
    catalog = Catalog([
        PlannedSource(
            role="road", source_type="local", provider="PostGIS", source_url=None,
            cache_path="local/road.geojson", bbox=(100.0, 20.0, 101.0, 21.0),
            feature_count=10, status="available",
        )
    ])

    plan = plan_sources(
        intent, location=location, catalog=catalog,
        remote_errors={"road": {"error_code": "network_error", "retryable": True}},
    )

    assert plan.layers[0].status == "failed"
    assert plan.layers[0].source_type == "remote"
    assert plan.layers[0].error_code == "network_error"


def test_parse_intent_keeps_named_poi_location_intact():
    intent = parse_intent("标注清华大学的位置")

    assert intent.location.text == "清华大学"
    assert any(layer.role == "university" for layer in intent.layers)


def test_location_resolution_failure_never_returns_a_global_extent(monkeypatch):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return []

    monkeypatch.setattr(remote.requests, "get", lambda *args, **kwargs: Response())

    resolution = remote.resolve_location("不存在的地点")

    assert resolution.error_code == "location_not_resolved"
    assert resolution.bbox is None
    assert resolution.geometry is None
