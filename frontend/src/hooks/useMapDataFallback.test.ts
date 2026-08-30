import { describe, expect, it } from "vitest";
import { parseGeoJsonBuffer, shouldFallbackToMainThread } from "./useMapData";

describe("GeoJSON worker fallback", () => {
  it("parses a valid response on the main thread when worker processing must fall back", () => {
    const body = new TextEncoder().encode(JSON.stringify({
      type: "FeatureCollection",
      features: [],
    })).buffer;

    expect(parseGeoJsonBuffer(body)).toEqual({
      type: "FeatureCollection",
      features: [],
    });
  });

  it("does not treat an HTTP error body as a successful worker fallback", () => {
    const body = new ArrayBuffer(1);

    expect(shouldFallbackToMainThread("worker", true, body, 8000)).toBe(true);
    expect(shouldFallbackToMainThread("worker", true, body, 8001)).toBe(false);
    expect(shouldFallbackToMainThread("worker", true, body)).toBe(false);
    expect(shouldFallbackToMainThread("worker", false, body, 8000)).toBe(false);
    expect(shouldFallbackToMainThread("direct", true, body, 8000)).toBe(false);
  });
});
