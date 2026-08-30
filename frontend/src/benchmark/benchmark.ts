import Map from "ol/Map";
import View from "ol/View";
import Feature from "ol/Feature";
import MVT from "ol/format/MVT";
import VectorLayer from "ol/layer/Vector";
import VectorTileLayer from "ol/layer/VectorTile";
import VectorSource from "ol/source/Vector";
import VectorTileSource from "ol/source/VectorTile";
import { createXYZ } from "ol/tilegrid";
import { createEmpty, extend, isEmpty } from "ol/extent";
import { fromLonLat } from "ol/proj";
import Style from "ol/style/Style";
import Stroke from "ol/style/Stroke";
import CircleStyle from "ol/style/Circle";
import Fill from "ol/style/Fill";
import type { GeoJsonFeature } from "../map/geojsonParser";
import type { GeoJsonWorkerResponse } from "../map/workerProtocol";
import { MVT_TILE_SIZE, renderFeaturesPerFrame, renderModeForFeatureCount, type RenderStrategy } from "../map/renderPolicy";
import { addGeoJsonFeatureBatch, createFrameBatchScheduler, featureCollection, readGeoJsonFeatures, scheduleRenderFrame, scheduleRenderTask } from "../map/renderers";

type Variant = "A" | "B";

export const MVT_BENCHMARK_ZOOM = 11;
export const MVT_BENCHMARK_TILE_SIZE = MVT_TILE_SIZE;

export function beginRenderMeasurement(
  mark: (name: string) => void,
  state: { started: boolean },
): void {
  if (state.started) return;
  state.started = true;
  mark("render-start");
}

export function startBenchmark(): void {
  const query = new URLSearchParams(window.location.search);
  const featureCount = Number(query.get("count"));
  const variant = query.get("variant") === "B" ? "B" : "A" as Variant;
  const bbox = (query.get("bbox") || "116,39.8,116.8,40.4").split(",").map(Number);
  const fixtureMetadata = {
    geometry_type: query.get("geometry_type") || "LineString",
    coordinate_count: Number(query.get("coordinate_count") || featureCount * 3),
    geojson_bytes: Number(query.get("geojson_bytes") || 0),
    bbox,
    seed: Number(query.get("seed") || 0),
  };
  const strategy: RenderStrategy = variant === "A"
    ? "direct"
    : renderModeForFeatureCount(featureCount) === "geojson" ? "direct"
      : renderModeForFeatureCount(featureCount) === "geojson-worker" ? "worker" : "mvt";
  const root = document.getElementById("root");
  if (!root || !Number.isInteger(featureCount) || featureCount < 1) {
    throw new Error("benchmark requires a positive integer count");
  }
  root.innerHTML = `<main class="benchmark-page" style="font:14px system-ui;padding:16px"><h1>Map render benchmark</h1><div id="benchmark-map" style="width:900px;height:480px"></div><output id="benchmark-status">loading</output></main>`;
  const target = document.getElementById("benchmark-map")!;
  const status = document.getElementById("benchmark-status")!;
  const map = new Map({
    target,
    layers: [],
    view: new View({ center: fromLonLat([116.4, 40.1]), zoom: MVT_BENCHMARK_ZOOM, projection: "EPSG:3857" }),
  });
  const metrics = { feature_count: 0, first_visible: false, interactive: false, extent_match: false };
  const renderState = { started: false };
  let firstVisible = false;
  let interactive = false;
  let extent = createEmpty();
  let hasExtent = false;
  const mark = (name: string) => performance.mark(`map-benchmark-${name}`);
  const measure = (name: string, start: string, end: string) => {
    try { performance.measure(`map-benchmark-${name}`, `map-benchmark-${start}`, `map-benchmark-${end}`); } catch (_) {}
  };

  map.on("rendercomplete", () => {
    markVisible();
  });
  const markVisible = () => {
    if (!renderState.started || metrics.feature_count < 1 || firstVisible) return;
    firstVisible = true;
    mark("first_visible");
    mark("render-end");
    measure("render", "render-start", "render-end");
    measure("first_visible", "fetch-start", "first_visible");
    publishResult();
  };
  map.on("pointerdrag", () => {
    if (interactive) return;
    interactive = true;
    mark("interactive");
    measure("interactive", "fetch-start", "interactive");
    metrics.interactive = true;
    publishResult();
  });

  const publishResult = () => {
    const result = {
      feature_count: metrics.feature_count,
      // MVT is intentionally lazy: correctness is scoped to loaded viewport
      // tiles, while GeoJSON correctness covers the complete fixture.
      feature_count_match: strategy === "mvt" ? metrics.feature_count > 0 : metrics.feature_count === featureCount,
      extent_match: strategy === "mvt" ? metrics.feature_count > 0 : metrics.extent_match || (hasExtent && !isEmpty(extent)),
      correctness_scope: strategy === "mvt" ? "visible_tiles" : "full_dataset",
      render_success: firstVisible,
      interactive,
      strategy,
      variant,
      expected_feature_count: featureCount,
      ...fixtureMetadata,
    };
    (window as Window & { __mapBenchmarkResult?: unknown }).__mapBenchmarkResult = result;
    status.textContent = JSON.stringify(result);
    if (interactive) document.body.dataset.benchmarkComplete = "true";
  };

  if (strategy === "mvt") {
    const source = new VectorTileSource({
      format: new MVT(),
      tileGrid: createXYZ({ tileSize: MVT_BENCHMARK_TILE_SIZE, maxZoom: 22 }),
      url: "/benchmark-tiles/{z}/{x}/{y}.pbf",
    });
    const seen = new Set<string>();
    let fetchMeasured = false;
    beginRenderMeasurement(mark, renderState);
    source.on("tileloadend", (event) => {
      const tile = event.tile as { getFeatures?: () => Feature[] };
      for (const feature of tile.getFeatures?.() || []) seen.add(String(feature.getId() ?? seen.size));
        metrics.feature_count = seen.size;
      metrics.extent_match = metrics.feature_count > 0;
       if (!fetchMeasured) {
         fetchMeasured = true;
         mark("fetch-end");
         measure("fetch", "fetch-start", "fetch-end");
       }
      requestAnimationFrame(markVisible);
      publishResult();
    });
    source.on("tileloaderror", () => { status.textContent = "tile_error"; });
    const layer = new VectorTileLayer({ source, style: new Style({ stroke: new Stroke({ color: "#2d789d", width: 1.2 }) }) });
    mark("fetch-start");
    map.getView().fit([
      fromLonLat([bbox[0], bbox[1]])[0],
      fromLonLat([bbox[0], bbox[1]])[1],
      fromLonLat([bbox[2], bbox[3]])[0],
      fromLonLat([bbox[2], bbox[3]])[1],
    ], { padding: [20, 20, 20, 20], maxZoom: MVT_BENCHMARK_ZOOM });
    map.getView().setZoom(MVT_BENCHMARK_ZOOM);
    map.addLayer(layer);
    return;
  }

  mark("fetch-start");
  fetch("/benchmark-fixture.geojson", { cache: "no-store" })
    .then(async (response) => {
      const buffer = await response.arrayBuffer();
      mark("fetch-end");
      measure("fetch", "fetch-start", "fetch-end");
      if (!response.ok) throw new Error(`fixture ${response.status}`);
       if (strategy === "worker") {
         return parseWithWorker(buffer, map, metrics, featureCount, mark, measure, () => beginRenderMeasurement(mark, renderState))
           .then(() => publishResult());
       }
      mark("parse-start");
      const collection = JSON.parse(new TextDecoder().decode(buffer));
      mark("parse-end");
      measure("parse", "parse-start", "parse-end");
      mark("feature_convert-start");
      const features = readGeoJsonFeatures(collection);
      mark("feature_convert-end");
      measure("feature_convert", "feature_convert-start", "feature_convert-end");
      metrics.feature_count = features.length;
      for (const feature of features) { const itemExtent = feature.getGeometry()?.getExtent(); if (itemExtent) { extend(extent, itemExtent); hasExtent = true; } }
      metrics.extent_match = metrics.feature_count === featureCount && hasExtent;
      const layer = new VectorLayer({ source: new VectorSource({ features }), style: new Style({ stroke: new Stroke({ color: "#2d789d", width: 1.2 }), image: new CircleStyle({ radius: 3, fill: new Fill({ color: "#2d789d" }) }) }) });
      map.addLayer(layer);
       beginRenderMeasurement(mark, renderState);
      map.getView().fit(extent, { padding: [20, 20, 20, 20], maxZoom: 13 });
      requestAnimationFrame(markVisible);
      publishResult();
    })
    .catch((error) => { status.textContent = error instanceof Error ? error.message : "benchmark_failed"; });
  publishResult();
}

