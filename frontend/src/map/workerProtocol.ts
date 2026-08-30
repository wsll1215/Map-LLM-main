import type { GeoJsonFeature } from "./geojsonParser";

export type GeoJsonWorkerRequest =
  | {
      type: "parse";
      requestId: number;
      layerId: string;
      layerVersion: number;
      buffer: ArrayBuffer;
      batchSize?: number;
    }
  | { type: "cancel"; requestId: number };

export type GeoJsonWorkerResponse =
  | {
      type: "batch";
      requestId: number;
      layerId: string;
      layerVersion: number;
      features: GeoJsonFeature[];
      featureCount: number;
      extent: [number, number, number, number] | null;
      done: boolean;
    }
  | { type: "error"; requestId: number; layerId: string; layerVersion: number; message: string };

export function isCurrentGeoJsonWorkerResponse(
  response: GeoJsonWorkerResponse,
  job: Pick<Extract<GeoJsonWorkerRequest, { type: "parse" }>, "layerId" | "layerVersion">,
): boolean {
  return response.layerId === job.layerId && response.layerVersion === job.layerVersion;
}

export function createGeoJsonParseRequest(options: {
  requestId: number;
  layerId: string;
  layerVersion: number;
  buffer: ArrayBuffer;
  batchSize?: number;
}): Extract<GeoJsonWorkerRequest, { type: "parse" }> {
  return {
    type: "parse",
    requestId: options.requestId,
    layerId: options.layerId,
    layerVersion: options.layerVersion,
    buffer: options.buffer,
    ...(options.batchSize === undefined ? {} : { batchSize: options.batchSize }),
  };
}

export function createGeoJsonCancelRequest(requestId: number): Extract<GeoJsonWorkerRequest, { type: "cancel" }> {
  return { type: "cancel", requestId };
}
