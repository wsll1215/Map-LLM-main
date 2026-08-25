import { describe, expect, it } from "vitest";
import { getRenderStrategy } from "./renderPolicy";

describe("getRenderStrategy", () => {
  it("follows the server-selected render mode", () => {
    expect(getRenderStrategy({ render_mode: "geojson" })).toBe("direct");
    expect(getRenderStrategy({ render_mode: "geojson-worker" })).toBe("worker");
    expect(getRenderStrategy({ render_mode: "mvt" })).toBe("mvt");
    expect(getRenderStrategy({ render_mode: "pmtiles" })).toBe("pmtiles");
  });

  it("uses direct GeoJSON only for legacy manifests without a mode", () => {
    expect(getRenderStrategy({})).toBe("direct");
  });
});
