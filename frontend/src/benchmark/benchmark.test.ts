import { describe, expect, it } from "vitest";
import { beginRenderMeasurement, MVT_BENCHMARK_TILE_SIZE, MVT_BENCHMARK_ZOOM } from "./benchmark";

describe("benchmark render measurement", () => {
  it("uses the same 256px tile grid as the synthetic MVT layout", () => {
    expect(MVT_BENCHMARK_TILE_SIZE).toBe(256);
    expect(MVT_BENCHMARK_ZOOM).toBe(11);
  });

  it("marks the render start once when the first worker batch arrives", () => {
    const marks: string[] = [];
    const state = { started: false };

    beginRenderMeasurement((name) => marks.push(name), state);
    beginRenderMeasurement((name) => marks.push(name), state);

    expect(state.started).toBe(true);
    expect(marks).toEqual(["render-start"]);
  });
});
