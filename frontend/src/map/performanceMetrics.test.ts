import { describe, expect, it } from "vitest";
import { createPerformanceMetrics } from "./performanceMetrics";

describe("render performance metrics", () => {
  it("records deterministic phase durations and browser responsiveness metrics", () => {
    let now = 100;
    const metrics = createPerformanceMetrics(() => now);

    metrics.mark("fetch_start");
    now = 160;
    metrics.mark("fetch_end");
    metrics.measure("fetch_ms", "fetch_start", "fetch_end");
    metrics.recordLongTask(84);
    metrics.recordInputDelay(22);

    expect(metrics.snapshot()).toMatchObject({
      durations: { fetch_ms: 60 },
      long_task_ms: 84,
      input_delay_ms: 22,
    });
  });

  it("keeps the first visible and interactive timestamps separate", () => {
    let now = 0;
    const metrics = createPerformanceMetrics(() => now);

    metrics.mark("fetch_start");
    now = 25;
    metrics.mark("first_visible");
    now = 70;
    metrics.mark("interactive");

    expect(metrics.snapshot().durations).toEqual({
      time_to_first_visible_ms: 25,
      time_to_interactive_ms: 70,
    });
  });

  it("reports phase measurements independently instead of folding parse time into fetch time", () => {
    let now = 0;
    const metrics = createPerformanceMetrics(() => now);

    metrics.mark("fetch_start");
    now = 40;
    metrics.mark("fetch_end");
    now = 90;
    metrics.mark("parse_end");
    metrics.measure("fetch_ms", "fetch_start", "fetch_end");
    metrics.measure("json_parse_ms", "fetch_end", "parse_end");

    expect(metrics.snapshot().durations).toEqual({ fetch_ms: 40, json_parse_ms: 50 });
  });
});
