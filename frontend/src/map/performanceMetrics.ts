export type PerformanceClock = () => number;

export interface PerformanceSnapshot {
  durations: Record<string, number>;
  long_task_ms: number;
  long_task_count: number;
  input_delay_ms: number;
  input_delay_count: number;
}

export interface PerformanceMetrics {
  mark(name: string): void;
  measure(name: string, startMark: string, endMark: string): number | null;
  recordLongTask(duration: number): void;
  recordInputDelay(duration: number): void;
  snapshot(): PerformanceSnapshot;
  reset(): void;
}

export function createPerformanceMetrics(now: PerformanceClock = () => performance.now()): PerformanceMetrics {
  const marks = new Map<string, number>();
  const durations = new Map<string, number>();
  let longTaskMs = 0;
  let longTaskCount = 0;
  let inputDelayMs = 0;
  let inputDelayCount = 0;

  return {
    mark(name) {
      const timestamp = now();
      marks.set(name, timestamp);
      if (name === "first_visible") {
        measureInternal("time_to_first_visible_ms", "fetch_start", name);
      }
      if (name === "interactive") {
        measureInternal("time_to_interactive_ms", "fetch_start", name);
      }
    },
    measure(name, startMark, endMark) {
      const start = marks.get(startMark);
      const end = marks.get(endMark);
      if (start === undefined || end === undefined || end < start) return null;
      measureInternal(name, startMark, endMark);
      return end - start;
    },
    recordLongTask(duration) {
      if (!Number.isFinite(duration) || duration < 0) return;
      longTaskMs += duration;
      longTaskCount += 1;
    },
    recordInputDelay(duration) {
      if (!Number.isFinite(duration) || duration < 0) return;
      inputDelayMs = Math.max(inputDelayMs, duration);
      inputDelayCount += 1;
    },
    snapshot() {
      return {
        durations: Object.fromEntries(durations),
        long_task_ms: longTaskMs,
        long_task_count: longTaskCount,
        input_delay_ms: inputDelayMs,
        input_delay_count: inputDelayCount,
      };
    },
    reset() {
      marks.clear();
      durations.clear();
      longTaskMs = 0;
      longTaskCount = 0;
      inputDelayMs = 0;
      inputDelayCount = 0;
    },
  };

  function measureInternal(name: string, startMark: string, endMark: string): number | null {
    const start = marks.get(startMark);
    const end = marks.get(endMark);
    if (start === undefined || end === undefined || end < start) return null;
    durations.set(name, (durations.get(name) || 0) + end - start);
    return end - start;
  }
}

export function observeBrowserPerformance(metrics: PerformanceMetrics): () => void {
  if (typeof PerformanceObserver === "undefined") return () => undefined;

  const observers: PerformanceObserver[] = [];
  const observe = (type: string, callback: (entry: PerformanceEntry) => void) => {
    try {
      const observer = new PerformanceObserver((list) => {
        for (const entry of list.getEntries()) callback(entry);
      });
      observer.observe({ type, buffered: true });
      observers.push(observer);
    } catch {
      // Unsupported entry types are normal in older browsers.
    }
  };

  observe("longtask", (entry) => metrics.recordLongTask(entry.duration));
  observe("event", (entry) => {
    const timing = entry as PerformanceEventTiming;
    metrics.recordInputDelay(Math.max(0, timing.processingStart - timing.startTime));
  });
  return () => observers.forEach((observer) => observer.disconnect());
}
