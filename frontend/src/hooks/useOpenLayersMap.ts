import { useEffect, useRef } from "react";
import OlMap from "ol/Map";
import View from "ol/View";
import Feature from "ol/Feature";
import VectorLayer from "ol/layer/Vector";
import VectorSource from "ol/source/Vector";
import GeoJSON from "ol/format/GeoJSON";
import { createEmpty, extend, isEmpty } from "ol/extent";
import type { LayerPayload } from "../types/api";
import { styleForLayer } from "../map/styles";
import { getLayerDataKey, shouldLoadLayerData } from "../map/layerRegistry";

export function useOpenLayersMap(target: HTMLElement | null, layers: LayerPayload[], visibleLayers: Record<string, boolean>) {
  const mapRef = useRef<OlMap | null>(null);
  const layerRefs = useRef(new globalThis.Map<string, VectorLayer<VectorSource>>());
  const dataKeysRef = useRef(new globalThis.Map<string, string>());
  const fittedRef = useRef(false);
  useEffect(() => {
    if (!target || mapRef.current) return;
    mapRef.current = new OlMap({ target, layers: [], view: new View({ center: [0, 0], zoom: 2, projection: "EPSG:3857" }) });
    return () => { mapRef.current?.setTarget(undefined); mapRef.current = null; layerRefs.current.clear(); dataKeysRef.current.clear(); fittedRef.current = false; };
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
      let vector = layerRefs.current.get(layerId);
      if (!vector) { vector = new VectorLayer({ source: new VectorSource(), style: styleForLayer(layer) }); layerRefs.current.set(layerId, vector); map.addLayer(vector); }
      vector.setVisible(isVisible);
      vector.setStyle(styleForLayer(layer));
      vector.setZIndex(layer.z_order ?? index);
      const source = vector.getSource(); if (!source) return;
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
  }, [target, layers, visibleLayers]);
  return mapRef;
}
