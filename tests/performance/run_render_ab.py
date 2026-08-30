"""Run the real browser A/B renderer benchmark against the Vite benchmark page."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlencode, urlsplit, urlunsplit

import mercantile
from pyproj import Transformer
from playwright.sync_api import sync_playwright


MVT_BENCHMARK_ZOOM = 11
MVT_DATASET_BBOX = (114.5, 38.5, 119.5, 42.0)

try:
    from tests.performance.render_benchmark import (
        DEFAULT_SEED,
        DEFAULT_BBOX,
        REQUIRED_FEATURE_COUNTS,
        BenchmarkObservation,
        browser_case,
        collect_browser_metrics,
        fixture_json,
        install_browser_metrics,
        render_report,
    )
except ModuleNotFoundError:  # Direct execution from the project root.
    from render_benchmark import (
        DEFAULT_SEED,
        DEFAULT_BBOX,
        REQUIRED_FEATURE_COUNTS,
        BenchmarkObservation,
        browser_case,
        collect_browser_metrics,
        fixture_json,
        install_browser_metrics,
        render_report,
    )


def _mvt_fixture(
    feature_count: int,
    *,
    z: int = 9,
    x: Optional[int] = None,
    y: Optional[int] = None,
    id_offset: int = 0,
) -> bytes:
    """Encode all synthetic ids into one valid tile for the browser harness."""
    import mapbox_vector_tile

    tile = mercantile.tile(116.4, 40.1, z)
    if x is not None or y is not None:
        if x is None or y is None:
            raise ValueError("x and y must be provided together")
        tile = mercantile.Tile(x=x, y=y, z=z)
    bounds = mercantile.xy_bounds(tile.x, tile.y, tile.z)
    center_x = (bounds.left + bounds.right) / 2
    center_y = (bounds.bottom + bounds.top) / 2
    features = []
    for index in range(feature_count):
        offset = ((index % 100) + 1) * (bounds.right - bounds.left) / 1000
        features.append(
            {
                "id": id_offset + index + 1,
                "geometry": {
                    "type": "LineString",
                    "coordinates": [
                        [center_x + offset, center_y],
                        [center_x + offset, center_y + offset],
                    ],
                },
                "properties": {"synthetic_id": index + 1},
            }
        )
    return mapbox_vector_tile.encode(
        [{"name": "benchmark", "features": features}],
        default_options={
            "quantize_bounds": (bounds.left, bounds.bottom, bounds.right, bounds.top),
            "extents": 4096,
            "y_coord_down": True,
        },
    )


def _mvt_tile_layout(
    feature_count: int,
    *,
    z: int = MVT_BENCHMARK_ZOOM,
    bbox: Sequence[float] = MVT_DATASET_BBOX,
) -> List[Any]:
    """Return the fixed visible tile layout used by the MVT benchmark."""
    if feature_count < 1:
        raise ValueError("feature_count must be positive")
    if len(bbox) != 4 or bbox[0] >= bbox[2] or bbox[1] >= bbox[3]:
        raise ValueError("bbox must be [min_x, min_y, max_x, max_y]")
    return list(mercantile.tiles(*bbox, zooms=z))


def _mvt_fixture_for_request(feature_count: int, z: int, x: int, y: int) -> bytes:
    """Distribute the large fixture across visible tiles instead of one giant tile."""
    tiles = _mvt_tile_layout(feature_count, z=MVT_BENCHMARK_ZOOM)
    if z != MVT_BENCHMARK_ZOOM or (x, y) not in {(tile.x, tile.y) for tile in tiles}:
        import mapbox_vector_tile

        bounds = mercantile.xy_bounds(x, y, z)
        return mapbox_vector_tile.encode(
            [{"name": "benchmark", "features": []}],
            default_options={
                "quantize_bounds": (
                    bounds.left,
                    bounds.bottom,
                    bounds.right,
                    bounds.top,
                ),
                "extents": 4096,
                "y_coord_down": True,
            },
        )
    tile_index = next(index for index, tile in enumerate(tiles) if (tile.x, tile.y) == (x, y))
    base, remainder = divmod(feature_count, len(tiles))
    tile_count = base + (1 if tile_index < remainder else 0)
    id_offset = tile_index * base + min(tile_index, remainder)
    return _mvt_fixture(tile_count, z=z, x=x, y=y, id_offset=id_offset)


def _wait_for_vite(
    base_url: str, process: subprocess.Popen[bytes], timeout: float = 30
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Vite exited with code {process.returncode}")
        try:
            with urllib.request.urlopen(_vite_health_url(base_url), timeout=1):
                return
        except Exception:
            time.sleep(0.25)
    raise TimeoutError(f"Vite did not start at {base_url}")


def _vite_port(base_url: str) -> int:
    """Return the Vite port from the benchmark base URL."""
    parsed = urlsplit(base_url)
    if parsed.port is None:
        raise ValueError("base_url must include a valid port")
    return parsed.port


def _vite_health_url(base_url: str) -> str:
    """Return a URL that Vite serves for its configured base root."""
    return base_url.rstrip("/") + "/"


def _vite_base_url_for_port(base_url: str, port: int) -> str:
    """Replace only the port while preserving the configured Vite base path."""
    parsed = urlsplit(base_url)
    hostname = parsed.hostname or "127.0.0.1"
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    return urlunsplit(
        (
            parsed.scheme,
            f"{hostname}:{int(port)}",
            parsed.path,
            parsed.query,
            parsed.fragment,
        )
    )


def _find_available_port(start_port: int, *, attempts: int = 20) -> int:
    """Find a local port for an owned Vite process without taking over callers' servers."""
    for port in range(int(start_port), int(start_port) + attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise RuntimeError(
        f"no available Vite port in range {start_port}-{start_port + attempts - 1}"
    )


def _metric(metrics: Dict[str, Any], name: str, *, applicable: bool = True) -> float:
    value = metrics.get(name)
    if value is None:
        if not applicable:
            return 0.0
        raise RuntimeError(f"browser did not expose required metric: {name}")
    return float(value)


def _browser_executable() -> Optional[str]:
    candidates = [
        os.environ.get("MAP_BENCHMARK_BROWSER"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        shutil.which("chrome.exe"),
        shutil.which("msedge.exe"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    return None


def _benchmark_url(
    base_url: str,
    count: int,
    variant: str,
    metadata: Dict[str, Any],
    seed: int,
) -> str:
    """Build a self-describing URL so browser results retain fixture provenance."""
    query = urlencode(
        {
            "count": count,
            "variant": variant,
            "seed": seed,
            "geometry_type": metadata["geometry_type"],
            "coordinate_count": metadata["coordinate_count"],
            "geojson_bytes": metadata["geojson_bytes"],
            "bbox": ",".join(str(value) for value in metadata["bbox"]),
        }
    )
    return f"{base_url}/benchmark?{query}"


def _run_case(
    page: Any,
    base_url: str,
    count: int,
    variant: str,
    seed: int,
    feature_counts: Iterable[int] = REQUIRED_FEATURE_COUNTS,
) -> BenchmarkObservation:
    install_browser_metrics(page)
    fixture = fixture_json(count, seed=seed)
    fixture_payload = json.loads(fixture)
    fixture_metadata = fixture_payload["metadata"]
    diagnostics: Dict[str, List[str]] = {
        "console": [],
        "page_errors": [],
        "request_failed": [],
    }

    page.on(
        "console",
        lambda message: diagnostics["console"].append(
            f"{message.type}: {message.text}"
        ),
    )
    page.on(
        "pageerror",
        lambda error: diagnostics["page_errors"].append(str(error)),
    )
    page.on(
        "requestfailed",
        lambda request: diagnostics["request_failed"].append(
            f"{request.url}: {request.failure}"
        ),
    )

    def route_handler(route: Any) -> None:
        if route.request.url.endswith("benchmark-fixture.geojson"):
            route.fulfill(body=fixture, content_type="application/geo+json")
            return
        path_parts = urlsplit(route.request.url).path.rstrip("/").split("/")
        try:
            z = int(path_parts[-3])
            x = int(path_parts[-2])
            y = int(path_parts[-1][:-4])
        except (IndexError, ValueError):
            route.fulfill(status=400, body=b"invalid tile", content_type="text/plain")
            return
        route.fulfill(
            body=_mvt_fixture_for_request(count, z, x, y),
            content_type="application/vnd.mapbox-vector-tile",
        )

    page.route("**/benchmark-fixture.geojson", route_handler)
    page.route("**/benchmark-tiles/**/*.pbf", route_handler)
    page.set_default_timeout(60_000)
    page.set_default_navigation_timeout(60_000)
    url = _benchmark_url(base_url, count, variant, fixture_metadata, seed)
    try:
        page.goto(url, wait_until="domcontentloaded")
    except Exception as exc:
        raise RuntimeError(
            f"benchmark navigation failed for {count}/{variant}: {url}; "
            f"page_status={_page_status(page)}; { _diagnostic_text(diagnostics) }"
        ) from exc
    _wait_for_result(page, count, variant, diagnostics)
    box = page.locator("#benchmark-map").bounding_box()
    if not box:
        raise RuntimeError("benchmark map has no layout box")
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.mouse.down()
    page.mouse.move(box["x"] + box["width"] / 2 + 8, box["y"] + box["height"] / 2 + 8)
    page.mouse.up()
    page.wait_for_function("window.__mapBenchmarkResult?.interactive === true")
    page.wait_for_function("window.__mapBenchmarkResult?.feature_count_match === true")
    result = page.evaluate("window.__mapBenchmarkResult")
    metrics = collect_browser_metrics(page)
    strategy = result["strategy"]
    return BenchmarkObservation(
        scenario=browser_case(count, seed=seed, feature_counts=feature_counts)["scenario"]["name"],
        variant=variant,
        feature_count=count,
        fetch_ms=_metric(metrics, "fetch_ms"),
        parse_ms=_metric(metrics, "parse_ms", applicable=strategy == "direct"),
        render_ms=_metric(metrics, "render_ms"),
        interactive_ms=_metric(metrics, "interactive_ms"),
        long_task_ms=_metric(metrics, "long_task_ms"),
        pointer_delay_ms=_metric(metrics, "pointer_delay_ms"),
        memory_delta_bytes=_metric(metrics, "memory_delta_bytes"),
        render_success=bool(result["render_success"]),
        feature_count_match=bool(result["feature_count_match"]),
        extent_match=bool(result["extent_match"]),
        worker_process_ms=_metric(
            metrics, "worker_process_ms", applicable=strategy == "worker"
        ),
        feature_convert_ms=_metric(
            metrics, "feature_convert_ms", applicable=strategy != "mvt"
        ),
        first_visible_ms=_metric(metrics, "first_visible_ms"),
        correctness_scope=str(result.get("correctness_scope", "full_dataset")),
        strategy=strategy,
        geometry_type=str(result["geometry_type"]),
        coordinate_count=int(result["coordinate_count"]),
        geojson_bytes=int(result["geojson_bytes"]),
        bbox=tuple(float(value) for value in result["bbox"]),
        seed=int(result["seed"]),
    )


def _page_status(page: Any) -> str:
    """Return benchmark status without masking the original browser error."""
    try:
        return page.locator("#benchmark-status").text_content(timeout=1) or "<empty>"
    except Exception:
        return "<unavailable>"


def _diagnostic_text(diagnostics: Dict[str, List[str]]) -> str:
    parts = []
    for name, values in diagnostics.items():
        if values:
            parts.append(f"{name}={values[-3:]}")
    return "; ".join(parts) or "browser_diagnostics=<none>"


def _wait_for_result(
    page: Any,
    count: int,
    variant: str,
    diagnostics: Dict[str, List[str]],
) -> None:
    """Wait for success but surface the page's own failure state on timeout."""
    try:
        page.wait_for_function(
            "window.__mapBenchmarkResult?.render_success === true",
            timeout=60_000,
        )
    except Exception as exc:
        raise RuntimeError(
            f"benchmark render did not become visible for {count}/{variant}; "
            f"page_status={_page_status(page)}; { _diagnostic_text(diagnostics) }"
        ) from exc


def run(
    *,
    base_url: str,
    counts: Iterable[int] = REQUIRED_FEATURE_COUNTS,
    warmup: int = 5,
    samples: int = 30,
    seed: int = DEFAULT_SEED,
    start_vite: bool = False,
) -> List[BenchmarkObservation]:
    process: Optional[subprocess.Popen[bytes]] = None
    if start_vite:
        vite_port = _find_available_port(_vite_port(base_url))
        base_url = _vite_base_url_for_port(base_url, vite_port)
        process = subprocess.Popen(
            [
                "npm.cmd" if os.name == "nt" else "npm",
                "run",
                "dev",
                "--",
                "--host",
                "127.0.0.1",
                "--port",
                str(vite_port),
            ],
            cwd=Path(__file__).parents[2] / "frontend",
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        _wait_for_vite(base_url, process)
    observations: List[BenchmarkObservation] = []
    try:
        with sync_playwright() as playwright:
            launch_options: Dict[str, Any] = {"headless": True}
            executable = _browser_executable()
            if executable:
                launch_options["executable_path"] = executable
            for count in counts:
                browser = playwright.chromium.launch(**launch_options)
                try:
                    for variant in ("A", "B"):
                        for _ in range(warmup):
                            context = browser.new_context()
                            try:
                                page = context.new_page()
                                _run_case(page, base_url, count, variant, seed, counts)
                            finally:
                                context.close()
                        for _ in range(samples):
                            context = browser.new_context()
                            try:
                                page = context.new_page()
                                observations.append(
                                    _run_case(page, base_url, count, variant, seed, counts)
                                )
                            finally:
                                context.close()
                finally:
                    browser.close()
    finally:
        if process is not None:
            process.terminate()
            process.wait(timeout=10)
    return observations


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:5200/static/frontend")
    parser.add_argument("--warmup", type=int, default=5)
    parser.add_argument("--samples", type=int, default=30)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument(
        "--counts",
        default=",".join(str(count) for count in REQUIRED_FEATURE_COUNTS),
        help="comma-separated feature counts for threshold calibration",
    )
    parser.add_argument("--start-vite", action="store_true")
    parser.add_argument(
        "--output", type=Path, default=Path("tests/performance/observations.json")
    )
    parser.add_argument(
        "--report", type=Path, default=Path("docs/performance/render-ab-report.md")
    )
    args = parser.parse_args()
    try:
        counts = tuple(int(value.strip()) for value in args.counts.split(",") if value.strip())
    except ValueError as exc:
        parser.error(f"--counts must be comma-separated positive integers: {exc}")
    observations = run(
        base_url=args.base_url,
        counts=counts,
        warmup=args.warmup,
        samples=args.samples,
        seed=args.seed,
        start_vite=args.start_vite,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            {"observations": [item.to_dict() for item in observations]},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(render_report(observations), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
