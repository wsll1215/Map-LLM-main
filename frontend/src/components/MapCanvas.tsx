import { useState } from "react";
import { useOpenLayersMap } from "../hooks/useOpenLayersMap";
import type { LayerPayload } from "../types/api";
import type { Bbox } from "../map/mapDataLoader";
import "ol/ol.css";

type MapStatus = "idle" | "pending" | "processing" | "completed" | "partial" | "failed";

const emptyStateCopy: Record<MapStatus, { title: string; detail: string }> = {
  idle: { title: "地图将在这里出现", detail: "从右侧提交一条制图需求，生成结果会直接加载到画布。" },
  pending: { title: "已收到制图需求", detail: "正在创建任务并准备数据。" },
  processing: { title: "正在生成地图", detail: "数据、图层与地图样式会依次加载。" },
  completed: { title: "本次任务未产生图层", detail: "可以补充地图范围或数据要求后再次生成。" },
  partial: { title: "地图部分生成", detail: "当前结果可以查看，补齐缺失图层后再完成任务。" },
  failed: { title: "地图未能生成", detail: "请查看右侧错误信息，调整需求后重新提交。" },
};

export function MapCanvas({ requestId, layers, status, mapCrs, dataError, dataLoading, onViewportChange, onError, onRetry }: { requestId: number | null; layers: LayerPayload[]; status: MapStatus; mapCrs?: string | null; dataError?: string | null; dataLoading?: boolean; onViewportChange?: (bbox: Bbox) => void; onError?: (message: string) => void; onRetry?: () => void }) {
  const [target, setTarget] = useState<HTMLDivElement | null>(null);
  const [visible, setVisible] = useState<Record<string, boolean>>({});
  useOpenLayersMap(target, requestId, layers, visible, onViewportChange, onError, mapCrs ?? undefined);
  const emptyState = emptyStateCopy[status];

  return <div className="map-shell"><div ref={setTarget} className="map-canvas" />
    {dataError && <div className="map-data-error" role="alert"><span>{dataError}</span>{onRetry && <button type="button" onClick={onRetry}>重试</button>}</div>}
    {dataLoading && layers.length > 0 && <div className="map-data-loading" role="status" aria-live="polite">正在加载图层数据</div>}
    {layers.length === 0 && <div className={`map-empty map-empty-${status}`} aria-live="polite" aria-busy={status === "pending" || status === "processing"}><div className="map-empty-mark" aria-hidden="true"><span /><span /><span /></div><strong>{emptyState.title}</strong><p>{emptyState.detail}</p>{(status === "pending" || status === "processing") && <div className="map-progress"><span /></div>}</div>}
    <div className="map-legend">{layers.map((layer, index) => { const id = layer.id || layer.name || `layer-${index}`; const spec = layer.render_spec; const colors = spec?.colors || []; const entries = spec?.kind === "categorical" ? (spec.values || []).map((label, itemIndex) => ({ label, color: spec.value_colors?.[label] || colors[itemIndex] })) : (spec?.labels || []).map((label, itemIndex) => ({ label, color: colors[itemIndex] })); return <div className="legend-group" key={id}><button type="button" className="legend-item" onClick={() => setVisible((state) => ({ ...state, [id]: state[id] === false }))}><span className="legend-dot" style={{ backgroundColor: colors[0] || String(layer.style?.color || "#2563eb") }} />{layer.name || id}</button>{entries.length > 0 && <div className="legend-class-list">{entries.map((entry) => <span className="legend-class" key={entry.label}><i style={{ backgroundColor: entry.color }} />{entry.label}</span>)}</div>}</div>; })}</div>
  </div>;
}
