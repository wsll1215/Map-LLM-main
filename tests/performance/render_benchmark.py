"""Deterministic GIS fixtures and offline A/B benchmark helpers.

The module intentionally has no browser, Django, network, or GIS-library
dependency. A Playwright test can import the helpers, serialize a fixture, and
serve it through ``page.route`` without starting the application backend.
"""

from __future__ import annotations

import argparse
import json
import math
import random
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Union


REQUIRED_FEATURE_COUNTS: Tuple[int, ...] = (
    4999,
    5000,
    7999,
    8000,
    8001,
    10000,
    29999,
    30000,
    30001,
)
DEFAULT_SEED = 20260827
DEFAULT_BBOX = (116.0, 39.8, 116.8, 40.4)
METRIC_FIELDS: Tuple[str, ...] = (
    "fetch_ms",
    "parse_ms",
    "worker_process_ms",
    "feature_convert_ms",
    "render_ms",
    "first_visible_ms",
    "interactive_ms",
    "long_task_ms",
    "pointer_delay_ms",
    "memory_delta_bytes",
)


def _validate_feature_count(feature_count: int) -> None:
    if isinstance(feature_count, bool) or not isinstance(feature_count, int):
        raise ValueError("feature_count must be a positive integer")
    if feature_count < 1:
        raise ValueError("feature_count must be a positive integer")


def generate_geojson(
    feature_count: int,
    *,
    seed: int = DEFAULT_SEED,
    bbox: Sequence[float] = DEFAULT_BBOX,
) -> Dict[str, Any]:
    """Generate a stable, valid synthetic LineString FeatureCollection.

    Coordinates stay inside the supplied bbox. The local RNG means calls do
    not mutate global random state, which makes browser benchmark fixtures
    reproducible across test cases.
    """

    _validate_feature_count(feature_count)
    if len(bbox) != 4 or bbox[0] >= bbox[2] or bbox[1] >= bbox[3]:
        raise ValueError("bbox must be [min_x, min_y, max_x, max_y]")
    if not isinstance(seed, int):
        raise ValueError("seed must be an integer")

    min_x, min_y, max_x, max_y = (float(value) for value in bbox)
    rng = random.Random(seed)
    width = max_x - min_x
    height = max_y - min_y
    features: List[Dict[str, Any]] = []

    for index in range(feature_count):
        start_x = min_x + rng.random() * width
        start_y = min_y + rng.random() * height
        end_x = max(min_x, min(max_x, start_x + (rng.random() - 0.5) * width * 0.02))
        end_y = max(min_y, min(max_y, start_y + (rng.random() - 0.5) * height * 0.02))
        midpoint_x = (start_x + end_x) / 2
        midpoint_y = (start_y + end_y) / 2
        coordinates = [
            [round(start_x, 6), round(start_y, 6)],
            [round(midpoint_x, 6), round(midpoint_y, 6)],
            [round(end_x, 6), round(end_y, 6)],
        ]
        features.append(
            {
                "type": "Feature",
                "id": f"synthetic-road-{index + 1}",
                "properties": {
                    "synthetic_id": index + 1,
                    "road_class": "primary" if index % 5 == 0 else "secondary",
                    "seed": seed,
                },
                "geometry": {"type": "LineString", "coordinates": coordinates},
            }
        )

    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "synthetic": True,
            "seed": seed,
            "feature_count": feature_count,
            "geometry_type": "LineString",
            "coordinate_count": feature_count * 3,
            "bbox": [min_x, min_y, max_x, max_y],
        },
    }


def fixture_json(
    feature_count: int,
    *,
    seed: int = DEFAULT_SEED,
    separators: Tuple[str, str] = (",", ":"),
) -> str:
    """Serialize a fixture for a Playwright route or browser ``fetch`` test."""

    fixture = generate_geojson(feature_count, seed=seed)
    fixture["metadata"]["geojson_bytes"] = 0
    for _ in range(5):
        serialized = json.dumps(fixture, ensure_ascii=True, separators=separators)
        byte_length = len(serialized.encode("utf-8"))
        if fixture["metadata"]["geojson_bytes"] == byte_length:
            return serialized
        fixture["metadata"]["geojson_bytes"] = byte_length
    return json.dumps(fixture, ensure_ascii=True, separators=separators)


