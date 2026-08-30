import { describe, expect, it } from "vitest";
import VectorSource from "ol/source/Vector";
import Point from "ol/geom/Point";
import { addGeoJsonFeatureBatch, createFrameBatchScheduler, readGeoJsonFeatures, scheduleRenderTask } from "./renderers";

const collection = {
  type: "FeatureCollection" as const,
  features: [
    {
      type: "Feature" as const,
      geometry: { type: "Point" as const, coordinates: [116.4, 39.9] },
      properties: { name: "A" },
    },
    {
      type: "Feature" as const,
      geometry: { type: "Point" as const, coordinates: [116.5, 39.91] },
      properties: { name: "B" },
    },
  ],
};

describe("shared map renderers", () => {
  it("drains streamed features within a frame budget and completes after the queue", () => {
    const scheduled: Array<() => void> = [];
    const batches: number[][] = [];
    let completed = false;
    const scheduler = createFrameBatchScheduler<number>(
      (batch) => batches.push(batch),
      () => { completed = true; },
      2,
      (callback) => scheduled.push(callback),
    );

    scheduler.enqueue([1, 2, 3]);
    scheduler.finish();
    expect(batches).toEqual([]);

    scheduled.shift()?.();
    expect(batches).toEqual([[1, 2]]);
    expect(completed).toBe(false);

    scheduled.shift()?.();
    expect(batches).toEqual([[1, 2], [3]]);
    expect(completed).toBe(true);
  });

  it("converts GeoJSON with the same OpenLayers projection used by production", () => {
    const features = readGeoJsonFeatures(collection);

    expect(features).toHaveLength(2);
    expect(features[0].getGeometry()?.getType()).toBe("Point");
    const geometry = features[0].getGeometry();
    expect(geometry).toBeInstanceOf(Point);
    expect((geometry as Point).getCoordinates()[0]).toBeGreaterThan(10000000);
  });

  it("adds a worker batch to a vector source and returns the converted count", () => {
    const source = new VectorSource();

    const added = addGeoJsonFeatureBatch(source, collection);

    expect(added).toBe(2);
    expect(source.getFeatures()).toHaveLength(2);
  });

  it("uses idle time for background render batches when the browser supports it", () => {
    const callbacks: Array<() => void> = [];
    let timeout: number | undefined;

    scheduleRenderTask(
      () => callbacks.push(() => undefined),
      {
        requestIdleCallback(callback: () => void, options?: { timeout?: number }) {
          callbacks.push(callback);
          timeout = options?.timeout;
          return 1;
        },
        requestAnimationFrame() {
          throw new Error("background work must not use animation frames when idle callbacks exist");
        },
      },
    );

    expect(callbacks).toHaveLength(1);
    expect(timeout).toBe(100);
  });
});
