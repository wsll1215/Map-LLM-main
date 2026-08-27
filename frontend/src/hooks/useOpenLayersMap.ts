import { useEffect, useRef } from "react";
import OlMap from "ol/Map";
import View from "ol/View";
import Feature from "ol/Feature";
import VectorLayer from "ol/layer/Vector";
import VectorSource from "ol/source/Vector";
import VectorTileLayer from "ol/layer/VectorTile";
import VectorTileSource from "ol/source/VectorTile";
import MVT from "ol/format/MVT";
import GeoJSON from "ol/format/GeoJSON";
import { createEmpty, extend, isEmpty } from "ol/extent";
import { toLonLat, transformExtent } from "ol/proj";
import type { LayerPayload } from "../types/api";
import { styleForFeature, styleForLayer } from "../map/styles";
import { getLayerDataKey, shouldLoadLayerData } from "../map/layerRegistry";
import { getLayerTileUrl, type Bbox } from "../map/mapDataLoader";

type RenderLayer = VectorLayer<VectorSource> | VectorTileLayer<VectorTileSource>;

export function useOpenLayersMap(
  target: HTMLElement | null,
  requestId: number | null,
  layers: LayerPayload[],
  visibleLayers: Record<string, boolean>,
  onViewportChange?: (bbox: Bbox) => void,
  onError?: (message: string) => void,
  mapCrs = "EPSG:4326",
) {
  const mapRef = useRef<OlMap | null>(null);
  const layerRefs = useRef(new globalThis.Map<string, RenderLayer>());
  const dataKeysRef = useRef(new globalThis.Map<string, string>());
  const tileRetryRef = useRef(new globalThis.Map<string, number>());
  const fittedRef = useRef(false);
  const viewportRef = useRef(onViewportChange);
  const errorRef = useRef(onError);
  viewportRef.current = onViewportChange;
  errorRef.current = onError;
  useEffect(() => {
    if (!target || mapRef.current) return;
    // OpenLayers 10 uses its Canvas renderer by default; keeping the map
    // instance unmounted only when the target disappears preserves interactions.
    mapRef.current = new OlMap({ target, layers: [], view: new View({ center: [0, 0], zoom: 2, projection: "EPSG:3857" }) });
    const map = mapRef.current;
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
    return () => { map.un("moveend", reportViewport); map.setTarget(undefined); mapRef.current = null; layerRefs.current.clear(); dataKeysRef.current.clear(); fittedRef.current = false; };
  }, [target]);
  useEffect(() => {
    const map = mapRef.current; if (!map) return;
    const format = new GeoJSON(); const incoming = new Set(layers.map((layer, index) => layer.id || layer.name || `layer-${index}`));
    if (incoming.size === 0) { fittedRef.current = false; dataKeysRef.current.clear(); }
    const visibleExtent = createEmpty();
    let hasVisibleExtent = false;
    layerRefs.current.forEach((layer, id) => { if (!incoming.has(id)) { map.removeLayer(layer); layerRefs.current.delete(id); } });
    layers.forEach((layer, index) => {
      const layerId = layer.id || layer.name || `layer-${index}`;
      const isVisible = visibleLayers[layerId] !== false;
      const wantsMvt = layer.render_mode === "mvt" && requestId !== null;
      let vector = layerRefs.current.get(layerId);
      const hasMvt = vector instanceof VectorTileLayer;
      if (!vector || hasMvt !== wantsMvt) {
        if (vector) map.removeLayer(vector);
        if (wantsMvt) {
          const source = new VectorTileSource({ format: new MVT(), url: getLayerTileUrl(requestId, { ...layer, id: layerId }) });
         source.on("tileloaderror", () => errorRef.current?.(`${layer.name || layerId}: MVT 瓦片加载失败，请查看 PNG 预览或重试`));
          source.on("tileloaderror", () => {
            const attempt = tileRetryRef.current.get(layerId) || 0;
            if (attempt < 3) {
              tileRetryRef.current.set(layerId, attempt + 1);
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
      if (!shouldLoadLayerData(previousKey, dataKey, Boolean(layer.geojson))) return;
      dataKeysRef.current.set(layerId, dataKey);
      source.clear();
      if (!isVisible || !layer.geojson) return;
      try { const features = format.readFeatures(layer.geojson, { featureProjection: "EPSG:3857" }); source.addFeatures(features as Feature[]); }
      catch { /* invalid geometry is rendered by the PNG fallback in the workbench */ }
      const sourceExtent = source.getExtent();
      if (sourceExtent && !isEmpty(sourceExtent) && source.getFeatures().length) {
        extend(visibleExtent, sourceExtent);
        hasVisibleExtent = true;
      }
    });
    if (!fittedRef.current && hasVisibleExtent && !isEmpty(visibleExtent)) {
      map.getView().fit(visibleExtent, { padding: [36, 36, 36, 36], maxZoom: 16, duration: 250 });
      fittedRef.current = true;
    }
  }, [target, requestId, layers, visibleLayers, mapCrs]);
  return mapRef;
}
