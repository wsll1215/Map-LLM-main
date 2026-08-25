import type { LayerPayload } from "../types/api";

type LayerReference = Pick<LayerPayload, "id" | "version" | "data_url">;

export function getLayerDataUrl(requestId: number, layer: LayerReference): string {
  if (layer.data_url) {
    return layer.data_url.endsWith("/data/")
      ? layer.data_url
      : `${layer.data_url.replace(/\/$/, "")}/data/`;
  }
  const layerId = encodeURIComponent(String(layer.id || "layer"));
  const version = layer.version ?? "current";
  return `/mapping/api/map-requests/${requestId}/snapshots/${version}/layers/${layerId}/data/`;
}

export function getLayerCacheKey(requestId: number, layerId: string, version: number | undefined, dataHash: string | null | undefined): string {
  return `${requestId}:${layerId}:${version ?? 0}:${dataHash ?? ""}`;
}

export function shouldRetryLayerFetch(status: number, attempt: number): boolean {
  return (status === 202 || status === 404) && attempt < 2;
}
