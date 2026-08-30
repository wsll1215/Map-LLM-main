import { describe, expect, it } from "vitest";
import { getUnrenderedGeoJsonFeatures, isRenderableExtent } from "./useOpenLayersMap";

describe("OpenLayers incremental feature loading", () => {
  it("creates a collection containing only features after the rendered cursor", () => {
    const first = { type: "Feature", geometry: { type: "Point", coordinates: [116, 40] }, properties: {} };
    const second = { type: "Feature", geometry: { type: "Point", coordinates: [117, 41] }, properties: {} };
    const collection = { type: "FeatureCollection" as const, features: [first, second] };

    expect(getUnrenderedGeoJsonFeatures(collection, 1)).toEqual({
      type: "FeatureCollection",
      features: [second],
    });
  });

  it("limits one incremental render commit to the frame budget", () => {
    const collection = {
      type: "FeatureCollection" as const,
      features: Array.from({ length: 4 }, (_, index) => ({
        type: "Feature",
        geometry: { type: "Point", coordinates: [116 + index, 40] },
        properties: {},
      })),
    };

    expect(getUnrenderedGeoJsonFeatures(collection, 1, 2).features).toHaveLength(2);
    expect(getUnrenderedGeoJsonFeatures(collection, 3, 2).features).toHaveLength(1);
  });

  it("guards nullable OpenLayers extents before fitting the view", () => {
    expect(isRenderableExtent(null)).toBe(false);
    expect(isRenderableExtent([0, 0, 1, 1])).toBe(true);
  });
});
