import json

import pytest

from tests.performance.render_benchmark import (
    DEFAULT_BBOX,
    REQUIRED_FEATURE_COUNTS,
    BenchmarkObservation,
    browser_case,
    build_ab_scenarios,
    collect_browser_metrics,
    fixture_json,
    generate_geojson,
    install_browser_metrics,
    load_observations,
    render_report,
    summarize_observations,
    _optimized_strategy,
)
from tests.performance.run_render_ab import (
    _benchmark_url,
    _vite_base_url_for_port,
    _vite_health_url,
    _vite_port,
)
from tests.performance.run_render_ab import _mvt_fixture_for_request, _mvt_tile_layout


def test_generate_geojson_is_deterministic_and_has_exact_feature_count():
    first = generate_geojson(4999, seed=20260827)
    second = generate_geojson(4999, seed=20260827)

    assert first == second
    assert first["type"] == "FeatureCollection"
    assert len(first["features"]) == 4999
    assert all(feature["type"] == "Feature" for feature in first["features"])
    assert all(
        feature["geometry"]["type"] == "LineString" for feature in first["features"]
    )
    assert all(
        len(feature["geometry"]["coordinates"]) >= 2 for feature in first["features"]
    )


def test_generated_coordinates_stay_inside_fixture_bbox():
    fixture = generate_geojson(5001, seed=7)
    min_x, min_y, max_x, max_y = fixture["metadata"]["bbox"]

    coordinates = [
        coordinate
        for feature in fixture["features"]
        for coordinate in feature["geometry"]["coordinates"]
    ]

    assert all(min_x <= x <= max_x and min_y <= y <= max_y for x, y in coordinates)


@pytest.mark.parametrize("feature_count", REQUIRED_FEATURE_COUNTS)
def test_required_fixture_sizes_are_available(feature_count):
    fixture = generate_geojson(feature_count)

    assert len(fixture["features"]) == feature_count
    assert fixture["metadata"]["feature_count"] == feature_count
    assert fixture["metadata"]["seed"] == 20260827


def test_invalid_fixture_size_is_rejected():
    with pytest.raises(ValueError, match="feature_count"):
        generate_geojson(0)


def test_ab_scenarios_cover_threshold_boundaries_and_expose_both_variants():
    scenarios = build_ab_scenarios()

    assert [scenario.feature_count for scenario in scenarios] == list(REQUIRED_FEATURE_COUNTS)
    assert [scenario.optimized_strategy for scenario in scenarios] == [
        "direct",
        "direct",
        "direct",
        "direct",
        "worker",
        "worker",
        "worker",
        "worker",
        "mvt",
    ]
    assert all(scenario.baseline_strategy == "direct" for scenario in scenarios)
    assert all(scenario.variants == ("A", "B") for scenario in scenarios)


def test_ab_scenarios_accept_candidate_counts_for_threshold_calibration():
    scenarios = build_ab_scenarios((5500, 7000, 8500, 10000))

    assert [scenario.feature_count for scenario in scenarios] == [
        5500,
        7000,
        8500,
        10000,
    ]
    assert [scenario.optimized_strategy for scenario in scenarios] == [
        "direct",
        "direct",
        "worker",
        "worker",
    ]


def test_calibrated_worker_boundary_is_eight_thousand_features():
    assert _optimized_strategy(7999) == "direct"
    assert _optimized_strategy(8000) == "direct"
    assert _optimized_strategy(8001) == "worker"


def test_summarize_observations_returns_median_p95_and_correctness_aggregates():
    observations = [
        BenchmarkObservation(
            scenario="worker-8001",
            variant="A",
                feature_count=8001,
            fetch_ms=12,
            parse_ms=50,
            render_ms=100,
            interactive_ms=200,
            long_task_ms=80,
            pointer_delay_ms=6,
            memory_delta_bytes=10,
            render_success=True,
            feature_count_match=True,
            extent_match=True,
            worker_process_ms=0,
            feature_convert_ms=90,
            first_visible_ms=180,
        ),
        BenchmarkObservation(
            scenario="worker-8001",
            variant="A",
            feature_count=8001,
            fetch_ms=14,
            parse_ms=70,
            render_ms=120,
            interactive_ms=240,
            long_task_ms=100,
            pointer_delay_ms=8,
            memory_delta_bytes=14,
            render_success=True,
            feature_count_match=True,
            extent_match=True,
            worker_process_ms=0,
            feature_convert_ms=100,
            first_visible_ms=210,
        ),
        BenchmarkObservation(
            scenario="worker-8001",
            variant="B",
            feature_count=8001,
            fetch_ms=11,
            parse_ms=30,
            render_ms=90,
            interactive_ms=150,
            long_task_ms=40,
            pointer_delay_ms=4,
            memory_delta_bytes=9,
            render_success=True,
            feature_count_match=True,
            extent_match=True,
            worker_process_ms=25,
            feature_convert_ms=35,
            first_visible_ms=110,
        ),
    ]

    report = summarize_observations(observations)

    assert report["worker-8001"]["A"]["sample_count"] == 2
    assert report["worker-8001"]["A"]["median"]["interactive_ms"] == 220
    assert report["worker-8001"]["A"]["p95"]["interactive_ms"] == 240
    assert report["worker-8001"]["A"]["correctness"] == {
        "render_success_rate": 1.0,
        "feature_count_match_rate": 1.0,
        "extent_match_rate": 1.0,
    }