BROWSER_METRICS_INIT_SCRIPT = r"""
(() => {
  const state = window.__mapBenchmarkMetrics = {
    long_task_ms: 0,
    pointer_delay_ms: 0,
    memory_start_bytes: performance.memory?.usedJSHeapSize ?? null,
  };
  if (window.PerformanceObserver) {
    try {
      new PerformanceObserver((list) => {
        for (const entry of list.getEntries()) {
          state.long_task_ms += entry.duration;
        }
      }).observe({ type: "longtask", buffered: true });
    } catch (_) {}
    try {
      new PerformanceObserver((list) => {
        for (const entry of list.getEntries()) {
          if (["pointerdown", "pointerup", "click"].includes(entry.name)) {
            state.pointer_delay_ms = Math.max(
              state.pointer_delay_ms,
              entry.processingStart - entry.startTime,
            );
          }
        }
      }).observe({ type: "event", buffered: true, durationThreshold: 16 });
    } catch (_) {}
  }
})();
"""


def install_browser_metrics(page: Any) -> None:
    """Install observers before navigation in a Playwright page."""

    page.add_init_script(script=BROWSER_METRICS_INIT_SCRIPT)


def browser_mark(page: Any, name: str) -> None:
    """Add a named browser Performance mark from a Playwright test."""

    if not name or not isinstance(name, str):
        raise ValueError("name must be a non-empty string")
    page.evaluate("markName => performance.mark(markName)", name)


def collect_browser_metrics(page: Any) -> Dict[str, Any]:
    """Read standard marks and browser observer metrics from a Playwright page.

    Applications under test should create ``map-benchmark-{phase}-start`` and
    ``map-benchmark-{phase}-end`` marks for each phase they expose. Missing
    marks remain ``None`` so a report cannot silently turn absent measurements
    into zero-duration claims.
    """

    return page.evaluate(
        """
        () => {
          const phases = [
            "fetch", "parse", "worker_process", "feature_convert", "render",
            "first_visible", "interactive",
          ];
          const entries = performance.getEntriesByType("measure");
          const metrics = Object.fromEntries(phases.map((phase) => {
            const entry = entries.find((item) => item.name === `map-benchmark-${phase}`);
            return [`${phase}_ms`, entry ? entry.duration : null];
          }));
          const state = window.__mapBenchmarkMetrics || {};
          const memory = performance.memory?.usedJSHeapSize;
          return {
            ...metrics,
            long_task_ms: state.long_task_ms ?? 0,
            pointer_delay_ms: state.pointer_delay_ms ?? 0,
            memory_delta_bytes: memory !== undefined && state.memory_start_bytes !== null
              ? memory - state.memory_start_bytes
              : null,
          };
        }
        """
    )


