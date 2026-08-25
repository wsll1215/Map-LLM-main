import { useState } from "react";
import { useOpenLayersMap } from "../hooks/useOpenLayersMap";
import type { LayerPayload } from "../types/api";
import "ol/ol.css";

type MapStatus = "idle" | "pending" | "processing" | "completed" | "failed";

const emptyStateCopy: Record<MapStatus, { title: string; detail: string }> = {
  idle: { title: "地图将在这里出现", detail: "从右侧提交一条制图需求，生成结果会直接加载到画布。" },
  pending: { title: "已收到制图需求", detail: "正在创建任务并准备数据。" },
  processing: { title: "正在生成地图", detail: "数据、图层与地图样式会依次加载。" },
  completed: { title: "本次任务未产生图层", detail: "可以补充地图范围或数据要求后再次生成。" },
  failed: { title: "地图未能生成", detail: "请查看右侧错误信息，调整需求后重新提交。" },
};

export function MapCanvas({ layers, status, dataError, dataLoading }: { layers: LayerPayload[]; status: MapStatus; dataError?: string | null; dataLoading?: boolean }) {
  const [target, setTarget] = useState<HTMLDivElement | null>(null);
  const [visible, setVisible] = useState<Record<string, boolean>>({});
  useOpenLayersMap(target, layers, visible);
  const emptyState = emptyStateCopy[status];

  return <div className="map-shell"><div ref={setTarget} className="map-canvas" />
    {dataError && <div className="map-data-error" role="alert">{dataError}</div>}
    {dataLoading && layers.length > 0 && <div className="map-data-loading" role="status" aria-live="polite">正在加载图层数据</div>}
    {layers.length === 0 && <div className={`map-empty map-empty-${status}`} aria-live="polite" aria-busy={status === "pending" || status === "processing"}><div className="map-empty-mark" aria-hidden="true"><span /><span /><span /></div><strong>{emptyState.title}</strong><p>{emptyState.detail}</p>{(status === "pending" || status === "processing") && <div className="map-progress"><span /></div>}</div>}
    <div className="map-legend">{layers.map((layer, index) => { const id = layer.id || layer.name || `layer-${index}`; return <button key={id} className="legend-item" onClick={() => setVisible((state) => ({ ...state, [id]: state[id] === false }))}><span className="legend-dot" />{layer.name || id}</button>; })}</div>
  </div>;
}
