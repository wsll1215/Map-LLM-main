import { describe, expect, it } from "vitest";
import { getLayerDataKey, shouldLoadLayerData } from "./layerRegistry";

describe("layer registry versioning", () => {
  it("changes the data key when the version or hash changes", () => {
    const first = getLayerDataKey({ id: "roads", version: 1, data_hash: "one", geojson: null });
    const next = getLayerDataKey({ id: "roads", version: 2, data_hash: "two", geojson: null });
    expect(first).not.toBe(next);
  });

  it("loads only when data exists and the key is new", () => {
    const key = getLayerDataKey({ id: "roads", version: 1, data_hash: "one", geojson: null });
    expect(shouldLoadLayerData("", key, false)).toBe(false);
    expect(shouldLoadLayerData("old", key, true)).toBe(true);
    expect(shouldLoadLayerData(key, key, true)).toBe(false);
  });
});
