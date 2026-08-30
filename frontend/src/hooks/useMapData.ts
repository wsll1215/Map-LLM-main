import { useEffect, useRef, useState } from "react";
import type { LayerPayload } from "../types/api";
import { getLayerCacheKey, getLayerDataUrl, shouldRetryLayerFetch, type Bbox } from "../map/mapDataLoader";
import { GEOJSON_FEATURE_LIMIT, getRenderStrategy, type RenderStrategy } from "../map/renderPolicy";
import type { GeoJsonFeature, GeoJsonFeatureCollection } from "../map/geojsonParser";
import { createGeoJsonCancelRequest, createGeoJsonParseRequest, isCurrentGeoJsonWorkerResponse, type GeoJsonWorkerResponse } from "../map/workerProtocol";
import { createPerformanceMetrics, type PerformanceSnapshot } from "../map/performanceMetrics";

type PendingWorkerJob = {
  layerId: string;
  layerVersion: number;
  features: GeoJsonFeature[];
  onBatch: (features: GeoJsonFeature[]) => void;
  resolve: (value: GeoJsonFeatureCollection) => void;
  reject: (reason: Error) => void;
};

export function useMapData(requestId: number | null, layers: LayerPayload[], viewportBbox?: Bbox | null, retryToken = 0) {
  const workerRef = useRef<Worker | null>(null);
  const jobIdRef = useRef(0);
  const pendingJobsRef = useRef(new Map<number, PendingWorkerJob>());
  const workerBuffersRef = useRef(new Map<string, { cacheKey: string; buffer: ReturnType<typeof createGeoJsonBatchBuffer>; flushScheduled: boolean }>());
  const cacheRef = useRef(new Map<string, LayerPayload["geojson"]>());
  const loadedKeysRef = useRef(new Map<string, string>());
  const [loadedData, setLoadedData] = useState<Record<string, LayerPayload["geojson"]>>({});
  const [loading, setLoading] = useState<Record<string, boolean>>({});
  const [error, setError] = useState<string | null>(null);
  const [performance, setPerformance] = useState<PerformanceSnapshot>(() => createPerformanceMetrics().snapshot());
  const metricsRef = useRef(createPerformanceMetrics());
  const [debouncedViewportBbox, setDebouncedViewportBbox] = useState<Bbox | null | undefined>(viewportBbox);
  const lastRequestIdRef = useRef<number | null>(null);

  useEffect(() => {
    const debouncer = createBboxDebouncer(setDebouncedViewportBbox, 250);
    debouncer.schedule(viewportBbox ?? null);
    return debouncer.cancel;
  }, [viewportBbox]);

  useEffect(() => {
    try {
      const worker = new Worker(new URL("../workers/geojsonParser.worker.ts", import.meta.url), { type: "module" });
      worker.onmessage = ({ data }: MessageEvent<GeoJsonWorkerResponse>) => {
        const job = pendingJobsRef.current.get(data.requestId);
        if (!job) return;
        if (!isCurrentGeoJsonWorkerResponse(data, job)) {
          pendingJobsRef.current.delete(data.requestId);
          job.reject(new Error("GeoJSON Worker 返回了过期版本"));
          return;
        }
        if (data.type === "error") {
          pendingJobsRef.current.delete(data.requestId);
          job.reject(new Error(data.message));
          return;
        }
        job.features.push(...data.features);
        job.onBatch(data.features);
        if (data.done) {
          pendingJobsRef.current.delete(data.requestId);
          job.resolve({ type: "FeatureCollection", features: job.features });
        }
      };
      worker.onerror = () => {
        for (const [jobId, job] of pendingJobsRef.current) {
          pendingJobsRef.current.delete(jobId);
          job.reject(new Error("GeoJSON Worker 执行失败"));
        }
      };
      workerRef.current = worker;
      return () => {
        for (const [jobId, job] of pendingJobsRef.current) {
          worker.postMessage(createGeoJsonCancelRequest(jobId));
          job.reject(new Error("GeoJSON Worker 任务已取消"));
        }
        pendingJobsRef.current.clear();
        worker.terminate();
        workerRef.current = null;
      };
    } catch {
      setError("浏览器不支持 GeoJSON Worker，已停止加载中等规模图层");
      return undefined;
    }
  }, []);

  useEffect(() => {
    if (!requestId) return undefined;
    const controllers = new Map<string, AbortController>();
    let active = true;
    setError(null);
    if (lastRequestIdRef.current !== requestId) {
      cacheRef.current.clear();
      loadedKeysRef.current.clear();
      setLoadedData({});
      lastRequestIdRef.current = requestId;
    }
    setLoading({});
    workerBuffersRef.current.clear();
    metricsRef.current.reset();
    setPerformance(metricsRef.current.snapshot());

    const loadLayer = async (layer: LayerPayload, layerId: string) => {
      const strategy = getRenderStrategy(layer);
      let responseBody: ArrayBuffer | null = null;
      if (strategy === "mvt" || strategy === "pmtiles") {
        setLoading((current) => ({ ...current, [layerId]: false }));
        if (strategy === "pmtiles") {
          setError(String(layer.name || layerId) + ": PMTiles 尚未配置可用数据源，已保留 PNG 预览");
        }
        return;
      }
      const requestBbox = strategy === "worker" ? debouncedViewportBbox || normalizeBbox(layer.extent) : undefined;
      const cacheKey = getLayerCacheKey(requestId, layerId, layer.version, layer.data_hash, requestBbox);
      const cached = cacheRef.current.get(cacheKey);
      if (cached) {
        loadedKeysRef.current.set(layerId, cacheKey);
        setLoadedData((current) => ({ ...current, [layerId]: cached }));
        return;
      }

      const controller = new AbortController();
      controllers.set(cacheKey, controller);
      setLoading((current) => ({ ...current, [layerId]: true }));
      let responseWasOk = false;
      try {
        let response: Response;
        const fetchStart = `${layerId}:fetch_start`;
        const fetchEnd = `${layerId}:fetch_end`;
        metricsRef.current.mark(fetchStart);
        for (let attempt = 0; ; attempt += 1) {
          response = await fetch(getLayerDataUrl(requestId, { ...layer, id: layerId }, requestBbox), {
            credentials: "same-origin",
            signal: controller.signal,
            headers: { Accept: "application/geo+json, application/json" },
          });
          if (!shouldRetryLayerFetch(response.status, attempt)) break;
          await new Promise((resolve) => setTimeout(resolve, 500));
          if (controller.signal.aborted) return;
        }
        const body = await response.arrayBuffer();
        responseBody = body;
        responseWasOk = response.ok;
        metricsRef.current.mark(fetchEnd);
        metricsRef.current.measure("fetch_ms", fetchStart, fetchEnd);
        if (!response.ok) {
          const errorBody = parseErrorBuffer(body);
          throw new Error(errorBody?.error || `图层加载失败 (${response.status})`);
        }
        if (strategy === "worker") {
          const buffer = body as ArrayBuffer;
          const workerStart = `${layerId}:worker_start`;
          const workerEnd = `${layerId}:worker_end`;
          metricsRef.current.mark(workerStart);
          let workerBuffer = workerBuffersRef.current.get(layerId);
          if (!workerBuffer || workerBuffer.cacheKey !== cacheKey) {
            workerBuffer = { cacheKey, buffer: createGeoJsonBatchBuffer(), flushScheduled: false };
            workerBuffersRef.current.set(layerId, workerBuffer);
          }
          const flushWorkerBuffer = () => {
            if (!active || controller.signal.aborted || !workerBuffer) return;
            workerBuffer.flushScheduled = false;
            loadedKeysRef.current.set(layerId, cacheKey);
            setLoadedData((current) => ({ ...current, [layerId]: workerBuffer!.buffer.collection as LayerPayload["geojson"] }));
            setPerformance(metricsRef.current.snapshot());
          };
          const scheduleWorkerBufferFlush = () => {
            if (!workerBuffer || workerBuffer.flushScheduled) return;
            workerBuffer.flushScheduled = true;
            if (typeof window !== "undefined" && typeof window.requestAnimationFrame === "function") {
              window.requestAnimationFrame(flushWorkerBuffer);
            } else {
              setTimeout(flushWorkerBuffer, 0);
            }
          };
          const parsed = workerRef.current
            ? await parseWithWorker(workerRef.current, buffer, layerId, layer.version ?? 0, jobIdRef, pendingJobsRef.current, (batch) => {
               if (!active || controller.signal.aborted) return;
               workerBuffer!.buffer.append(batch);
               scheduleWorkerBufferFlush();
             })
            : null;
          metricsRef.current.mark(workerEnd);
          metricsRef.current.measure("worker_process_ms", workerStart, workerEnd);
          if (!parsed) throw new Error("浏览器不支持 GeoJSON Worker，无法加载中等规模图层");
          if (!active || controller.signal.aborted) return;
          cacheRef.current.set(cacheKey, parsed as LayerPayload["geojson"]);
          trimCache(cacheRef.current, 12);
          loadedKeysRef.current.set(layerId, cacheKey);
          setLoadedData((current) => ({ ...current, [layerId]: parsed as LayerPayload["geojson"] }));
        } else {
          const parseStart = `${layerId}:parse_start`;
          const parseEnd = `${layerId}:parse_end`;
          metricsRef.current.mark(parseStart);
          const collection = parseJsonBuffer(body);
          const responseMetadata = collection as GeoJsonFeatureCollection & { status?: string; error?: string };
          if (responseMetadata.status === "pending") {
            throw new Error(responseMetadata.error || "图层快照仍在生成");
          }
          metricsRef.current.mark(parseEnd);
          metricsRef.current.measure("json_parse_ms", parseStart, parseEnd);
          if (!active || controller.signal.aborted) return;
          cacheRef.current.set(cacheKey, collection as LayerPayload["geojson"]);
          trimCache(cacheRef.current, 12);
          loadedKeysRef.current.set(layerId, cacheKey);
          setLoadedData((current) => ({ ...current, [layerId]: collection as LayerPayload["geojson"] }));
        }
        setPerformance(metricsRef.current.snapshot());
      } catch (loadError) {
        if (controller.signal.aborted || !active) return;
        if (shouldFallbackToMainThread(strategy, responseWasOk, responseBody, layer.feature_count)) {
          try {
            const fallbackStart = `${layerId}:fallback_parse_start`;
            const fallbackEnd = `${layerId}:fallback_parse_end`;
            if (responseBody === null) throw new Error("图层响应为空");
            metricsRef.current.mark(fallbackStart);
            const collection = parseGeoJsonBuffer(responseBody);
            metricsRef.current.mark(fallbackEnd);
            metricsRef.current.measure("json_parse_ms", fallbackStart, fallbackEnd);
            cacheRef.current.set(cacheKey, collection as LayerPayload["geojson"]);
            trimCache(cacheRef.current, 12);
            loadedKeysRef.current.set(layerId, cacheKey);
            setLoadedData((current) => ({ ...current, [layerId]: collection as LayerPayload["geojson"] }));
            setError(null);
            return;
          } catch {
            // Keep the original Worker error when the response is not valid
            // GeoJSON either.
          }
        }
        setError(loadError instanceof Error ? `${layer.name || layerId}: ${loadError.message}` : `${layer.name || layerId}: 图层加载失败`);
      } finally {
        if (active) setLoading((current) => ({ ...current, [layerId]: false }));
      }
    };

    for (const [index, layer] of layers.entries()) {
      const layerId = layer.id || layer.name || `layer-${index}`;
      void loadLayer(layer, layerId);
    }
    return () => {
      active = false;
      for (const controller of controllers.values()) controller.abort();
      for (const [jobId, job] of pendingJobsRef.current) {
        workerRef.current?.postMessage(createGeoJsonCancelRequest(jobId));
        pendingJobsRef.current.delete(jobId);
        job.reject(new Error("GeoJSON Worker 任务已取消"));
      }
    };
  }, [layers, requestId, debouncedViewportBbox, retryToken]);

  const resolvedLayers = layers.map((layer, index) => {
    const layerId = layer.id || layer.name || `layer-${index}`;
    if (requestId === null) return layer;
    const strategy = getRenderStrategy(layer);
    const requestBbox = strategy === "worker" ? debouncedViewportBbox || normalizeBbox(layer.extent) : undefined;
    const cacheKey = getLayerCacheKey(requestId, layerId, layer.version, layer.data_hash, requestBbox);
    if (loadedKeysRef.current.get(layerId) === cacheKey && loadedData[layerId]) {
      return { ...layer, geojson: loadedData[layerId], data_bbox: requestBbox ?? null };
    }
    return strategy === "worker" && requestBbox
      ? { ...layer, geojson: null, data_bbox: requestBbox }
      : layer;
  });
  return { layers: resolvedLayers, loading: Object.values(loading).some(Boolean), error, performance };
}

