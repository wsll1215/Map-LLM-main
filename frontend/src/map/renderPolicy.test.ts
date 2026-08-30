import { describe, expect, it } from "vitest";
import { getRenderStrategy, renderFeaturesPerFrame, renderModeForFeatureCount } from "./renderPolicy";

describe("getRenderStrategy", () => {
  it("uses a larger frame budget for smaller worker payloads", () => {
    expect(renderFeaturesPerFrame(5001)).toBe(1000);
    expect(renderFeaturesPerFrame(10000)).toBe(1000);
    expect(renderFeaturesPerFrame(10001)).toBe(500);
    expect(renderFeaturesPerFrame(30000)).toBe(250);
  });

  it("follows the server-selected render mode", () => {
    expect(getRenderStrategy({ render_mode: "geojson" })).toBe("direct");
    expect(getRenderStrategy({ render_mode: "geojson-worker" })).toBe("worker");
    expect(getRenderStrategy({ render_mode: "mvt" })).toBe("mvt");
    expect(getRenderStrategy({ render_mode: "pmtiles" })).toBe("pmtiles");
  });

  it("uses direct GeoJSON only for legacy manifests without a mode", () => {
    expect(getRenderStrategy({})).toBe("direct");
  });

  it.each([
    [4999, "geojson", "direct"],
    [5000, "geojson", "direct"],
    [7999, "geojson", "direct"],
    [8000, "geojson", "direct"],
    [8001, "geojson-worker", "worker"],
    [30000, "geojson-worker", "worker"],
    [30001, "mvt", "mvt"],
  ] as const)("keeps the server render contract at %s features", (_count, mode, expected) => {
    expect(getRenderStrategy({ render_mode: mode })).toBe(expected);
  });

  it.each([
    [4999, "geojson"], [5000, "geojson"], [7999, "geojson"],
    [8000, "geojson"], [8001, "geojson-worker"],
    [30000, "geojson-worker"], [30001, "mvt"],
  ] as const)("selects the production mode at %s features", (count, expected) => {
    expect(renderModeForFeatureCount(count)).toBe(expected);
  });
});
