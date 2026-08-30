import { describe, expect, it, vi } from "vitest";
import { appendGeoJsonBatch, copyBufferForWorker, createBboxDebouncer, createGeoJsonBatchBuffer } from "./useMapData";

describe("useMapData viewport loading", () => {
  it("keeps the original response buffer available for worker fallback", () => {
    const original = new TextEncoder().encode('{"type":"FeatureCollection"}').buffer;
    const workerBuffer = copyBufferForWorker(original);

    expect(workerBuffer).not.toBe(original);
    expect(new TextDecoder().decode(original)).toContain("FeatureCollection");
  });

  it("debounces rapid viewport changes and can cancel the pending request", () => {
    vi.useFakeTimers();
    const onChange = vi.fn();
    const debouncer = createBboxDebouncer(onChange, 250);

    debouncer.schedule([115, 39, 116, 40]);
    debouncer.schedule([116, 40, 117, 41]);
    vi.advanceTimersByTime(249);
    expect(onChange).not.toHaveBeenCalled();

    vi.advanceTimersByTime(1);
    expect(onChange).toHaveBeenCalledOnce();
    expect(onChange).toHaveBeenCalledWith([116, 40, 117, 41]);

    debouncer.schedule([117, 41, 118, 42]);
    debouncer.cancel();
    vi.advanceTimersByTime(250);
    expect(onChange).toHaveBeenCalledOnce();
    vi.useRealTimers();
  });

  it("appends worker batches without replacing features from earlier batches", () => {
    const first = { type: "FeatureCollection" as const, features: [] };
    const point = { type: "Feature" as const, geometry: { type: "Point", coordinates: [116, 40] }, properties: {} };

    const result = appendGeoJsonBatch(first, [point]);

    expect(result.features).toEqual([point]);
    expect(result).not.toBe(first);
  });

  it("keeps one mutable feature buffer for multiple worker batches", () => {
    const buffer = createGeoJsonBatchBuffer();
    const first = [{ type: "Feature" as const, geometry: { type: "Point", coordinates: [116, 40] }, properties: {} }];
    const second = [{ type: "Feature" as const, geometry: { type: "Point", coordinates: [117, 41] }, properties: {} }];

    const firstSnapshot = buffer.append(first);
    const secondSnapshot = buffer.append(second);

    expect(secondSnapshot.features).toBe(firstSnapshot.features);
    expect(secondSnapshot.features).toHaveLength(2);
  });
});