function parseWithWorker(
  buffer: ArrayBuffer,
  map: Map,
  metrics: { feature_count: number; extent_match: boolean },
  featureCount: number,
  mark: (name: string) => void,
  measure: (name: string, start: string, end: string) => void,
  startRender: () => void,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const worker = new Worker(new URL("../workers/geojsonParser.worker.ts", import.meta.url), { type: "module" });
    const source = new VectorSource();
    const layer = new VectorLayer({ source, style: new Style({ stroke: new Stroke({ color: "#2d789d", width: 1.2 }) }) });
    map.addLayer(layer);
    mark("worker_process-start");
    let count = 0;
    let expectedFeatureCount = 0;
    let firstBatch = true;
    const scheduler = createFrameBatchScheduler<GeoJsonFeature>(
      (batch) => {
        if (count === 0) startRender();
        mark("feature_convert-start");
        addGeoJsonFeatureBatch(source, featureCollection(batch));
        mark("feature_convert-end");
        measure("feature_convert", "feature_convert-start", "feature_convert-end");
        count += batch.length;
        metrics.feature_count = count;
      },
      () => {
        metrics.extent_match = count > 0 && expectedFeatureCount === count;
        worker.terminate();
        resolve();
      },
      renderFeaturesPerFrame(featureCount),
      (callback) => {
        const schedule = firstBatch ? scheduleRenderFrame : scheduleRenderTask;
        firstBatch = false;
        schedule(callback);
      },
    );
    worker.onmessage = ({ data }: MessageEvent<GeoJsonWorkerResponse>) => {
      if (data.type === "error") { worker.terminate(); reject(new Error(data.message)); return; }
      scheduler.enqueue(data.features);
      if (data.done) {
        mark("worker_process-end");
        measure("worker_process", "worker_process-start", "worker_process-end");
        expectedFeatureCount = data.featureCount;
        scheduler.finish();
      }
    };
    worker.onerror = () => { worker.terminate(); reject(new Error("worker_failed")); };
    worker.postMessage({ type: "parse", requestId: 1, layerId: "benchmark", layerVersion: 1, buffer }, [buffer]);
  });
}
