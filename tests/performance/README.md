# Rendering A/B Benchmark Toolkit

This directory contains offline benchmark helpers. They do not change the
production renderer or SSE implementation.

## Playwright usage

Install observers before navigation, serve a deterministic fixture through a
route, and add marks around the application phases:

```python
from tests.performance.render_benchmark import (
    browser_case,
    browser_mark,
    collect_browser_metrics,
    fixture_json,
    install_browser_metrics,
)

install_browser_metrics(page)
page.route(
    "**/benchmark-fixture.geojson",
    lambda route: route.fulfill(
        body=fixture_json(8001),
        content_type="application/geo+json",
    ),
)
page.goto("http://127.0.0.1:8001/mapping/")
browser_mark(page, "map-benchmark-fetch-start")
# Run the A or B harness here.
browser_mark(page, "map-benchmark-fetch-end")
metrics = collect_browser_metrics(page)
case = browser_case(8001)
```

The standard phase names are `fetch`, `parse`, `worker_process`,
`feature_convert`, `render`, `first_visible`, and `interactive`. A phase is
measured by the matching `map-benchmark-{phase}-start` and
`map-benchmark-{phase}-end` marks. Missing marks return `None`; they must not be
converted to a zero before creating a `BenchmarkObservation`.

## Report generation

## Real browser runner

The runner opens the project Vite benchmark page and measures the actual
OpenLayers Canvas path. Variant A forces full GeoJSON on the main thread;
variant B uses the production direct/Worker/MVT policy. It serves deterministic
fixtures through Playwright, so no external GIS or LLM service is needed.

Run the required experiment with five warmups and thirty measured samples per
size and variant:

```powershell
F:\FL\anaconda_20241031\envs\ggy\python.exe tests/performance/run_render_ab.py --start-vite
```

For a smoke run that exercises all configured boundaries without filling the final
report with under-sampled numbers:

```powershell
F:\FL\anaconda_20241031\envs\ggy\python.exe tests/performance/run_render_ab.py --start-vite --warmup 0 --samples 1 --output tests/performance/smoke-observations.json --report docs/performance/smoke-render-ab-report.md
```

Only the required experiment should be used for resume claims. The runner
fails when a required browser metric is missing instead of replacing it with a
made-up zero.

The report generator accepts a JSON file with an `observations` list. Each item
must contain the fields of `BenchmarkObservation`, including the three
correctness fields. It computes median and nearest-rank P95 separately for A
and B:

```powershell
python -m tests.performance.render_benchmark `
  --observations tests/performance/observations.json `
  --report docs/performance/render-ab-report.md
```

With no `--observations`, the command writes a blank report template. It never
invents timing results.
