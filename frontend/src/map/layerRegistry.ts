import type { LayerPayload } from "../types/api";

type LayerDataIdentity = Pick<LayerPayload, "id" | "version" | "data_hash" | "geojson">;

export function getLayerDataKey(layer: LayerDataIdentity): string {
  return `${layer.id ?? "layer"}:${layer.version ?? 0}:${layer.data_hash ?? ""}:${layer.geojson ? "loaded" : "empty"}`;
}

export function shouldLoadLayerData(previousKey: string, nextKey: string, hasData: boolean): boolean {
  return hasData && previousKey !== nextKey;
}
