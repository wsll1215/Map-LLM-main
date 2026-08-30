import { describe, expect, it } from "vitest";
import { handleGeoJsonWorkerMessage, parseGeoJsonArrayBuffer } from "./geojsonParser.worker";

describe("GeoJSON worker parser", () => {
  it("parses the raw ArrayBuffer inside the worker and returns batches", () => {
    const payload = {
      type: "FeatureCollection",
      features: [
        { type: "Feature", geometry: { type: "Point", coordinates: [116, 40] }, properties: {} },
        { type: "Feature", geometry: { type: "Point", coordinates: [117, 41] }, properties: {} },
      ],
    };
    const buffer = new TextEncoder().encode(JSON.stringify(payload)).buffer;

    const result = parseGeoJsonArrayBuffer(buffer, 1);

    expect(result.batches).toHaveLength(2);
    expect(result.featureCount).toBe(2);
    expect(result.extent).toEqual([116, 40, 117, 41]);
  });

  it("emits one response for each parsed batch and a terminal done response", async () => {
    const point = { type: "Feature", geometry: { type: "Point", coordinates: [116, 40] }, properties: {} };
    const buffer = new TextEncoder().encode(JSON.stringify({ type: "FeatureCollection", features: [point, point] })).buffer;
    const messages: unknown[] = [];

    await handleGeoJsonWorkerMessage(
      { type: "parse", requestId: 2, layerId: "schools", layerVersion: 3, buffer, batchSize: 1 },
      (message) => messages.push(message),
    );

    expect(messages).toHaveLength(2);
    expect(messages[0]).toMatchObject({ type: "batch", done: false, featureCount: 2 });
    expect(messages[1]).toMatchObject({ type: "batch", done: true, featureCount: 2 });
  });
});
