import { describe, expect, it } from "vitest";
import { getLayerDataUrl, getLayerCacheKey, shouldRetryLayerFetch } from "./mapDataLoader";

describe("mapDataLoader helpers", () => {
  it("builds a versioned data URL from a layer manifest", () => {
    expect(
      getLayerDataUrl(7, {
        id: "roads",
        version: 3,
        data_url: null,
      }),
    ).toBe("/mapping/api/map-requests/7/snapshots/3/layers/roads/data/");
  });

  it("uses the data hash to invalidate an unchanged layer id/version", () => {
    expect(getLayerCacheKey(7, "roads", 3, "sha256:one")).not.toBe(
      getLayerCacheKey(7, "roads", 3, "sha256:two"),
    );
  });

  it("isolates identical layer versions between map requests", () => {
    expect(getLayerCacheKey(7, "roads", 3, "sha256:same")).not.toBe(
      getLayerCacheKey(8, "roads", 3, "sha256:same"),
    );
  });

  it("retries only transient missing snapshot responses", () => {
    expect(shouldRetryLayerFetch(404, 0)).toBe(true);
    expect(shouldRetryLayerFetch(202, 0)).toBe(true);
    expect(shouldRetryLayerFetch(404, 2)).toBe(false);
    expect(shouldRetryLayerFetch(500, 0)).toBe(false);
  });
});
