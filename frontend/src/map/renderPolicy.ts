import type { LayerPayload } from "../types/api";

export type RenderStrategy = "direct" | "worker" | "mvt" | "pmtiles";

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
