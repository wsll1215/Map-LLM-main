import { useEffect, useRef } from "react";
import Map from "ol/Map";
import View from "ol/View";
import Feature from "ol/Feature";
import VectorLayer from "ol/layer/Vector";
import VectorSource from "ol/source/Vector";
import GeoJSON from "ol/format/GeoJSON";
import { transformExtent } from "ol/proj";
import type { LayerPayload } from "../types/api";
import { styleForLayer } from "../map/styles";

export function useOpenLayersMap(target: HTMLElement | null, layers: LayerPayload[], visibleLayers: Record<string, boolean>) {
  const mapRef = useRef<Map | null>(null);
  const layerRefs = useRef(new Map<string, VectorLayer<VectorSource>>());
  useEffect(() => {
    if (!target || mapRef.current) return;
    mapRef.current = new Map({ target, layers: [], view: new View({ center: [0, 0], zoom: 2, projection: "EPSG:3857" }) });
    return () => { mapRef.current?.setTarget(undefined); mapRef.current = null; layerRefs.current.clear(); };
  }, [target]);
  useEffect(() => {
    const map = mapRef.current; if (!map) return;
    const format = new GeoJSON(); const incoming = new Set(layers.map((layer, index) => layer.id || layer.name || `layer-${index}`));
    layerRefs.current.forEach((layer, id) => { if (!incoming.has(id)) { map.removeLayer(layer); layerRefs.current.delete(id); } });
    layers.forEach((layer, index) => {
      const layerId = layer.id || layer.name || `layer-${index}`;
      let vector = layerRefs.current.get(layerId);
      if (!vector) { vector = new VectorLayer({ source: new VectorSource(), style: styleForLayer(layer) }); layerRefs.current.set(layerId, vector); map.addLayer(vector); }
      vector.setVisible(visibleLayers[layerId] !== false);
      vector.setStyle(styleForLayer(layer));
      const source = vector.getSource(); if (!source) return;
      source.clear();
      if (!layer.geojson) return;
      try { const features = format.readFeatures(layer.geojson, { featureProjection: "EPSG:3857" }); source.addFeatures(features as Feature[]); }
      catch { /* invalid geometry is rendered by the PNG fallback in the workbench */ }
      if (source.getFeatures().length) map.getView().fit(source.getExtent(), { padding: [36, 36, 36, 36], maxZoom: 16, duration: 250 });
    });
    const extent = layers[0]?.geojson && (layers[0].geojson as unknown as { bbox?: number[] }).bbox;
    if (extent && extent.length >= 4) map.getView().fit(transformExtent(extent.slice(0, 4), "EPSG:4326", "EPSG:3857"), { padding: [36, 36, 36, 36], maxZoom: 16 });
  }, [layers, visibleLayers]);
  return mapRef;
}
