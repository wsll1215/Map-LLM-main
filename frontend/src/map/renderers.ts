import GeoJSON from "ol/format/GeoJSON";
import type Feature from "ol/Feature";
import type VectorSource from "ol/source/Vector";

export type RenderableGeoJsonCollection = {
  type: "FeatureCollection";
  features: unknown[];
};

const DEFAULT_FEATURE_PROJECTION = "EPSG:3857";

/** Convert GeoJSON exactly once at the production OpenLayers boundary. */
export function readGeoJsonFeatures(
  collection: RenderableGeoJsonCollection,
  featureProjection = DEFAULT_FEATURE_PROJECTION,
): Feature[] {
  return new GeoJSON().readFeatures(collection, { featureProjection });
}

/** Add one direct or Worker batch through the same conversion path. */
export function addGeoJsonFeatureBatch(
  source: VectorSource,
  collection: RenderableGeoJsonCollection,
  featureProjection = DEFAULT_FEATURE_PROJECTION,
): number {
  const features = readGeoJsonFeatures(collection, featureProjection);
  source.addFeatures(features);
  return features.length;
}

export function featureCollection(features: unknown[]): RenderableGeoJsonCollection {
  return { type: "FeatureCollection", features };
}

export const GEOJSON_FEATURES_PER_FRAME = 250;

export type RenderTaskEnvironment = {
  requestAnimationFrame?: (callback: () => void) => number;
  requestIdleCallback?: (callback: () => void, options?: { timeout?: number }) => number;
};

export function createFrameBatchScheduler<T>(
  onBatch: (batch: T[]) => void,
  onComplete: () => void,
  batchSize = GEOJSON_FEATURES_PER_FRAME,
  schedule: (callback: () => void) => void = scheduleRenderFrame,
) {
  if (!Number.isInteger(batchSize) || batchSize < 1) {
    throw new Error("batchSize must be a positive integer");
  }
  const queue: T[] = [];
  let finished = false;
  let scheduled = false;
  let completed = false;

  const drain = () => {
    scheduled = false;
    if (queue.length) onBatch(queue.splice(0, batchSize));
    if (queue.length) {
      scheduleDrain();
    } else if (finished && !completed) {
      completed = true;
      onComplete();
    }
  };

  const scheduleDrain = () => {
    if (scheduled || completed) return;
    scheduled = true;
    schedule(drain);
  };

  return {
    enqueue(items: T[]) {
      if (completed || items.length === 0) return;
      queue.push(...items);
      scheduleDrain();
    },
    finish() {
      finished = true;
      if (queue.length) scheduleDrain();
      else if (!completed) {
        completed = true;
        onComplete();
      }
    },
  };
}

export function scheduleRenderFrame(
  callback: () => void,
  environment: RenderTaskEnvironment = getRenderTaskEnvironment(),
): void {
  if (typeof environment.requestAnimationFrame === "function") {
    environment.requestAnimationFrame(callback);
    return;
  }
  setTimeout(callback, 0);
}

/** Defer non-urgent feature batches so pointer and wheel input get priority. */
export function scheduleRenderTask(
  callback: () => void,
  environment: RenderTaskEnvironment = getRenderTaskEnvironment(),
): void {
  if (typeof environment.requestIdleCallback === "function") {
    environment.requestIdleCallback(callback, { timeout: 100 });
    return;
  }
  scheduleRenderFrame(callback, environment);
}

function getRenderTaskEnvironment(): RenderTaskEnvironment {
  if (typeof window === "undefined") return {};
  return window as unknown as RenderTaskEnvironment;
}
