import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useReducer,
  useRef,
  useState,
  type Dispatch,
  type FormEvent,
} from "react";
import { mappingApi } from "./api/mappingApi";
import { initialWorkbenchState, workbenchReducer, type WorkbenchAction } from "./state/workbenchReducer";
import { useMapBuildStream } from "./hooks/useMapBuildStream";
import { useSessionHistory } from "./hooks/useSessionHistory";
import { useConversation } from "./hooks/useConversation";
import { useMapData } from "./hooks/useMapData";
import { useTaskStatus } from "./hooks/useTaskStatus";
import type { GeneratedMap, MapRequestSummary } from "./types/api";
import "./styles/app.css";

const MapCanvas = lazy(() => import("./components/MapCanvas").then((module) => ({ default: module.MapCanvas })));
export default function App() {
  const [state, dispatch] = useReducer(workbenchReducer, initialWorkbenchState);
  const [prompt, setPrompt] = useState("");
  const [generatedMaps, setGeneratedMaps] = useState<GeneratedMap[]>([]);
  const [finalMapLoading, setFinalMapLoading] = useState(false);
  const [finalMapError, setFinalMapError] = useState<string | null>(null);
  const [historyNotice, setHistoryNotice] = useState<string | null>(null);
  const mapStageRef = useRef<HTMLDivElement | null>(null);
  const submitInFlightRef = useRef(false);
  const { history, loading: historyLoading, error: historyError, refresh: loadHistory } = useSessionHistory();
  const stream = useMapBuildStream(dispatch);
  const conversation = useConversation(state.requestId);
  const mapData = useMapData(state.status === "completed" || state.status === "failed" || state.status === "needs_clarification" ? null : state.requestId, state.layers);
  const isWorking = state.submissionInFlight || state.status === "pending" || state.status === "processing";
  const hasStoredMap = generatedMaps.some((map) => map.file_exists !== false);
  const canContinue = state.requestId !== null && (state.status === "needs_clarification" || state.status === "completed" || (state.status === "failed" && hasStoredMap));
  const latestAssistant = isWorking ? null : [...state.messages].reverse().find((message) => message.role === "assistant");
  const latestRequest = [...state.messages].reverse().find((message) => message.role === "user");
  const availableMap = generatedMaps.find((map) => map.file_exists !== false) ?? null;
  const finalMapUrl = availableMap?.file_path || (state.status === "completed" ? null : state.previewUrl);
  const terminalWithResult = (state.status === "completed" || state.status === "failed") && hasStoredMap;
  const showingFinalMap = terminalWithResult && Boolean(availableMap) && !finalMapError;
  const progressStep = state.status === "idle" ? 0 : state.status === "pending" ? 1 : state.status === "processing" ? 2 : state.status === "needs_clarification" ? 1 : state.status === "completed" ? 3 : 2;
  useTaskStatus(state.requestId, isWorking, dispatch);

  const loadGeneratedMaps = useCallback(async (requestId: number) => {
    setFinalMapLoading(true);
    setFinalMapError(null);
    try {
      const maps = await mappingApi.generated(requestId);
      setGeneratedMaps(maps);
      if (!maps.some((map) => map.file_exists !== false)) {
        setFinalMapError("最终 PNG 尚未找到，实时预览已停止显示。请重试或查看任务日志。");
      }
    } catch (error) {
      setGeneratedMaps([]);
      setFinalMapError(error instanceof Error ? error.message : "最终 PNG 加载失败");
    } finally {
      setFinalMapLoading(false);
    }
  }, []);

  useEffect(() => {
    if ((state.status === "completed" || state.status === "failed") && state.requestId) {
      void (async () => {
        await loadGeneratedMaps(state.requestId!);
        await loadHistory();
      })();
    }
  }, [loadGeneratedMaps, loadHistory, state.requestId, state.status]);

  useEffect(() => {
    const stage = mapStageRef.current;
    if (!stage) return;
    const preventPageScroll = (event: WheelEvent) => {
      event.preventDefault();
    };
    stage.addEventListener("wheel", preventPageScroll, { capture: true, passive: false });
    return () => stage.removeEventListener("wheel", preventPageScroll, true);
  }, []);

  const startMapRequest = async (requestText: string) => {
    const text = requestText.trim();
    if (!text || isWorking || submitInFlightRef.current) return;
    submitInFlightRef.current = true;
    dispatch({ type: "submission_started" });
    setGeneratedMaps([]);
    setFinalMapError(null);
    try {
      const created = await mappingApi.create(text);
      dispatch({ type: "request_created", requestId: created.request_id });
      dispatch({ type: "user_message", content: text });
      void stream.start(created.request_id);
      await mappingApi.process(created.request_id);
    } catch (error) {
      stream.stop();
      dispatch({ type: "task_error", message: error instanceof Error ? error.message : "创建任务失败" });
    } finally {
      submitInFlightRef.current = false;
      dispatch({ type: "submission_finished" });
      setPrompt("");
    }
  };

  const startRequest = (event: FormEvent) => {
    event.preventDefault();
    void startMapRequest(prompt);
  };

  const continueRequest = async (event: FormEvent) => {
    event.preventDefault();
    const text = prompt.trim();
    if (!text || !state.requestId || isWorking) return;
    dispatch({ type: "conversation_started" });
    dispatch({ type: "user_message", content: text });
    setPrompt("");
    try {
      const result = await conversation.send(text);
      // The completed request has an old terminal SSE event. Submit first so
      // the stream replays the new run instead of closing on that old event.
      void stream.start(state.requestId, result.stream_after_id);
    } catch (error) {
      stream.stop();
      dispatch({ type: "task_error", message: error instanceof Error ? error.message : "继续对话失败" });
    }
  };

  const resetWorkbench = () => {
    submitInFlightRef.current = false;
    stream.stop();
    setGeneratedMaps([]);
    setFinalMapLoading(false);
    setFinalMapError(null);
    setHistoryNotice(null);
    dispatch({ type: "reset" });
  };
  const connectionLabel = state.transportStatus === "connected" ? "实时进度已连接" : state.transportStatus === "reconnecting" ? "实时通道重连中" : isWorking ? "任务已提交" : state.status === "completed" ? "地图已完成" : state.status === "needs_clarification" ? "等待补充信息" : state.status === "failed" ? "任务需重试" : "准备制图";

  return (
    <main className="workbench">
      <header className="topbar">
        <div className="brand-block"><span className="eyebrow">MAP-LLM / CARTOGRAPHY WORKBENCH</span><h1>智能制图工作台</h1><p>用自然语言创建、检查并持续调整地图成果</p></div>
        <div className="topbar-actions"><span className={`connection ${state.transportStatus === "connected" ? "online" : state.transportStatus === "reconnecting" ? "failed" : isWorking ? "working" : state.status === "failed" ? "failed" : "ready"}`}><i aria-hidden="true" />{connectionLabel}</span><button className="secondary-button" type="button" onClick={resetWorkbench}>新建任务</button></div>
      </header>

      <section className="workspace-grid">
        <aside className="panel history-panel">
          <div className="panel-heading"><div><span className="section-kicker">ARCHIVE</span><h2>历史成果</h2></div><button className="text-button" type="button" onClick={() => void loadHistory()} disabled={historyLoading}>{historyLoading ? "读取中" : "刷新"}</button></div>
          <div className="history-intro">选择一条记录，恢复地图版本和对话。</div>
          {historyError && <div className="inline-notice error-notice" role="alert">{historyError}</div>}
          {historyNotice && <div className="inline-notice" role="status">{historyNotice}</div>}
          <div className="history-list">{history.length === 0 ? <p className="muted">暂无已生成地图</p> : history.map((item) => <button className="history-item" type="button" key={item.request_id} onClick={() => { setHistoryNotice(null); setFinalMapError(null); setGeneratedMaps(item.maps || []); void openHistory(item, dispatch, stream, setGeneratedMaps).catch((error) => setHistoryNotice(error instanceof Error ? error.message : "历史成果加载失败")); }}><span className="history-item-title">{item.title}</span><span className="history-item-meta"><span className={`history-dot status-dot-${item.status}`} />{statusLabel(item.status)}<b>#{item.request_id}</b></span></button>)}</div>
        </aside>

        <section className="center-column">
          <div className="panel map-panel">
            <div className="map-header"><div className="map-title"><span className="section-kicker">LIVE CANVAS</span><h2>{state.viewState?.map?.title || "地图预览"}</h2></div><div className="map-meta"><span className={`status status-${state.status}`}>{statusLabel(state.status)}</span>{state.layers.length > 0 && <span>{state.layers.length} 个图层</span>}{state.layers.length > 0 && <span className="layer-context" title={state.layers.map((layer) => layer.name || layer.id || "未命名图层").join("、")}>图层：{state.layers.map((layer) => layer.name || layer.id || "未命名").join("、")}</span>}</div></div>
            <div className="map-stage" ref={mapStageRef}>
              {state.status === "needs_clarification" ? <div className="map-shell clarification-shell" role="status" aria-live="polite"><span className="clarification-mark" aria-hidden="true">?</span><strong>需要补充制图信息</strong><p>{state.clarification?.question || latestAssistant?.content || "请补充地图范围和图层类型。"}</p><div className="clarification-suggestions">{(state.clarification?.suggestions || []).map((suggestion) => <button type="button" className="clarification-chip" key={suggestion} onClick={() => setPrompt(suggestion)}>{suggestion}</button>)}</div></div> : terminalWithResult ? finalMapLoading ? <div className="map-shell map-loading" role="status" aria-live="polite"><strong>正在加载最终 PNG</strong><span>正在核对成果文件，请稍候。</span></div> : showingFinalMap && finalMapUrl ? <StoredMapPreview src={finalMapUrl} version={availableMap?.version || 1} onError={() => setFinalMapError("最终 PNG 加载失败，文件无法显示，请重试或打开成果文件。")} /> : <div className="map-shell map-final-error" role="alert"><strong>最终 PNG 暂时不可用</strong><span>{finalMapError || "成果文件尚未同步。"}</span><button type="button" onClick={() => state.requestId && void loadGeneratedMaps(state.requestId)}>重新加载成果</button></div> : <><Suspense fallback={<div className="map-shell map-loading" role="status">正在加载实时地图画布</div>}><MapCanvas layers={mapData.layers} status={state.status} dataError={mapData.error} dataLoading={mapData.loading} /></Suspense>{state.layers.length === 0 && finalMapUrl && isWorking && <img className="map-live-preview" src={finalMapUrl} alt="地图实时预览" />}</>}
              <div className={`map-mode-badge map-mode-${state.status}`} aria-live="polite">{terminalWithResult ? state.status === "failed" ? `保留成果 v${availableMap?.version || 1}` : "最终 PNG" : state.status === "needs_clarification" ? "等待补充" : isWorking ? "实时预览" : "等待输入"}</div>
            </div>
            {terminalWithResult && <div className={`result-strip ${state.status === "failed" ? "result-strip-warning" : ""}`}><span className="result-check" aria-hidden="true">{state.status === "failed" ? "!" : "✓"}</span><div><strong>{state.status === "failed" ? `本轮调整失败，已保留 v${availableMap?.version || 1}` : "地图成果已生成"}</strong><span>{state.status === "failed" ? "当前 PNG 和之前的地图版本仍可查看；修正需求后可以继续调整。" : generatedMaps.length > 0 ? `${generatedMaps.length} 个文件版本已保存，可在右侧打开或下载。` : "地图已加载到画布，成果文件正在同步。"}</span></div>{availableMap && <a className="result-download" href={availableMap.file_path} download={availableMap.filename}>下载 PNG</a>}<button className="link-button" type="button" onClick={() => document.getElementById("result-card")?.scrollIntoView({ behavior: "smooth", block: "nearest" })}>查看成果</button></div>}
          </div>
          <div className="panel log-panel">
            <div className="panel-heading"><div><span className="section-kicker">ACTIVITY</span><h2>处理进度</h2></div><span className="log-count">{state.logs.length ? `${state.logs.length} 条记录` : "等待任务"}</span></div>
            <div className="progress-steps" aria-label="制图进度">{(state.status === "needs_clarification" ? ["任务提交", "等待补充", "生成图层", "完成交付"] : ["任务提交", "连接服务", "生成图层", "完成交付"]).map((label, index) => { const done = state.status === "completed" || index < progressStep; return <div className={`progress-step ${done ? "done" : index === progressStep ? "current" : ""}`} key={label}><span>{done ? "✓" : index + 1}</span>{label}</div>; })}</div>
            <div className="logs" aria-live="polite">{state.logs.length === 0 ? <p className="log-placeholder">{isWorking ? "已提交，正在等待第一条处理进度。" : "提交需求后，数据匹配、图层生成和渲染进度会出现在这里。"}</p> : state.logs.slice(-8).map((log, index) => <div className="log-line" key={index}><span>{String(log.step || log.level || "INFO")}</span><p>{String(log.message || log.content || "")}</p></div>)}</div>
          </div>
        </section>

        <aside className="panel inspector-panel">
          <div className="panel-heading"><div><span className="section-kicker">TASK INSPECTOR</span><h2>任务详情</h2></div><span className="request-id">{state.requestId ? `#${state.requestId}` : "未开始"}</span></div>
          <div className="inspector-scroll">
            <section className={`task-status status-card status-card-${state.status}`}><div className="status-card-top"><div><span className="card-label">当前状态</span><strong>{statusLabel(state.status)}</strong></div><span className="status-icon" aria-hidden="true">{state.status === "completed" ? "✓" : state.status === "failed" ? "!" : state.status === "needs_clarification" ? "?" : state.status === "idle" ? "·" : "↗"}</span></div><p>{statusDetail(state.status, state.transportStatus)}</p>{state.transportError && <div className="transport-notice" role="status">{state.transportError}，正在用任务状态同步恢复。</div>}</section>
            {latestRequest && <section className="inspector-section"><div className="section-title"><span>本次需求</span></div><div className="request-card">{latestRequest.content}</div></section>}
            {terminalWithResult && <section className="inspector-section" id="result-card"><div className="section-title"><span>{state.status === "failed" ? "已保留成果" : "生成成果"}</span><span className="section-count">{generatedMaps.length} 项</span></div><div className="result-card">{finalMapUrl && <img src={finalMapUrl} alt="地图成果缩略图" onError={() => setFinalMapError("最终 PNG 加载失败，文件无法显示。请重试或打开成果文件。")} />}{generatedMaps.length > 0 ? generatedMaps.map((map) => <div className="file-row" key={map.id}><div><strong>地图文件 v{map.version}</strong><span>{map.filename}</span></div>{map.file_exists === false ? <span className="file-unavailable">文件不可用</span> : <><a className="file-action" href={map.file_path} target="_blank" rel="noreferrer">打开</a><a className="file-action" href={map.file_path} download={map.filename}>下载 PNG</a></>}</div>) : <p className="result-note">最终成果文件未返回，请点击画布中的“重新加载成果”。</p>}</div></section>}
            {latestAssistant && <section className="inspector-section"><div className="section-title"><span>最新反馈</span></div><div className="assistant-card">{latestAssistant.content}</div></section>}
            {state.error && <section className="error-box" role="alert"><strong>生成失败</strong><p>{state.error}</p><button className="retry-button" type="button" onClick={() => setPrompt(latestRequest?.content || "")}>重新检查需求</button></section>}
          </div>
          <form onSubmit={canContinue ? continueRequest : startRequest} className="composer"><label htmlFor="map-prompt">{state.status === "needs_clarification" ? "补充制图信息" : canContinue ? "继续调整地图" : "输入制图需求"}</label><textarea id="map-prompt" value={prompt} onChange={(event) => setPrompt(event.target.value)} placeholder={state.status === "needs_clarification" ? "请补充地图范围、图层类型或数据源" : canContinue ? "例如：标注清华大学，并生成 v2" : "例如：给我绘制北京的地图"} rows={3} disabled={isWorking} aria-describedby="composer-status" /><div className="composer-footer"><span id="composer-status">{isWorking ? "任务进行中，页面会持续显示进度" : state.status === "needs_clarification" ? "选择上方建议或补充缺少的信息后继续" : canContinue ? "当前成果可继续调整" : "支持自然语言描述"}</span><button type="submit" disabled={isWorking || !prompt.trim()}>{isWorking ? "生成中" : state.status === "needs_clarification" ? "继续处理" : canContinue ? "发送调整" : "开始制图"}</button></div></form>
        </aside>
      </section>
    </main>
  );
}

function statusLabel(status: "idle" | "pending" | "processing" | "needs_clarification" | "completed" | "failed") {
  return { idle: "准备开始", pending: "任务已提交", processing: "生成中", needs_clarification: "等待补充信息", completed: "已完成", failed: "生成失败" }[status];
}

function statusDetail(status: "idle" | "pending" | "processing" | "needs_clarification" | "completed" | "failed", transportStatus: "idle" | "connecting" | "connected" | "reconnecting") {
  if (status === "idle") return "还没有正在处理的制图任务。";
  if (status === "pending") return transportStatus === "connected" ? "任务已进入实时队列。" : "任务已提交，正在建立进度连接。";
  if (status === "processing") return transportStatus === "reconnecting" ? "实时通道暂时断开，任务状态同步仍在继续。" : "服务正在处理数据并生成地图，进度会持续更新。";
  if (status === "completed") return "地图已经生成，可以查看成果或继续调整。";
  if (status === "needs_clarification") return "任务已暂停，补充信息后会继续当前请求，不会新建地图。";
  return "任务没有完成，请根据下面的错误信息检查后重试。";
}

function StoredMapPreview({ src, version, onError }: { src: string; version: number; onError?: () => void }) {
  const [zoom, setZoom] = useState(1);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const drag = useRef<{ x: number; y: number; offsetX: number; offsetY: number } | null>(null);

  const reset = () => {
    setZoom(1);
    setOffset({ x: 0, y: 0 });
  };

  return <div className="stored-map-preview">
    <div className="stored-map-viewport" onPointerDown={(event) => { drag.current = { x: event.clientX, y: event.clientY, offsetX: offset.x, offsetY: offset.y }; event.currentTarget.setPointerCapture(event.pointerId); }} onPointerMove={(event) => { if (!drag.current) return; setOffset({ x: drag.current.offsetX + event.clientX - drag.current.x, y: drag.current.offsetY + event.clientY - drag.current.y }); }} onPointerUp={() => { drag.current = null; }} onPointerCancel={() => { drag.current = null; }} onWheel={(event) => { setZoom((value) => Math.min(2.5, Math.max(.6, value + (event.deltaY < 0 ? .1 : -.1)))); }}>
      <img src={src} alt="已生成的地图成果" onError={onError} style={{ transform: `translate(${offset.x}px, ${offset.y}px) scale(${zoom})` }} draggable={false} />
    </div>
    <div className="stored-map-toolbar" aria-label="地图预览控制"><button type="button" onClick={() => setZoom((value) => Math.min(2.5, value + .1))} aria-label="放大地图">+</button><button type="button" onClick={() => setZoom((value) => Math.max(.6, value - .1))} aria-label="缩小地图">−</button><button type="button" onClick={reset} aria-label="适应地图尺寸">适应</button></div>
    <div className="stored-map-label">历史文件预览 · v{version} · 可拖动查看</div>
  </div>;
}

async function openHistory(item: MapRequestSummary, dispatch: Dispatch<WorkbenchAction>, stream: ReturnType<typeof useMapBuildStream>, setGeneratedMaps: (maps: GeneratedMap[]) => void) {
  dispatch({ type: "history_loaded", requestId: item.request_id, status: item.status, viewState: item.view_state, clarification: item.clarification });
  setGeneratedMaps(item.maps || []);
  const [messages, maps] = await Promise.all([mappingApi.messages(item.request_id), mappingApi.generated(item.request_id)]);
  messages.forEach((message) => dispatch({ type: "message_loaded", role: message.type === "user" ? "user" : message.type === "assistant" ? "assistant" : "system", content: message.content }));
  setGeneratedMaps(maps);
  if (item.status === "processing") await stream.start(item.request_id);
}