export function createBboxDebouncer(onChange: (bbox: Bbox | null) => void, delayMs: number) {
  let timer: ReturnType<typeof setTimeout> | undefined;
  return {
    schedule(bbox: Bbox | null) {
      if (timer !== undefined) clearTimeout(timer);
      timer = setTimeout(() => {
        timer = undefined;
        onChange(bbox);
      }, delayMs);
    },
    cancel() {
      if (timer !== undefined) clearTimeout(timer);
      timer = undefined;
    },
  };
}

function normalizeBbox(value: LayerPayload["extent"]): Bbox | undefined {
  if (!value || value.length !== 4 || value[0] >= value[2] || value[1] >= value[3]) return undefined;
  return value;
}

function parseWithWorker(
  worker: Worker,
  buffer: ArrayBuffer,
  layerId: string,
  layerVersion: number,
  jobIdRef: { current: number },
  pendingJobs: Map<number, PendingWorkerJob>,
  onBatch: (features: GeoJsonFeature[]) => void,
): Promise<GeoJsonFeatureCollection> {
  const requestId = ++jobIdRef.current;
  return new Promise((resolve, reject) => {
    pendingJobs.set(requestId, { layerId, layerVersion, features: [], onBatch, resolve, reject });
    // Transfer a copy so the original response remains usable if the Worker
    // fails and the caller needs to fall back to the main thread.
    const workerBuffer = copyBufferForWorker(buffer);
    const request = createGeoJsonParseRequest({ requestId, layerId, layerVersion, buffer: workerBuffer });
    worker.postMessage(request, [workerBuffer]);
  });
}

