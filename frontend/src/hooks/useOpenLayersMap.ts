import { useEffect, useRef } from "react";
import OlMap from "ol/Map";
import View from "ol/View";
import VectorLayer from "ol/layer/Vector";
import VectorSource from "ol/source/Vector";
import VectorTileLayer from "ol/layer/VectorTile";
import VectorTileSource from "ol/source/VectorTile";
import MVT from "ol/format/MVT";
import { createXYZ } from "ol/tilegrid";
import { createEmpty, extend, isEmpty, type Extent } from "ol/extent";
import { toLonLat, transformExtent } from "ol/proj";
import type { LayerPayload } from "../types/api";
import { styleForFeature, styleForLayer } from "../map/styles";
import { getLayerDataKey } from "../map/layerRegistry";
import { getLayerTileUrl, type Bbox } from "../map/mapDataLoader";
import { MVT_TILE_SIZE, getRenderStrategy, renderFeaturesPerFrame } from "../map/renderPolicy";
import { createPerformanceMetrics, observeBrowserPerformance, type PerformanceSnapshot } from "../map/performanceMetrics";
import { readGeoJsonFeatures, scheduleRenderFrame, scheduleRenderTask } from "../map/renderers";

type RenderLayer = VectorLayer<VectorSource> | VectorTileLayer<VectorTileSource>;

