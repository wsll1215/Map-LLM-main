import type { LayerPayload } from "../types/api";

type LayerReference = Pick<LayerPayload, "id" | "version" | "data_url">;
export type Bbox = [number, number, number, number];

export function getLayerDataUrl(requestId: number, layer: LayerReference, bbox?: Bbox): string {
  const baseUrl = layer.data_url
    ? layer.data_url.endsWith("/data/")
      ? layer.data_url
      : `${layer.data_url.replace(/\/$/, "")}/data/`
    : `/mapping/api/map-requests/${requestId}/snapshots/${layer.version ?? "current"}/layers/${encodeURIComponent(String(layer.id || "layer"))}/data/`;
  if (!bbox) return baseUrl;
  const separator = baseUrl.includes("?") ? "&" : "?";
  return `${baseUrl}${separator}bbox=${bbox.join(",")}`;
}

export function getLayerCacheKey(requestId: number, layerId: string, version: number | undefined, dataHash: string | null | undefined, bbox?: Bbox): string {
  return `${requestId}:${layerId}:${version ?? 0}:${dataHash ?? ""}:${bbox?.join(",") ?? "full"}`;
}

export function getLayerTileUrl(requestId: number, layer: LayerReference): string {
  const version = layer.version ?? "current";
  const layerId = encodeURIComponent(String(layer.id || "layer"));
  return `/mapping/api/map-requests/${requestId}/snapshots/${version}/layers/${layerId}/tiles/{z}/{x}/{y}.pbf`;
}

export function shouldRetryLayerFetch(status: number, attempt: number): boolean {
  return (status === 202 || status === 404) && attempt < 2;
}