export function copyBufferForWorker(buffer: ArrayBuffer): ArrayBuffer {
  return buffer.slice(0);
}

export function appendGeoJsonBatch(
  current: LayerPayload["geojson"],
  batch: GeoJsonFeature[],
): GeoJsonFeatureCollection {
  const features = current?.features || [];
  return {
    type: "FeatureCollection",
    features: [...features, ...batch],
  };
}

export function createGeoJsonBatchBuffer() {
  const features: GeoJsonFeature[] = [];
  const collection: GeoJsonFeatureCollection = { type: "FeatureCollection", features };
  return {
    collection,
    append(batch: GeoJsonFeature[]): GeoJsonFeatureCollection {
      features.push(...batch);
      return collection;
    },
  };
}

function trimCache(cache: Map<string, LayerPayload["geojson"]>, maxEntries: number): void {
  while (cache.size > maxEntries) {
    const oldest = cache.keys().next().value;
    if (oldest === undefined) return;
    cache.delete(oldest);
  }
}

function parseErrorBuffer(buffer: ArrayBuffer): { error?: string; status?: string } | null {
  try {
    return JSON.parse(new TextDecoder().decode(buffer)) as { error?: string; status?: string };
  } catch {
    return null;
  }
}

export function parseGeoJsonBuffer(buffer: ArrayBuffer): GeoJsonFeatureCollection {
  return JSON.parse(new TextDecoder().decode(buffer)) as GeoJsonFeatureCollection;
}

export function shouldFallbackToMainThread(
  strategy: RenderStrategy,
  responseOk: boolean,
  responseBody: ArrayBuffer | null,
  featureCount?: number,
): boolean {
  return (
    strategy === "worker"
    && responseOk
    && responseBody !== null
    && Number.isFinite(featureCount)
    && Number(featureCount) <= GEOJSON_FEATURE_LIMIT
  );
}

const parseJsonBuffer = parseGeoJsonBuffer;