export function useOpenLayersMap(
  target: HTMLElement | null,
  requestId: number | null,
  layers: LayerPayload[],
  visibleLayers: Record<string, boolean>,
  onViewportChange?: (bbox: Bbox) => void,
  onError?: (message: string) => void,
  mapCrs = "EPSG:4326",
  onPerformanceMetrics?: (metrics: PerformanceSnapshot) => void,
) {
  const mapRef = useRef<OlMap | null>(null);
  const layerRefs = useRef(new globalThis.Map<string, RenderLayer>());
  const dataKeysRef = useRef(new globalThis.Map<string, string>());
  const tileRetryRef = useRef(new globalThis.Map<string, number>());
  const renderedFeatureCountsRef = useRef(new globalThis.Map<string, number>());
  const scheduledFeatureCountsRef = useRef(new globalThis.Map<string, number>());
  const renderGenerationRef = useRef(new globalThis.Map<string, number>());
  const metricsRef = useRef(createPerformanceMetrics());
  const dataReadyRef = useRef(false);
  const firstVisibleRecordedRef = useRef(false);
  const interactiveRecordedRef = useRef(false);
  const fittedRef = useRef(false);
  const viewportRef = useRef(onViewportChange);
  const errorRef = useRef(onError);
  const metricsCallbackRef = useRef(onPerformanceMetrics);
  viewportRef.current = onViewportChange;
  errorRef.current = onError;
  metricsCallbackRef.current = onPerformanceMetrics;
  useEffect(() => {
    if (!target || mapRef.current) return;
    // OpenLayers 10 uses its Canvas renderer by default; keeping the map
    // instance unmounted only when the target disappears preserves interactions.
    mapRef.current = new OlMap({ target, layers: [], view: new View({ center: [0, 0], zoom: 2, projection: "EPSG:3857" }) });
    const map = mapRef.current;
    metricsRef.current.mark("fetch_start");
    const disconnectPerformanceObserver = observeBrowserPerformance(metricsRef.current);
    const handleRenderComplete = () => {
      if (!dataReadyRef.current) return;
      metricsRef.current.mark("render_end");
      metricsRef.current.measure("render_ms", "render_start", "render_end");
      if (!firstVisibleRecordedRef.current) {
        metricsRef.current.mark("first_visible");
        firstVisibleRecordedRef.current = true;
      }
      metricsCallbackRef.current?.(metricsRef.current.snapshot());
    };
    const handlePointerDrag = () => {
      if (!dataReadyRef.current || interactiveRecordedRef.current) return;
      metricsRef.current.mark("interactive");
      interactiveRecordedRef.current = true;
      metricsCallbackRef.current?.(metricsRef.current.snapshot());
    };
    map.on("rendercomplete", handleRenderComplete);
    map.on("pointerdrag", handlePointerDrag);
    const reportViewport = () => {
      const size = map.getSize();
      if (!size) return;
      const extent = map.getView().calculateExtent(size);
      const southWest = toLonLat([extent[0], extent[1]]);
      const northEast = toLonLat([extent[2], extent[3]]);
      if (southWest[0] < northEast[0] && southWest[1] < northEast[1]) {
        viewportRef.current?.([southWest[0], southWest[1], northEast[0], northEast[1]]);
      }
    };
    map.on("moveend", reportViewport);
    return () => {
      map.un("moveend", reportViewport);
      map.un("rendercomplete", handleRenderComplete);
      map.un("pointerdrag", handlePointerDrag);
      disconnectPerformanceObserver();
      map.setTarget(undefined);
      mapRef.current = null;
      layerRefs.current.clear();
      dataKeysRef.current.clear();
      renderedFeatureCountsRef.current.clear();
      scheduledFeatureCountsRef.current.clear();
      renderGenerationRef.current.clear();
      firstVisibleRecordedRef.current = false;
      interactiveRecordedRef.current = false;
      dataReadyRef.current = false;
      fittedRef.current = false;
    };
  }, [target]);
  useEffect(() => {
    metricsRef.current.reset();
    firstVisibleRecordedRef.current = false;
    interactiveRecordedRef.current = false;
    dataReadyRef.current = false;
    fittedRef.current = false;
    onPerformanceMetrics?.(metricsRef.current.snapshot());
  }, [requestId]);
  useEffect(() => {
    const map = mapRef.current; if (!map) return;
    const incoming = new Set(layers.map((layer, index) => layer.id || layer.name || `layer-${index}`));
    const nextGeneration = (layerId: string) => {
      const generation = (renderGenerationRef.current.get(layerId) || 0) + 1;
      renderGenerationRef.current.set(layerId, generation);
      return generation;
    };
    if (incoming.size === 0) { fittedRef.current = false; dataKeysRef.current.clear(); dataReadyRef.current = false; }
    const visibleExtent = createEmpty();
    let hasVisibleExtent = false;
    layerRefs.current.forEach((layer, id) => {
      if (!incoming.has(id)) {
        map.removeLayer(layer);
        layerRefs.current.delete(id);
        dataKeysRef.current.delete(id);
        renderedFeatureCountsRef.current.delete(id);
        scheduledFeatureCountsRef.current.delete(id);
        nextGeneration(id);
      }
    });
    metricsRef.current.mark("render_start");
    layers.forEach((layer, index) => {
      const layerId = layer.id || layer.name || `layer-${index}`;
      const isVisible = visibleLayers[layerId] !== false;
      const wantsMvt = layer.render_mode === "mvt" && requestId !== null;
      let vector = layerRefs.current.get(layerId);
      const hasMvt = vector instanceof VectorTileLayer;
      if (!vector || hasMvt !== wantsMvt) {
        if (vector) {
          map.removeLayer(vector);
          dataKeysRef.current.delete(layerId);
          renderedFeatureCountsRef.current.delete(layerId);
          scheduledFeatureCountsRef.current.delete(layerId);
          nextGeneration(layerId);
          tileRetryRef.current.delete(layerId);
        }
        if (wantsMvt) {
          const source = new VectorTileSource({
            format: new MVT(),
            tileGrid: createXYZ({ tileSize: MVT_TILE_SIZE, maxZoom: 22 }),
            url: getLayerTileUrl(requestId, { ...layer, id: layerId }),
          });
          source.on("tileloadend", (event) => {
            tileRetryRef.current.delete(tileKey(event));
            dataReadyRef.current = true;
          });
          source.on("tileloaderror", (event) => {
            const key = tileKey(event);
            const attempt = tileRetryRef.current.get(key) || 0;
            if (attempt < 3) {
              tileRetryRef.current.set(key, attempt + 1);
              window.setTimeout(() => source.refresh(), 500 * (attempt + 1));
              return;
            }
            errorRef.current?.(String(layer.name || layerId) + ": MVT 瓦片加载失败，已切换 PNG 预览，请重试");
          });
          vector = new VectorTileLayer({ source, style: (feature) => styleForFeature(layer, feature) });
        } else {
          vector = new VectorLayer({ source: new VectorSource(), style: layer.render_spec?.enabled ? (feature) => styleForFeature(layer, feature) : styleForLayer(layer) });
        }
        layerRefs.current.set(layerId, vector);
        map.addLayer(vector);
      }
      vector.setVisible(isVisible);
      vector.setStyle(layer.render_spec?.enabled ? (feature) => styleForFeature(layer, feature) : styleForLayer(layer));
      vector.setZIndex(layer.z_order ?? index);
      if (wantsMvt) {
        const tileExtent = layer.extent ? transformExtent(layer.extent, mapCrs, "EPSG:3857") : null;
        if (tileExtent && !isEmpty(tileExtent)) { extend(visibleExtent, tileExtent); hasVisibleExtent = true; }
        dataKeysRef.current.set(layerId, getLayerDataKey({ ...layer, id: layerId }));
        return;
      }
      const source = vector.getSource(); if (!(source instanceof VectorSource)) return;
      const dataKey = getLayerDataKey({ ...layer, id: layerId });
      const previousKey = dataKeysRef.current.get(layerId) ?? "";
      const dataChanged = previousKey !== dataKey;
      if (dataChanged) {
        dataKeysRef.current.set(layerId, dataKey);
        source.clear();
        renderedFeatureCountsRef.current.set(layerId, 0);
        scheduledFeatureCountsRef.current.set(layerId, 0);
        nextGeneration(layerId);
      }
      if (!isVisible) {
        if (source.getFeatures().length) source.clear();
        renderedFeatureCountsRef.current.set(layerId, 0);
        scheduledFeatureCountsRef.current.set(layerId, 0);
        nextGeneration(layerId);
        return;
      }
      if (!layer.geojson) return;
      const currentFeatureCount = layer.geojson.features.length;
      const renderedCount = renderedFeatureCountsRef.current.get(layerId) || 0;
      const scheduledCount = scheduledFeatureCountsRef.current.get(layerId) || 0;
      if (currentFeatureCount < renderedCount || currentFeatureCount < scheduledCount) {
        source.clear();
        renderedFeatureCountsRef.current.set(layerId, 0);
        scheduledFeatureCountsRef.current.set(layerId, 0);
        nextGeneration(layerId);
      }
      const startIndex = Math.max(
        renderedFeatureCountsRef.current.get(layerId) || 0,
        scheduledFeatureCountsRef.current.get(layerId) || 0,
      );
      if (startIndex >= currentFeatureCount) {
        const sourceExtent = source.getExtent();
        if (sourceExtent && !isEmpty(sourceExtent) && source.getFeatures().length) {
          extend(visibleExtent, sourceExtent);
          hasVisibleExtent = true;
        }
        return;
      }
      const generation = renderGenerationRef.current.get(layerId) || 0;
      const maxFeaturesPerFrame = getRenderStrategy(layer) === "worker"
        ? renderFeaturesPerFrame(currentFeatureCount)
        : Number.POSITIVE_INFINITY;
      const renderNextBatch = (requestedStart: number) => {
        if (renderGenerationRef.current.get(layerId) !== generation) return;
        const rendered = renderedFeatureCountsRef.current.get(layerId) || 0;
        const scheduled = scheduledFeatureCountsRef.current.get(layerId) || 0;
        if (requestedStart < rendered || (requestedStart < scheduled && requestedStart >= rendered)) return;
        const currentCollection = layer.geojson;
        if (!currentCollection) return;
        const pending = getUnrenderedGeoJsonFeatures(currentCollection, requestedStart, maxFeaturesPerFrame);
        if (!pending.features.length) return;
        const nextStart = requestedStart + pending.features.length;
        scheduledFeatureCountsRef.current.set(layerId, nextStart);
        metricsRef.current.mark(`${layerId}:ol_start`);
        const schedule = rendered === 0 ? scheduleRenderFrame : scheduleRenderTask;
        schedule(() => {
          if (renderGenerationRef.current.get(layerId) !== generation) return;
          try {
            const features = readGeoJsonFeatures(pending);
            source.addFeatures(features);
            if (features.length > 0) dataReadyRef.current = true;
            renderedFeatureCountsRef.current.set(layerId, nextStart);
            metricsRef.current.mark(`${layerId}:ol_end`);
            metricsRef.current.measure("ol_feature_convert_ms", `${layerId}:ol_start`, `${layerId}:ol_end`);
            if (!fittedRef.current) {
              fittedRef.current = fitVisibleLayers(map, layerRefs.current, visibleLayers);
            }
            metricsCallbackRef.current?.(metricsRef.current.snapshot());
            if (nextStart < currentCollection.features.length) renderNextBatch(nextStart);
          } catch {
            errorRef.current?.(`${layer.name || layerId}: GeoJSON 要素转换失败，已保留 PNG 预览`);
          }
        });
      };
      renderNextBatch(startIndex);
    });
    if (!fittedRef.current && hasVisibleExtent && !isEmpty(visibleExtent)) {
      map.getView().fit(visibleExtent, { padding: [36, 36, 36, 36], maxZoom: 16, duration: 250 });
      fittedRef.current = true;
    }
  }, [target, requestId, layers, visibleLayers, mapCrs]);
  return mapRef;
}

