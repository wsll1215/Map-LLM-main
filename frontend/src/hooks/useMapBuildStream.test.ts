import { describe, expect, it } from "vitest";
import { isCurrentStreamGeneration } from "./useMapBuildStream";

describe("useMapBuildStream generation guard", () => {
  it("rejects updates from an older connection generation", () => {
    expect(isCurrentStreamGeneration(3, 3)).toBe(true);
    expect(isCurrentStreamGeneration(4, 3)).toBe(false);
  });
});
