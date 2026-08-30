import { parseFeatureCollection } from "../map/geojsonParser";
import type { GeoJsonWorkerRequest, GeoJsonWorkerResponse } from "../map/workerProtocol";

const cancelled = new Set<number>();
const workerScope = self as unknown as {
  onmessage: ((event: MessageEvent<GeoJsonWorkerRequest>) => void) | null;
  postMessage: (message: GeoJsonWorkerResponse) => void;
};

export async function handleGeoJsonWorkerMessage(
  data: GeoJsonWorkerRequest,
  postMessage: (message: GeoJsonWorkerResponse) => void,
  schedule: () => Promise<void> = () => new Promise((resolve) => setTimeout(resolve, 0)),
): Promise<void> {
  if (data.type === "cancel") {
    cancelled.add(data.requestId);
    return;
  }
  cancelled.delete(data.requestId);
  try {
    const parsed = parseGeoJsonArrayBuffer(data.buffer, data.batchSize);
    for (const [index, features] of parsed.batches.entries()) {
      if (cancelled.has(data.requestId)) return;
      const response: GeoJsonWorkerResponse = {
        type: "batch",
        requestId: data.requestId,
        layerId: data.layerId,
        layerVersion: data.layerVersion,
        features,
        featureCount: parsed.featureCount,
        extent: parsed.extent,
        done: index === parsed.batches.length - 1,
      };
      postMessage(response);
      await schedule();
    }
    if (parsed.batches.length === 0 && !cancelled.has(data.requestId)) {
      postMessage({
        type: "batch",
        requestId: data.requestId,
        layerId: data.layerId,
        layerVersion: data.layerVersion,
        features: [],
        featureCount: 0,
        extent: null,
        done: true,
      });
    }
  } catch (error) {
    postMessage({
      type: "error",
      requestId: data.requestId,
      layerId: data.layerId,
      layerVersion: data.layerVersion,
      message: error instanceof Error ? error.message : "GeoJSON 解析失败",
    });
  } finally {
    cancelled.delete(data.requestId);
  }
}

workerScope.onmessage = ({ data }) => {
  void handleGeoJsonWorkerMessage(data, (message) => workerScope.postMessage(message));
};

export function parseGeoJsonArrayBuffer(buffer: ArrayBuffer, batchSize = 500) {
  const text = new TextDecoder().decode(buffer);
  const collection = JSON.parse(text);
  return parseFeatureCollection(collection, batchSize);
}