def test_summarize_observations_rejects_mismatched_scenario_metadata():
    observation = BenchmarkObservation(
        scenario="direct-4999",
        variant="A",
        feature_count=5000,
        fetch_ms=1,
        parse_ms=1,
        render_ms=1,
        interactive_ms=1,
        long_task_ms=0,
        pointer_delay_ms=0,
        memory_delta_bytes=0,
        render_success=True,
        feature_count_match=True,
        extent_match=True,
        worker_process_ms=0,
        feature_convert_ms=0,
        first_visible_ms=0,
    )

    with pytest.raises(ValueError, match="scenario metadata"):
        summarize_observations([observation])


def test_observation_rejects_negative_measurements():
    with pytest.raises(ValueError, match="non-negative"):
        BenchmarkObservation(
            scenario="direct-4999",
            variant="A",
            feature_count=4999,
            fetch_ms=-1,
            parse_ms=1,
            render_ms=1,
            interactive_ms=1,
            long_task_ms=1,
            pointer_delay_ms=1,
            memory_delta_bytes=1,
            render_success=True,
            feature_count_match=True,
            extent_match=True,
            worker_process_ms=0,
            feature_convert_ms=1,
            first_visible_ms=2,
        )


def test_render_report_is_a_template_until_real_observations_are_supplied():
    markdown = render_report([], generated_at="2026-08-27T00:00:00Z")

    assert "4999" in markdown
    assert "5000" in markdown
    assert "8001" in markdown
    assert "30001" in markdown
    assert "2.84" not in markdown
    assert "1.69" not in markdown
    assert "待填充" in markdown


def test_render_report_contains_machine_readable_observations():
    observation = BenchmarkObservation(
        scenario="direct-4999",
        variant="A",
        feature_count=4999,
        fetch_ms=1,
        parse_ms=2,
        render_ms=3,
        interactive_ms=4,
        long_task_ms=5,
        pointer_delay_ms=6,
        memory_delta_bytes=7,
        render_success=True,
        feature_count_match=True,
        extent_match=True,
        worker_process_ms=0,
        feature_convert_ms=0,
        first_visible_ms=0,
    )

    markdown = render_report([observation], generated_at="2026-08-27T00:00:00Z")

    assert "| direct-4999 | A | 4999 | direct | 1 |" in markdown
    assert "render_success" in markdown
    json_start = markdown.index("```json") + len("```json")
    json_end = markdown.index("```", json_start)
    payload = json.loads(markdown[json_start:json_end].strip())
    assert payload["observations"][0]["interactive_ms"] == 4


def test_observation_preserves_fixture_provenance_and_selected_strategy():
    observation = BenchmarkObservation(
        scenario="worker-8001",
        variant="B",
        feature_count=8001,
        fetch_ms=1,
        parse_ms=0,
        render_ms=3,
        interactive_ms=4,
        long_task_ms=5,
        pointer_delay_ms=6,
        memory_delta_bytes=7,
        render_success=True,
        feature_count_match=True,
        extent_match=True,
        worker_process_ms=8,
        feature_convert_ms=9,
        first_visible_ms=2,
        strategy="worker",
        geometry_type="LineString",
        coordinate_count=15003,
        geojson_bytes=123456,
        bbox=(116.0, 39.8, 116.8, 40.4),
        seed=20260827,
    )

    payload = observation.to_dict()

    assert payload["strategy"] == "worker"
    assert payload["geometry_type"] == "LineString"
    assert payload["coordinate_count"] == 15003
    assert payload["geojson_bytes"] == 123456
    assert payload["bbox"] == (116.0, 39.8, 116.8, 40.4)
    assert payload["seed"] == 20260827