def load_observations(input_path: Union[Path, str]) -> List[BenchmarkObservation]:
    """Load the JSON export produced by a Playwright benchmark runner."""

    payload = json.loads(Path(input_path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(
        payload.get("observations"), list
    ):
        raise ValueError("observation export must contain an observations list")
    observations = []
    for item in payload["observations"]:
        normalized = dict(item)
        if "bbox" in normalized:
            normalized["bbox"] = tuple(normalized["bbox"])
        observations.append(BenchmarkObservation(**normalized))
    return observations


@dataclass(frozen=True)
class RenderScenario:
    name: str
    feature_count: int
    baseline_strategy: str
    optimized_strategy: str
    variants: Tuple[str, str] = ("A", "B")
    seed: int = DEFAULT_SEED

    def strategy_for(self, variant: str) -> str:
        if variant == "A":
            return self.baseline_strategy
        if variant == "B":
            return self.optimized_strategy
        raise ValueError("variant must be A or B")

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["variants"] = list(self.variants)
        return payload


def _optimized_strategy(feature_count: int) -> str:
    if feature_count <= 8000:
        return "direct"
    if feature_count <= 30000:
        return "worker"
    return "mvt"


def build_ab_scenarios(
    feature_counts: Iterable[int] = REQUIRED_FEATURE_COUNTS,
    *,
    seed: int = DEFAULT_SEED,
) -> List[RenderScenario]:
    """Build explicit A/B cases for the requested calibration sizes."""

    counts = tuple(feature_counts)
    if not counts or any(
        isinstance(count, bool) or not isinstance(count, int) or count < 1
        for count in counts
    ):
        raise ValueError("feature_counts must contain positive integers")
    if len(set(counts)) != len(counts):
        raise ValueError("feature_counts must not contain duplicates")
    return [
        RenderScenario(
            name=f"{_optimized_strategy(feature_count)}-{feature_count}",
            feature_count=feature_count,
            baseline_strategy="direct",
            optimized_strategy=_optimized_strategy(feature_count),
            seed=seed,
        )
        for feature_count in counts
    ]


def browser_case(
    feature_count: int,
    *,
    seed: int = DEFAULT_SEED,
    feature_counts: Iterable[int] = REQUIRED_FEATURE_COUNTS,
) -> Dict[str, Any]:
    """Return JSON-compatible scenario data for a Playwright browser test."""

    scenario = next(
        item
        for item in build_ab_scenarios(feature_counts, seed=seed)
        if item.feature_count == feature_count
    )
    return {
        "scenario": scenario.to_dict(),
        "fixture": json.loads(fixture_json(feature_count, seed=seed)),
    }


@dataclass(frozen=True)
class BenchmarkObservation:
    """One browser run; correctness is deliberately recorded beside timings."""

    scenario: str
    variant: str
    feature_count: int
    fetch_ms: float
    parse_ms: float
    render_ms: float
    interactive_ms: float
    long_task_ms: float
    pointer_delay_ms: float
    memory_delta_bytes: float
    render_success: bool
    feature_count_match: bool
    extent_match: bool
    worker_process_ms: float
    feature_convert_ms: float
    first_visible_ms: float
    strategy: str = ""
    geometry_type: str = "LineString"
    coordinate_count: int = 0
    geojson_bytes: int = 0
    bbox: Tuple[float, float, float, float] = DEFAULT_BBOX
    seed: int = DEFAULT_SEED
    correctness_scope: str = "full_dataset"

    def __post_init__(self) -> None:
        _validate_feature_count(self.feature_count)
        if self.variant not in {"A", "B"}:
            raise ValueError("variant must be A or B")
        expected_strategy = (
            "direct" if self.variant == "A" else _optimized_strategy(self.feature_count)
        )
        if not self.strategy:
            object.__setattr__(self, "strategy", expected_strategy)
        elif self.strategy != expected_strategy:
            raise ValueError(f"strategy must be {expected_strategy} for {self.variant}")
        if not self.geometry_type:
            raise ValueError("geometry_type must be non-empty")
        if (
            isinstance(self.coordinate_count, bool)
            or not isinstance(self.coordinate_count, int)
            or self.coordinate_count < 0
        ):
            raise ValueError("coordinate_count must be non-negative")
        if (
            isinstance(self.geojson_bytes, bool)
            or not isinstance(self.geojson_bytes, int)
            or self.geojson_bytes < 0
        ):
            raise ValueError("geojson_bytes must be non-negative")
        if (
            len(self.bbox) != 4
            or self.bbox[0] >= self.bbox[2]
            or self.bbox[1] >= self.bbox[3]
        ):
            raise ValueError("bbox must be [min_x, min_y, max_x, max_y]")
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise ValueError("seed must be an integer")
        if self.correctness_scope not in {"full_dataset", "visible_tiles"}:
            raise ValueError("correctness_scope must be full_dataset or visible_tiles")
        for field_name in METRIC_FIELDS:
            value = getattr(self, field_name)
            if (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or (field_name != "memory_delta_bytes" and value < 0)
            ):
                raise ValueError(f"{field_name} must be non-negative")
        for field_name in ("render_success", "feature_count_match", "extent_match"):
            if not isinstance(getattr(self, field_name), bool):
                raise ValueError(f"{field_name} must be a boolean")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        raise ValueError("at least one observation is required")
    if not 0 < percentile <= 1:
        raise ValueError("percentile must be between 0 and 1")
    rank = max(1, math.ceil(percentile * len(values)))
    return sorted(values)[rank - 1]


def _metric_summary(
    observations: Sequence[BenchmarkObservation],
) -> Dict[str, Dict[str, float]]:
    return {
        "median": {
            field_name: median([getattr(item, field_name) for item in observations])
            for field_name in METRIC_FIELDS
        },
        "p95": {
            field_name: _percentile(
                [getattr(item, field_name) for item in observations], 0.95
            )
            for field_name in METRIC_FIELDS
        },
    }


def summarize_observations(
    observations: Iterable[BenchmarkObservation],
) -> Dict[str, Dict[str, Any]]:
    """Aggregate observations by scenario and A/B variant."""

    observations = list(observations)
    grouped: Dict[str, Dict[str, List[BenchmarkObservation]]] = {}
    feature_counts = (
        REQUIRED_FEATURE_COUNTS
        if not observations
        else tuple(dict.fromkeys(item.feature_count for item in observations))
    )
    scenarios = {
        scenario.name: scenario
        for scenario in build_ab_scenarios(feature_counts)
    }
    for observation in observations:
        scenario = scenarios.get(observation.scenario)
        if scenario is None or scenario.feature_count != observation.feature_count:
            raise ValueError(
                "scenario metadata must match a required feature count and name"
            )
        grouped.setdefault(observation.scenario, {}).setdefault(
            observation.variant, []
        ).append(observation)

    summaries: Dict[str, Dict[str, Any]] = {}
    for scenario, variants in grouped.items():
        summaries[scenario] = {}
        for variant, items in variants.items():
            metrics = _metric_summary(items)
            summaries[scenario][variant] = {
                "sample_count": len(items),
                **metrics,
                "correctness": {
                    "render_success_rate": sum(item.render_success for item in items)
                    / len(items),
                    "feature_count_match_rate": sum(
                        item.feature_count_match for item in items
                    )
                    / len(items),
                    "extent_match_rate": sum(item.extent_match for item in items)
                    / len(items),
                },
            }
    return summaries


def _report_rows(
    observations: Sequence[BenchmarkObservation],
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    feature_counts = (
        REQUIRED_FEATURE_COUNTS
        if not observations
        else tuple(dict.fromkeys(item.feature_count for item in observations))
    )
    for scenario in build_ab_scenarios(feature_counts):
        for variant in scenario.variants:
            matching = [
                item
                for item in observations
                if item.scenario == scenario.name and item.variant == variant
            ]
            rows.append(
                {
                    "scenario": scenario.name,
                    "variant": variant,
                    "feature_count": scenario.feature_count,
                    "strategy": scenario.strategy_for(variant),
                    "sample_count": len(matching),
                    "status": "已采集" if matching else "待填充",
                }
            )
    return rows


def _summary_rows(
    observations: Sequence[BenchmarkObservation],
) -> List[str]:
    summaries = summarize_observations(observations)
    rows: List[str] = []
    feature_counts = (
        REQUIRED_FEATURE_COUNTS
        if not observations
        else tuple(dict.fromkeys(item.feature_count for item in observations))
    )
    for scenario in build_ab_scenarios(feature_counts):
        for variant in scenario.variants:
            summary = summaries.get(scenario.name, {}).get(variant)
            if summary is None:
                rows.append(
                    f"| {scenario.name} | {variant} | 待填充 | 待填充 | 待填充 | 待填充 | 待填充 | 待填充 |"
                )
                continue
            correctness = summary["correctness"]
            rows.append(
                "| {scenario} | {variant} | {sample_count} | {median} | {p95} | "
                "{render_success_rate} | {feature_count_match_rate} | {extent_match_rate} |".format(
                    scenario=scenario.name,
                    variant=variant,
                    sample_count=summary["sample_count"],
                    median=summary["median"]["interactive_ms"],
                    p95=summary["p95"]["interactive_ms"],
                    **correctness,
                )
            )
    return rows


def _comparison_rows(
    observations: Sequence[BenchmarkObservation],
) -> List[str]:
    """Describe measured B-vs-A median changes; positive means B is slower."""
    summaries = summarize_observations(observations)
    rows: List[str] = []
    feature_counts = (
        REQUIRED_FEATURE_COUNTS
        if not observations
        else tuple(dict.fromkeys(item.feature_count for item in observations))
    )
    for scenario in build_ab_scenarios(feature_counts):
        variants = summaries.get(scenario.name, {})
        baseline = variants.get("A", {}).get("median", {})
        optimized = variants.get("B", {}).get("median", {})
        if not baseline or not optimized:
            continue
        for metric in ("first_visible_ms", "interactive_ms", "long_task_ms"):
            baseline_value = baseline.get(metric)
            optimized_value = optimized.get(metric)
            if not baseline_value:
                change = "n/a"
            else:
                change = (
                    f"{(optimized_value - baseline_value) / baseline_value * 100:.1f}%"
                )
            rows.append(f"| {scenario.name} | {metric} | {change} |")
    return rows


def render_report(
    observations: Iterable[BenchmarkObservation],
    *,
    generated_at: Optional[str] = None,
) -> str:
    """Render a Markdown report without inventing timing results."""

    collected = list(observations)
    timestamp = generated_at or datetime.now(timezone.utc).isoformat()
    rows = _report_rows(collected)
    lines = [
        "# GeoJSON 渲染 A/B 性能报告",
        "",
        "> 本报告只接受实际浏览器采样结果，不预填性能数字。",
        "",
        f"- 生成时间：`{timestamp}`",
        "- 数据：固定 seed 的合成 LineString GeoJSON",
        "- A：强制主线程直载基线；B：按规模选择 direct/worker/mvt",
        "- 统计：每个场景应预热 5 次、正式采样 30 次，报告 median 和 P95",
        "- 可交互定义：地图完成绘制，并成功响应一次拖动事件",
        "- 每条观测同时保存 strategy、geometry_type、coordinate_count、geojson_bytes、bbox 和 seed",
        "",
        "## 场景覆盖",
        "",
        "| scenario | variant | feature_count | strategy | sample_count | status |",
        "| --- | --- | ---: | --- | ---: | --- |",
    ]
    lines.extend(
        "| {scenario} | {variant} | {feature_count} | {strategy} | {sample_count} | {status} |".format(
            **row
        )
        for row in rows
    )
    lines.extend(
        [
            "",
            "## 统计汇总",
            "",
            "| scenario | variant | sample_count | median_interactive_ms | p95_interactive_ms | render_success_rate | feature_count_match_rate | extent_match_rate |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
            *_summary_rows(collected),
            "",
            "## A/B 变化",
            "",
            "> 变化率为 B 相对 A 的 median：正数表示 B 更慢，负数表示 B 更快。没有两组真实样本时不生成比较行。",
            "",
            "| scenario | metric | B 相对 A |",
            "| --- | --- | ---: |",
            *_comparison_rows(collected),
            "",
            "## 正确性字段",
            "",
            "每次采样必须同时记录 `render_success`、`feature_count_match` 和 `extent_match`；",
            "任何正确性字段不满足时，该样本不能作为成功性能结果解释。",
            "",
            "## 汇总结果",
            "",
            "将真实采样结果写入后，以下字段由生成器计算：`median`、`p95`、",
            "`render_success_rate`、`feature_count_match_rate`、`extent_match_rate`。",
            "",
            "## 原始观测 JSON",
            "",
            "```json",
            json.dumps(
                {
                    "observations": [item.to_dict() for item in collected],
                    "summaries": summarize_observations(collected),
                },
                ensure_ascii=False,
                indent=2,
            ),
            "```",
            "",
            "## 解释规则",
            "",
            "- 先比较正确性，再比较耗时；结果不正确的样本标记为失败。",
            "- 小数据边界用于验证策略切换没有越界或回退。",
            "- 超大图层的 A 组若因全量 GeoJSON 被拒绝，应记录为基线不可交付，不能补写耗时。",
            "- 简历中的性能数字必须来自本报告中的真实采样和测试环境记录。",
            "",
        ]
    )
    return "\n".join(lines)


def write_report(
    output_path: Union[Path, str],
    observations: Iterable[BenchmarkObservation] = (),
) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_report(observations), encoding="utf-8")
    return path


def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("docs/performance/render-ab-report.md"),
        help="write the report template or report generated from observations",
    )
    parser.add_argument(
        "--observations",
        type=Path,
        help="read a JSON export containing an observations list",
    )
    args = parser.parse_args()
    observations = load_observations(args.observations) if args.observations else ()
    write_report(args.report, observations)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
