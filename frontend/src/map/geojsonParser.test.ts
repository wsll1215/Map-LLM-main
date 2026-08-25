import { describe, expect, it } from "vitest";
import { parseFeatureCollection } from "./geojsonParser";

describe("parseFeatureCollection", () => {
  it("filters empty geometries, batches features, and computes extent", () => {
    const result = parseFeatureCollection(
      {
        type: "FeatureCollection",
        features: [
          { type: "Feature", geometry: { type: "Point", coordinates: [116, 40] }, properties: {} },
          { type: "Feature", geometry: null, properties: {} },
          { type: "Feature", geometry: { type: "Point", coordinates: [117, 41] }, properties: {} },
        ],
      },
      1,
    );

    expect(result.batches).toHaveLength(2);
    expect(result.batches[0]).toHaveLength(1);
    expect(result.featureCount).toBe(2);
    expect(result.extent).toEqual([116, 40, 117, 41]);
  });

  it("rejects malformed feature collections", () => {
    expect(() => parseFeatureCollection({ type: "FeatureCollection", features: "bad" })).toThrow(
      "GeoJSON features must be an array",
    );
  });
});