def test_mvt_observation_records_that_correctness_is_scoped_to_visible_tiles():
    observation = BenchmarkObservation(
        scenario="mvt-30001",
        variant="B",
        feature_count=30001,
        fetch_ms=1,
        parse_ms=0,
        render_ms=3,
        interactive_ms=4,
        long_task_ms=5,
        pointer_delay_ms=6,
        memory_delta_bytes=7,
        render_success=True,
        feature_count_match=True,
        extent_match=True,
        worker_process_ms=0,
        feature_convert_ms=8,
        first_visible_ms=2,
        strategy="mvt",
        correctness_scope="visible_tiles",
    )

    assert observation.to_dict()["correctness_scope"] == "visible_tiles"


def test_observation_rejects_strategy_that_does_not_match_scenario():
    with pytest.raises(ValueError, match="strategy"):
        BenchmarkObservation(
            scenario="worker-8001",
            variant="B",
            feature_count=8001,
            fetch_ms=1,
            parse_ms=0,
            render_ms=3,
            interactive_ms=4,
            long_task_ms=5,
            pointer_delay_ms=6,
            memory_delta_bytes=7,
            render_success=True,
            feature_count_match=True,
            extent_match=True,
            worker_process_ms=8,
            feature_convert_ms=9,
            first_visible_ms=2,
            strategy="direct",
        )


def test_render_report_shows_median_p95_and_correctness_in_summary_table():
    observation = BenchmarkObservation(
        scenario="direct-4999",
        variant="A",
        feature_count=4999,
        fetch_ms=1,
        parse_ms=2,
        render_ms=3,
        interactive_ms=4,
        long_task_ms=5,
        pointer_delay_ms=6,
        memory_delta_bytes=7,
        render_success=True,
        feature_count_match=True,
        extent_match=True,
        worker_process_ms=0,
        feature_convert_ms=0,
        first_visible_ms=0,
    )

    markdown = render_report([observation], generated_at="2026-08-27T00:00:00Z")

    assert "## 统计汇总" in markdown
    assert "| direct-4999 | A | 1 | 4 | 4 | 1.0 | 1.0 | 1.0 |" in markdown


def test_render_report_explains_real_ab_changes_without_precomputed_claims():
    observations = [
        BenchmarkObservation(
            scenario="worker-8001",
            variant=variant,
            feature_count=8001,
            fetch_ms=1,
            parse_ms=2,
            render_ms=3,
            interactive_ms=interactive,
            long_task_ms=long_task,
            pointer_delay_ms=0,
            memory_delta_bytes=0,
            render_success=True,
            feature_count_match=True,
            extent_match=True,
            worker_process_ms=worker,
            feature_convert_ms=1,
            first_visible_ms=4,
        )
        for variant, interactive, long_task, worker in (
            ("A", 100, 80, 0),
            ("B", 120, 40, 20),
        )
    ]

    markdown = render_report(observations, generated_at="2026-08-27T00:00:00Z")

    assert "## A/B 变化" in markdown
    assert "| worker-8001 | interactive_ms | 20.0% |" in markdown
    assert "| worker-8001 | long_task_ms | -50.0% |" in markdown


def test_memory_delta_can_be_negative_after_garbage_collection():
    observation = BenchmarkObservation(
        scenario="direct-4999",
        variant="A",
        feature_count=4999,
        fetch_ms=1,
        parse_ms=2,
        render_ms=3,
        interactive_ms=4,
        long_task_ms=5,
        pointer_delay_ms=6,
        memory_delta_bytes=-7,
        render_success=True,
        feature_count_match=True,
        extent_match=True,
        worker_process_ms=0,
        feature_convert_ms=0,
        first_visible_ms=0,
    )

    assert observation.memory_delta_bytes == -7


def test_browser_case_is_json_compatible_and_contains_matching_fixture():
    case = browser_case(30001)

    assert case["scenario"]["optimized_strategy"] == "mvt"
    assert case["fixture"]["metadata"]["feature_count"] == 30001
    assert case["fixture"]["metadata"]["coordinate_count"] == 30001 * 3
    assert case["fixture"]["metadata"]["geojson_bytes"] > 0
    json.dumps(case)


def test_fixture_json_is_a_compact_feature_collection_for_browser_routes():
    serialized = fixture_json(4999)
    payload = json.loads(serialized)

    assert payload["type"] == "FeatureCollection"
    assert len(payload["features"]) == 4999
    assert payload["metadata"]["coordinate_count"] == 4999 * 3
    assert payload["metadata"]["geojson_bytes"] == len(serialized.encode("utf-8"))


