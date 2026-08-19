import { useState } from "react";
import { useOpenLayersMap } from "../hooks/useOpenLayersMap";
import type { LayerPayload } from "../types/api";
import "ol/ol.css";

export function MapCanvas({ layers }: { layers: LayerPayload[] }) {
  const [target, setTarget] = useState<HTMLDivElement | null>(null);
  const [visible, setVisible] = useState<Record<string, boolean>>({});
  useOpenLayersMap(target, layers, visible);
  return <div className="map-shell"><div ref={setTarget} className="map-canvas" />
    {layers.length === 0 && <div className="map-empty">等待结构化图层事件…</div>}
    <div className="map-legend">{layers.map((layer) => <button key={layer.id} className="legend-item" onClick={() => setVisible((state) => ({ ...state, [layer.id]: state[layer.id] === false }))}><span className="legend-dot" />{layer.name || layer.id}</button>)}</div>
  </div>;
}
