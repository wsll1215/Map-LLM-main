import { parseFeatureCollection } from "../map/geojsonParser";
import type { GeoJsonWorkerRequest, GeoJsonWorkerResponse } from "../map/workerProtocol";

const cancelled = new Set<number>();
const workerScope = self as unknown as {
  onmessage: ((event: MessageEvent<GeoJsonWorkerRequest>) => void) | null;
  postMessage: (message: GeoJsonWorkerResponse) => void;
};

workerScope.onmessage = async ({ data }) => {
  if (data.type === "cancel") {
    cancelled.add(data.requestId);
    return;
  }
  cancelled.delete(data.requestId);
  try {
    const parsed = parseFeatureCollection(data.collection, data.batchSize);
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
      workerScope.postMessage(response);
      await new Promise<void>((resolve) => setTimeout(resolve, 0));
    }
    if (parsed.batches.length === 0 && !cancelled.has(data.requestId)) {
      workerScope.postMessage({
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
    workerScope.postMessage({
      type: "error",
      requestId: data.requestId,
      layerId: data.layerId,
      layerVersion: data.layerVersion,
      message: error instanceof Error ? error.message : "GeoJSON 解析失败",
    });
  } finally {
    cancelled.delete(data.requestId);
  }
};