def test_mvt_fixture_distributes_large_dataset_across_visible_tiles():
    import mapbox_vector_tile

    tiles = _mvt_tile_layout(30001)
    visible_tiles = [
        tile
        for tile in tiles
        if tile in _mvt_tile_layout(30001, bbox=DEFAULT_BBOX)
    ]
    decoded_counts = []
    decoded_ids = set()
    for tile in tiles:
        payload = _mvt_fixture_for_request(30001, tile.z, tile.x, tile.y)
        decoded = mapbox_vector_tile.decode(payload)
        features = decoded["benchmark"]["features"]
        decoded_counts.append(len(features))
        decoded_ids.update(feature["id"] for feature in features)

    assert len(tiles) > 1
    assert len(visible_tiles) < len(tiles)
    assert max(decoded_counts) <= 5000
    assert sum(decoded_counts) == 30001
    assert len(decoded_ids) == 30001


def test_load_observations_reads_playwright_json_export(tmp_path):
    observation = BenchmarkObservation(
        scenario="direct-4999",
        variant="A",
        feature_count=4999,
        fetch_ms=1,
        parse_ms=2,
        render_ms=3,
        interactive_ms=4,
        long_task_ms=5,
        pointer_delay_ms=6,
        memory_delta_bytes=7,
        render_success=True,
        feature_count_match=True,
        extent_match=True,
        worker_process_ms=0,
        feature_convert_ms=0,
        first_visible_ms=0,
    )
    source = tmp_path / "observations.json"
    source.write_text(
        json.dumps({"observations": [observation.to_dict()]}), encoding="utf-8"
    )

    loaded = load_observations(source)

    assert loaded == [observation]


class FakePlaywrightPage:
    def __init__(self):
        self.init_scripts = []
        self.evaluated = []

    def add_init_script(self, *, script):
        self.init_scripts.append(script)

    def evaluate(self, expression, argument=None):
        self.evaluated.append((expression, argument))
        return {"fetch_ms": 2, "long_task_ms": 3}


def test_collect_browser_metrics_installs_observer_and_returns_timing_fields():
    page = FakePlaywrightPage()

    install_browser_metrics(page)
    metrics = collect_browser_metrics(page)

    assert page.init_scripts
    assert "PerformanceObserver" in page.init_scripts[0]
    assert metrics == {"fetch_ms": 2, "long_task_ms": 3}


def test_write_report_creates_report_in_requested_project_path(tmp_path):
    from tests.performance.render_benchmark import write_report

    output_path = write_report(tmp_path / "render-ab-report.md")

    assert output_path.exists()
    assert "待填充" in output_path.read_text(encoding="utf-8")


def test_vite_port_ignores_the_frontend_path_prefix():
    assert _vite_port("http://127.0.0.1:5220/static/frontend") == 5220


def test_vite_health_url_has_a_trailing_slash_for_the_dev_root():
    assert _vite_health_url("http://127.0.0.1:5220/static/frontend") == (
        "http://127.0.0.1:5220/static/frontend/"
    )


def test_mvt_fixture_returns_features_only_for_the_benchmark_layout():
    import mapbox_vector_tile

    canonical = _mvt_tile_layout(5)[0]
    payload = mapbox_vector_tile.decode(
        _mvt_fixture_for_request(5, canonical.z, canonical.x, canonical.y)
    )
    empty_payload = mapbox_vector_tile.decode(
        _mvt_fixture_for_request(5, 8, canonical.x, canonical.y)
    )

    assert len(payload["benchmark"]["features"]) == 1
    assert empty_payload["benchmark"]["features"] == []


def test_vite_base_url_preserves_path_when_port_changes():
    assert _vite_base_url_for_port(
        "http://127.0.0.1:5220/static/frontend", 5240
    ) == "http://127.0.0.1:5240/static/frontend"


def test_benchmark_url_carries_fixture_provenance_to_the_browser():
    url = _benchmark_url(
        "http://127.0.0.1:5220/static/frontend",
        5001,
        "B",
        {
            "geometry_type": "LineString",
            "coordinate_count": 15003,
            "geojson_bytes": 123456,
            "bbox": [116.0, 39.8, 116.8, 40.4],
        },
        20260827,
    )

    assert url == (
        "http://127.0.0.1:5220/static/frontend/benchmark?"
        "count=5001&variant=B&seed=20260827&geometry_type=LineString&"
        "coordinate_count=15003&geojson_bytes=123456&"
        "bbox=116.0%2C39.8%2C116.8%2C40.4"
    )
