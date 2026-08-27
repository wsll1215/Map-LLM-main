import { useEffect, useRef, useState } from "react";
import type { LayerPayload } from "../types/api";
import { getLayerCacheKey, getLayerDataUrl, shouldRetryLayerFetch, type Bbox } from "../map/mapDataLoader";
import { getRenderStrategy } from "../map/renderPolicy";
import type { GeoJsonFeature, GeoJsonFeatureCollection } from "../map/geojsonParser";
import type { GeoJsonWorkerResponse } from "../map/workerProtocol";

type PendingWorkerJob = {
  layerId: string;
  layerVersion: number;
  features: GeoJsonFeature[];
  resolve: (value: GeoJsonFeatureCollection) => void;
  reject: (reason: Error) => void;
};

export function useMapData(requestId: number | null, layers: LayerPayload[], viewportBbox?: Bbox | null, retryToken = 0) {
  const workerRef = useRef<Worker | null>(null);
  const jobIdRef = useRef(0);
  const pendingJobsRef = useRef(new Map<number, PendingWorkerJob>());
  const cacheRef = useRef(new Map<string, LayerPayload["geojson"]>());
  const loadedKeysRef = useRef(new Map<string, string>());
  const [loadedData, setLoadedData] = useState<Record<string, LayerPayload["geojson"]>>({});
  const [loading, setLoading] = useState<Record<string, boolean>>({});
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    try {
      const worker = new Worker(new URL("../workers/geojsonParser.worker.ts", import.meta.url), { type: "module" });
      worker.onmessage = ({ data }: MessageEvent<GeoJsonWorkerResponse>) => {
        const job = pendingJobsRef.current.get(data.requestId);
        if (!job) return;
        if (data.type === "error") {
          pendingJobsRef.current.delete(data.requestId);
          job.reject(new Error(data.message));
          return;
        }
        job.features.push(...data.features);
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
          worker.postMessage({ type: "cancel", requestId: jobId });
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

    const loadLayer = async (layer: LayerPayload, layerId: string) => {
      const strategy = getRenderStrategy(layer);
      if (strategy === "mvt" || strategy === "pmtiles") {
        setLoading((current) => ({ ...current, [layerId]: false }));
        if (strategy === "pmtiles") {
          setError(String(layer.name || layerId) + ": PMTiles 尚未配置可用数据源，已保留 PNG 预览");
        }
        return;
      }
      const requestBbox = strategy === "worker" ? viewportBbox || normalizeBbox(layer.extent) : undefined;
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
      try {
        let response: Response;
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
        const body = await response.json().catch(() => null) as { error?: string; status?: string } | null;
        if (!response.ok) throw new Error(body?.error || `图层加载失败 (${response.status})`);
        if (body && "status" in body && body.status === "pending") {
          throw new Error(body.error || "图层快照仍在生成");
        }
        const collection = body as unknown as GeoJsonFeatureCollection;
        const parsed = strategy === "worker" && workerRef.current
          ? await parseWithWorker(workerRef.current, collection, layerId, layer.version ?? 0, jobIdRef, pendingJobsRef.current)
          : collection;
        if (!active || controller.signal.aborted) return;
        cacheRef.current.set(cacheKey, parsed as LayerPayload["geojson"]);
        loadedKeysRef.current.set(layerId, cacheKey);
        setLoadedData((current) => ({ ...current, [layerId]: parsed as LayerPayload["geojson"] }));
      } catch (loadError) {
        if (controller.signal.aborted || !active) return;
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
        workerRef.current?.postMessage({ type: "cancel", requestId: jobId });
        pendingJobsRef.current.delete(jobId);
        job.reject(new Error("GeoJSON Worker 任务已取消"));
      }
    };
  }, [layers, requestId, viewportBbox, retryToken]);

  const resolvedLayers = layers.map((layer, index) => {
    const layerId = layer.id || layer.name || `layer-${index}`;
    if (requestId === null) return layer;
    const strategy = getRenderStrategy(layer);
    const requestBbox = strategy === "worker" ? viewportBbox || normalizeBbox(layer.extent) : undefined;
    const cacheKey = getLayerCacheKey(requestId, layerId, layer.version, layer.data_hash, requestBbox);
    return loadedKeysRef.current.get(layerId) === cacheKey && loadedData[layerId]
      ? { ...layer, geojson: loadedData[layerId] }
      : layer;
  });
  return { layers: resolvedLayers, loading: Object.values(loading).some(Boolean), error };
}

function normalizeBbox(value: LayerPayload["extent"]): Bbox | undefined {
  if (!value || value.length !== 4 || value[0] >= value[2] || value[1] >= value[3]) return undefined;
  return value;
}

function parseWithWorker(
  worker: Worker,
  collection: GeoJsonFeatureCollection,
  layerId: string,
  layerVersion: number,
  jobIdRef: { current: number },
  pendingJobs: Map<number, PendingWorkerJob>,
): Promise<GeoJsonFeatureCollection> {
  const requestId = ++jobIdRef.current;
  return new Promise((resolve, reject) => {
    pendingJobs.set(requestId, { layerId, layerVersion, features: [], resolve, reject });
    worker.postMessage({ type: "parse", requestId, layerId, layerVersion, collection });
  });
}
