import { describe, expect, it } from "vitest";
import { createGeoJsonCancelRequest, createGeoJsonParseRequest, isCurrentGeoJsonWorkerResponse, type GeoJsonWorkerRequest } from "./workerProtocol";

describe("GeoJSON worker protocol", () => {
  it("sends the raw response buffer as a transferable parse request", () => {
    const buffer = new TextEncoder().encode('{"type":"FeatureCollection","features":[]}').buffer;

    const request = createGeoJsonParseRequest({
      requestId: 4,
      layerId: "roads",
      layerVersion: 7,
      buffer,
      batchSize: 2,
    });

    expect(request).toMatchObject<GeoJsonWorkerRequest>({
      type: "parse",
      requestId: 4,
      layerId: "roads",
      layerVersion: 7,
      buffer,
      batchSize: 2,
    });
    expect("collection" in request).toBe(false);
  });

  it("rejects a response from a stale layer version", () => {
    expect(
      isCurrentGeoJsonWorkerResponse(
        { type: "batch", requestId: 4, layerId: "roads", layerVersion: 6, features: [], featureCount: 0, extent: null, done: true },
        { layerId: "roads", layerVersion: 7 },
      ),
    ).toBe(false);
  });

  it("creates an explicit cancellation request for the active worker job", () => {
    expect(createGeoJsonCancelRequest(9)).toEqual({ type: "cancel", requestId: 9 });
  });
});
