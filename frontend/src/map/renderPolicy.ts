import type { LayerPayload } from "../types/api";

export type RenderStrategy = "direct" | "worker" | "mvt" | "pmtiles";

export const GEOJSON_FEATURE_LIMIT = 8000;
export const WORKER_FEATURE_LIMIT = 30000;
export const MVT_TILE_SIZE = 256;

export function renderFeaturesPerFrame(featureCount: number): number {
  if (featureCount <= 10000) return 1000;
  if (featureCount <= 20000) return 500;
  return 250;
}

export function renderModeForFeatureCount(featureCount: number, mvtEnabled = true): NonNullable<LayerPayload["render_mode"]> {
  if (featureCount > WORKER_FEATURE_LIMIT) return mvtEnabled ? "mvt" : "geojson-worker";
  if (featureCount > GEOJSON_FEATURE_LIMIT) return "geojson-worker";
  return "geojson";
}

export function getRenderStrategy(layer: Pick<LayerPayload, "render_mode">): RenderStrategy {
  switch (layer.render_mode) {
    case "geojson-worker":
      return "worker";
    case "mvt":
      return "mvt";
    case "pmtiles":
      return "pmtiles";
    default:
      return "direct";
  }
}