export function getUnrenderedGeoJsonFeatures<T>(
  collection: { type: "FeatureCollection"; features: T[] },
  renderedCount: number,
  maxFeatures = Number.POSITIVE_INFINITY,
) {
  const start = Math.max(0, renderedCount);
  return {
    type: "FeatureCollection" as const,
    features: collection.features.slice(start, start + maxFeatures),
  };
}

function fitVisibleLayers(
  map: OlMap,
  layerRefs: globalThis.Map<string, RenderLayer>,
  visibleLayers: Record<string, boolean>,
): boolean {
  const extent = createEmpty();
  let hasExtent = false;
  layerRefs.forEach((layer, layerId) => {
    if (visibleLayers[layerId] === false) return;
    if (layer instanceof VectorLayer) {
      const source = layer.getSource();
      const sourceExtent = source?.getExtent();
      if (source && source.getFeatures().length && isRenderableExtent(sourceExtent)) {
        extend(extent, sourceExtent);
        hasExtent = true;
      }
      return;
    }
  });
  if (!hasExtent || !isRenderableExtent(extent)) return false;
  map.getView().fit(extent, { padding: [36, 36, 36, 36], maxZoom: 16, duration: 250 });
  return true;
}

export function isRenderableExtent(extent: Extent | null | undefined): extent is Extent {
  return extent !== null && extent !== undefined && !isEmpty(extent);
}

function tileKey(event: { tile?: { getTileCoord?: () => number[] } }): string {
  const coordinate = event.tile?.getTileCoord?.();
  return coordinate?.join("/") || "unknown";
}
