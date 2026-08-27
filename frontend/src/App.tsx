import {
  Alert,
  Badge,
  Button,
  ConfigProvider,
  Input,
  Layout,
  Space,
  Tag,
  Tooltip,
} from "antd";
import {
  ArrowDownOutlined,
  ArrowUpOutlined,
  CheckCircleFilled,
  ExclamationCircleFilled,
  LoadingOutlined,
  PlusOutlined,
  ReloadOutlined,
  SearchOutlined,
  WarningOutlined,
} from "@ant-design/icons";
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
import { ExecutionLogPanel } from "./components/ExecutionLogPanel";
import { ProgressStatus } from "./components/ProgressStatus";
import type { GeneratedMap, MapRequestSummary } from "./types/api";
import type { Bbox } from "./map/mapDataLoader";
import "./styles/app.css";

const MapCanvas = lazy(() => import("./components/MapCanvas").then((module) => ({ default: module.MapCanvas })));
export default function App() {
  const [state, dispatch] = useReducer(workbenchReducer, initialWorkbenchState);
  const [prompt, setPrompt] = useState("");
  const [generatedMaps, setGeneratedMaps] = useState<GeneratedMap[]>([]);
  const [finalMapLoading, setFinalMapLoading] = useState(false);
  const [finalMapError, setFinalMapError] = useState<string | null>(null);
  const [historyNotice, setHistoryNotice] = useState<string | null>(null);
  const [historyQuery, setHistoryQuery] = useState("");
  const [viewportBbox, setViewportBbox] = useState<Bbox | null>(null);
  const [mapCanvasError, setMapCanvasError] = useState<string | null>(null);
  const [mapRetryToken, setMapRetryToken] = useState(0);
  const mapStageRef = useRef<HTMLDivElement | null>(null);
  const historyListRef = useRef<HTMLDivElement | null>(null);
  const submitInFlightRef = useRef(false);
  const { history, loading: historyLoading, error: historyError, refresh: loadHistory } = useSessionHistory();
  const stream = useMapBuildStream(dispatch);
  const conversation = useConversation(state.requestId);
  const mapData = useMapData(state.requestId, state.layers, viewportBbox, mapRetryToken);
  const loadTraceEvent = useCallback((eventId: string) => state.requestId != null && state.runId != null ? mappingApi.traceEvent(state.requestId, state.runId, eventId) : Promise.resolve(null), [state.requestId, state.runId]);
  const isWorking = state.submissionInFlight || state.status === "pending" || state.status === "processing";
  const hasStoredMap = generatedMaps.some((map) => map.file_exists !== false);
  const canContinue = state.requestId !== null && (state.status === "needs_clarification" || state.status === "completed" || state.status === "partial" || (state.status === "failed" && hasStoredMap));
  const latestAssistant = isWorking ? null : [...state.messages].reverse().find((message) => message.role === "assistant");
  const latestRequest = [...state.messages].reverse().find((message) => message.role === "user");
  const latestLog = [...state.logs].reverse()[0];
  const latestProgress = typeof latestLog?.progress === "number" ? latestLog.progress : null;
  const availableMap = generatedMaps.find((map) => map.file_exists !== false) ?? null;
  const finalMapUrl = availableMap?.file_path || (state.status === "completed" ? null : state.previewUrl);
  const terminalWithResult = (state.status === "completed" || state.status === "partial" || state.status === "failed") && hasStoredMap;
  const normalizedHistoryQuery = historyQuery.trim().toLocaleLowerCase();
  const visibleHistory = normalizedHistoryQuery
    ? history.filter((item) => [item.title, item.request_text, item.result_message].filter(Boolean).some((value) => String(value).toLocaleLowerCase().includes(normalizedHistoryQuery)))
    : history;
  useTaskStatus(state.requestId, isWorking, dispatch);

  useEffect(() => {
    if (!isWorking || !state.requestId) return;
    let cancelled = false;
    const pollPreview = async () => {
      try {
        const result = await mappingApi.latestPreview(state.requestId!);
        const preview = result.preview;
        if (!cancelled && preview?.image_url) {
          dispatch({
            type: "stream_event",
            event: {
              id: `poll-preview-${preview.created_at_ms || Date.now()}`,
              event: "tool_finished",
              data: { preview },
            },
          });
        }
      } catch {
        // Task status polling remains the authoritative fallback for preview errors.
      }
    };
    void pollPreview();
    const timer = window.setInterval(() => void pollPreview(), 2000);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [isWorking, state.requestId]);

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
    if ((state.status === "completed" || state.status === "partial" || state.status === "failed") && state.requestId) {
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
    setViewportBbox(null);
    setMapCanvasError(null);
    setMapRetryToken(0);
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
  const connectionLabel = state.transportStatus === "connected" ? "实时进度已连接" : state.transportStatus === "reconnecting" ? "实时通道重连中" : isWorking ? "任务已提交" : state.status === "completed" ? "地图已完成" : state.status === "partial" ? "部分结果可用" : state.status === "needs_clarification" ? "等待补充信息" : state.status === "failed" ? "任务需重试" : "准备制图";

  return (
    <ConfigProvider theme={{ token: { colorPrimary: "#286b86", borderRadius: 6, fontFamily: '"Atkinson Hyperlegible", "Microsoft YaHei", system-ui, sans-serif' } }}>
      <Layout className="workbench-shell">
        <Layout.Header className="topbar">
          <div className="brand-block"><span className="eyebrow">MAP-LLM / CARTOGRAPHY WORKBENCH</span><h1>智能制图工作台</h1><p>自然语言制图 · 实时进度 · 版本调整</p></div>
          <Space className="topbar-actions" size={16}><Badge className={`connection connection-${state.transportStatus}`} status={state.transportStatus === "connected" ? "success" : state.transportStatus === "reconnecting" ? "error" : isWorking ? "processing" : "default"} text={connectionLabel} /><Button icon={<PlusOutlined />} onClick={resetWorkbench}>新建任务</Button></Space>
        </Layout.Header>

        <Layout.Content className="workbench-content"><section className="workspace-grid">
        <aside className="panel history-panel">
          <div className="panel-heading history-heading"><div><span className="section-kicker">ARCHIVE</span><div className="heading-row"><h2>历史成果</h2><span className="history-total">{history.length}</span></div></div><Space className="history-heading-actions" size={2}><Tooltip title="跳到最新"><Button type="text" shape="circle" icon={<ArrowUpOutlined />} onClick={() => historyListRef.current?.scrollTo({ top: 0, behavior: "smooth" })} disabled={!history.length} aria-label="跳到最新历史" /></Tooltip><Tooltip title="跳到最早"><Button type="text" shape="circle" icon={<ArrowDownOutlined />} onClick={() => { const list = historyListRef.current; list?.scrollTo({ top: list.scrollHeight, behavior: "smooth" }); }} disabled={!history.length} aria-label="跳到最早历史" /></Tooltip><Button type="link" size="small" icon={<ReloadOutlined />} onClick={() => void loadHistory()} loading={historyLoading}>刷新</Button></Space></div>
          <div className="history-intro">选择一条记录，恢复地图版本和对话。</div>
          <div className="history-search"><label htmlFor="history-search-input">搜索历史</label><Input id="history-search-input" prefix={<SearchOutlined />} value={historyQuery} onChange={(event) => setHistoryQuery(event.target.value)} placeholder="按需求或编号搜索" allowClear /></div>
          {historyError && <div className="inline-notice error-notice" role="alert">{historyError}</div>}
          {historyNotice && <div className="inline-notice" role="status">{historyNotice}</div>}
          <div className="history-list" ref={historyListRef} aria-label="历史成果列表">{historyLoading && history.length === 0 ? <p className="muted">正在读取历史成果…</p> : visibleHistory.length === 0 ? <p className="muted">{history.length === 0 ? "暂无已生成地图" : "没有匹配的历史记录"}</p> : visibleHistory.map((item) => <Button className={`history-item ${state.requestId === item.request_id ? "history-item-selected" : ""}`} type="text" block key={item.request_id} onClick={() => { setHistoryNotice(null); setFinalMapError(null); setGeneratedMaps(item.maps || []); void openHistory(item, dispatch, stream, setGeneratedMaps).catch((error) => setHistoryNotice(error instanceof Error ? error.message : "历史成果加载失败")); }}><span className="history-item-title">{item.title}</span><span className="history-item-meta"><span className={`history-dot status-dot-${item.status}`} />{statusLabel(item.status)}<b>#{item.request_id}</b></span></Button>)}</div>
          <div className="history-footer"><span>{normalizedHistoryQuery ? `${visibleHistory.length} / ${history.length} 条记录` : "按时间倒序"}</span><Button type="link" size="small" onClick={() => historyListRef.current?.scrollTo({ top: 0, behavior: "smooth" })} disabled={!history.length}>回到最新</Button></div>
        </aside>

        <section className="center-column">
          <div className="panel map-panel">
              <div className="map-header"><div className="map-title"><span className="section-kicker">LIVE CANVAS</span><h2>{state.viewState?.map?.title || "地图预览"}</h2></div><div className="map-meta"><Tag color={statusColor(state.status)}>{statusLabel(state.status)}</Tag>{state.layers.length > 0 && <span>{state.layers.length} 个图层</span>}{state.layers.length > 0 && <span className="layer-context" title={state.layers.map((layer) => layer.name || layer.id || "未命名图层").join("、")}>图层：{state.layers.map((layer) => `${layer.name || layer.id || "未命名"} · ${layer.data_source_meta?.source_type === "remote" ? "远程" : "本地"}`).join("、")}</span>}</div></div>
            <div className="map-stage" ref={mapStageRef}>
              {state.status === "needs_clarification" ? <div className="map-shell clarification-shell" role="status" aria-live="polite"><span className="clarification-mark" aria-hidden="true">?</span><strong>需要补充制图信息</strong><p>{state.clarification?.question || latestAssistant?.content || "请补充地图范围和图层类型。"}</p><div className="clarification-suggestions">{(state.clarification?.suggestions || []).map((suggestion) => <button type="button" className="clarification-chip" key={suggestion} onClick={() => setPrompt(suggestion)}>{suggestion}</button>)}</div></div> : <><Suspense fallback={<div className="map-shell map-loading" role="status">正在加载实时地图画布</div>}><MapCanvas key={mapRetryToken} requestId={state.requestId} layers={mapData.layers} status={state.status} mapCrs={state.viewState?.map?.crs} dataError={mapData.error || mapCanvasError} dataLoading={mapData.loading} onViewportChange={setViewportBbox} onError={setMapCanvasError} onRetry={() => { setMapCanvasError(null); setMapRetryToken((value) => value + 1); }} /></Suspense>{(isWorking || terminalWithResult) && finalMapUrl && <div className={`map-live-preview-wrap ${mapData.error || mapCanvasError ? "map-live-preview-fallback" : ""}`}><img className="map-live-preview" src={finalMapUrl} alt={terminalWithResult ? "最终 PNG 缩略图" : "地图实时预览"} /><span>{mapData.error || mapCanvasError ? "矢量图层加载失败，显示 PNG 兜底" : terminalWithResult ? "最终 PNG 缩略图" : "最新中间产物"}</span></div>}{terminalWithResult && finalMapLoading && <div className="map-data-loading" role="status">正在同步最终 PNG</div>}{terminalWithResult && finalMapError && <div className="map-data-error" role="alert"><span>{finalMapError}</span><button type="button" onClick={() => state.requestId && void loadGeneratedMaps(state.requestId)}>重新加载成果</button></div>}</>}
              <div className={`map-mode-badge map-mode-${state.status}`} aria-live="polite">{terminalWithResult ? state.status === "failed" ? `保留成果 v${availableMap?.version || 1}` : state.status === "partial" ? "部分成果" : "最终 PNG" : state.status === "needs_clarification" ? "等待补充" : isWorking ? "实时预览" : "等待输入"}</div>
            </div>
            <ProgressStatus status={state.status} message={isWorking && latestLog ? String(latestLog.message || latestLog.content || "") : undefined} latestProgress={latestProgress} />
            {terminalWithResult && <div className={`result-strip ${state.status !== "completed" ? "result-strip-warning" : ""}`}><span className="result-check" aria-hidden="true">{state.status === "completed" ? <CheckCircleFilled /> : <ExclamationCircleFilled />}</span><div><strong>{state.status === "failed" ? `本轮调整失败，已保留 v${availableMap?.version || 1}` : state.status === "partial" ? "地图部分完成" : "地图成果已生成"}</strong><span>{state.status === "failed" ? "当前 PNG 和之前的地图版本仍可查看；修正需求后可以继续调整。" : state.status === "partial" ? "当前结果可以查看；补齐缺失图层后才会标记为完成。" : generatedMaps.length > 0 ? `${generatedMaps.length} 个文件版本已保存，可在右侧打开或下载。` : "地图已加载到画布，成果文件正在同步。"}</span></div>{availableMap && <Button type="default" size="small" href={availableMap.file_path} download={availableMap.filename}>下载 PNG</Button>}<Button className="link-button" type="link" size="small" onClick={() => document.getElementById("result-card")?.scrollIntoView({ behavior: "smooth", block: "nearest" })}>查看成果</Button></div>}
          </div>
          <ExecutionLogPanel logs={state.logs} traceEvents={state.traceEvents} traceTotalCount={state.traceTotalCount} traceId={state.traceId} requestId={state.requestId} runId={state.runId} isWorking={isWorking} loadTraceEvent={loadTraceEvent} />
        </section>

        <aside className="panel inspector-panel">
          <div className="panel-heading"><div><span className="section-kicker">TASK INSPECTOR</span><h2>任务详情</h2></div><span className="request-id">{state.requestId ? `#${state.requestId}` : "未开始"}</span></div>
          <div className="inspector-scroll">
            <section className={`task-status status-card status-card-${state.status}`}><div className="status-card-top"><div><span className="card-label">当前状态</span><strong>{statusLabel(state.status)}</strong></div><span className="status-icon" aria-hidden="true">{state.status === "completed" ? <CheckCircleFilled /> : state.status === "failed" ? <ExclamationCircleFilled /> : state.status === "partial" ? <WarningOutlined /> : state.status === "needs_clarification" ? "?" : state.status === "idle" ? "·" : <LoadingOutlined spin />}</span></div><p>{state.status === "failed" && state.error ? "本轮任务未完成，请根据失败原因处理后重试。" : statusDetail(state.status, state.transportStatus)}</p>{state.traceId && <div className="trace-line"><span>Trace</span><code>{state.traceId}</code></div>}{state.status === "failed" && state.error && <div className="failure-detail" role="alert"><strong>失败原因</strong><p>{state.error}</p><span>修正需求后可继续当前地图，不会覆盖已有成果。</span><Button className="retry-button" size="small" onClick={() => setPrompt(latestRequest?.content || "")}>带入原需求</Button></div>}{state.transportError && <Alert className="transport-notice" type="warning" showIcon message={state.transportError} description="正在用任务状态同步恢复。" />}</section>
            {latestRequest && <section className="inspector-section"><div className="section-title"><span>本次需求</span></div><div className="request-card">{latestRequest.content}</div></section>}
            {state.layers.length > 0 && <section className="inspector-section"><div className="section-title"><span>数据来源</span><span className="section-count">{state.layers.length} 个图层</span></div><div className="source-list">{state.layers.map((layer, index) => { const id = layer.id || layer.name || `layer-${index}`; const source = layer.data_source_meta; const remote = source?.source_type === "remote"; return <div className="source-row" key={id}><div><strong>{layer.name || id}</strong><span>{source?.provider || (remote ? "远程数据源" : "本地数据")}</span></div><b className={remote ? "source-tag source-tag-remote" : "source-tag"}>{remote ? "远程" : "本地"}</b></div>; })}</div></section>}
            {terminalWithResult && <section className="inspector-section" id="result-card"><div className="section-title"><span>{state.status === "failed" ? "已保留成果" : state.status === "partial" ? "部分成果" : "生成成果"}</span><span className="section-count">{generatedMaps.length} 项</span></div><div className="result-card">{finalMapUrl && <img src={finalMapUrl} alt="地图成果缩略图" onError={() => setFinalMapError("最终 PNG 加载失败，文件无法显示。请重试或打开成果文件。")} />}{generatedMaps.length > 0 ? generatedMaps.map((map) => <div className="file-row" key={map.id}><div><strong>地图文件 v{map.version}</strong><span>{map.filename}</span></div>{map.file_exists === false ? <span className="file-unavailable">文件不可用</span> : <><a className="file-action" href={map.file_path} target="_blank" rel="noreferrer">打开</a><a className="file-action" href={map.file_path} download={map.filename}>下载 PNG</a></>}</div>) : <p className="result-note">最终成果文件未返回，请点击画布中的“重新加载成果”。</p>}</div></section>}
            {latestAssistant && <section className="inspector-section"><div className="section-title"><span>最新反馈</span></div><div className="assistant-card">{latestAssistant.content}</div></section>}
          </div>
          <form onSubmit={canContinue ? continueRequest : startRequest} className="composer"><label htmlFor="map-prompt">{state.status === "needs_clarification" ? "补充制图信息" : canContinue ? "继续调整地图" : "输入制图需求"}</label><Input.TextArea id="map-prompt" value={prompt} onChange={(event) => setPrompt(event.target.value)} placeholder={state.status === "needs_clarification" ? "请补充地图范围、图层类型或数据源" : canContinue ? "例如：标注清华大学，并生成 v2" : "例如：给我绘制北京的地图"} autoSize={{ minRows: 3, maxRows: 6 }} disabled={isWorking} aria-describedby="composer-status" /><div className="composer-footer"><span id="composer-status">{isWorking ? "任务进行中，页面会持续显示进度" : state.status === "needs_clarification" ? "选择上方建议或补充缺少的信息后继续" : canContinue ? "当前成果可继续调整" : "支持自然语言描述"}</span><Button type="primary" htmlType="submit" icon={isWorking ? <LoadingOutlined spin /> : undefined} disabled={isWorking || !prompt.trim()}>{isWorking ? "生成中" : state.status === "needs_clarification" ? "继续处理" : canContinue ? "发送调整" : "开始制图"}</Button></div></form>
        </aside>
        </section></Layout.Content>
      </Layout>
    </ConfigProvider>
  );
}

function statusLabel(status: "idle" | "pending" | "processing" | "needs_clarification" | "completed" | "partial" | "failed") {
  return { idle: "准备开始", pending: "任务已提交", processing: "生成中", needs_clarification: "等待补充信息", completed: "已完成", partial: "部分完成", failed: "生成失败" }[status];
}

function statusColor(status: "idle" | "pending" | "processing" | "needs_clarification" | "completed" | "partial" | "failed") {
  return { idle: "default", pending: "processing", processing: "processing", needs_clarification: "blue", completed: "success", partial: "warning", failed: "error" }[status] as "default" | "processing" | "blue" | "success" | "warning" | "error";
}

function statusDetail(status: "idle" | "pending" | "processing" | "needs_clarification" | "completed" | "partial" | "failed", transportStatus: "idle" | "connecting" | "connected" | "reconnecting") {
  if (status === "idle") return "还没有正在处理的制图任务。";
  if (status === "pending") return transportStatus === "connected" ? "任务已进入实时队列。" : "任务已提交，正在建立进度连接。";
  if (status === "processing") return transportStatus === "reconnecting" ? "实时通道暂时断开，任务状态同步仍在继续。" : "服务正在处理数据并生成地图，进度会持续更新。";
  if (status === "completed") return "地图已经生成，可以查看成果或继续调整。";
  if (status === "partial") return "部分图层已生成，可以查看结果或补充缺失图层。";
  if (status === "needs_clarification") return "任务已暂停，补充信息后会继续当前请求，不会新建地图。";
  return "任务没有完成，请根据下面的错误信息检查后重试。";
}

async function openHistory(item: MapRequestSummary, dispatch: Dispatch<WorkbenchAction>, stream: ReturnType<typeof useMapBuildStream>, setGeneratedMaps: (maps: GeneratedMap[]) => void) {
  dispatch({ type: "history_loaded", requestId: item.request_id, status: item.status, viewState: item.view_state, clarification: item.clarification, traceId: item.latest_run?.trace_id, runId: item.latest_run?.id, error: item.error_message || item.latest_run?.error_message || null });
  setGeneratedMaps(item.maps || []);
  const [messages, maps, logs, tracePage] = await Promise.all([
    mappingApi.messages(item.request_id),
    mappingApi.generated(item.request_id),
    mappingApi.logs(item.request_id, item.latest_run?.id),
    item.latest_run?.id ? mappingApi.traceEvents(item.request_id, item.latest_run.id) : Promise.resolve({ items: [], next_cursor: null, total_count: 0 }),
  ]);
  messages.forEach((message) => dispatch({ type: "message_loaded", role: message.type === "user" ? "user" : message.type === "assistant" ? "assistant" : "system", content: message.content }));
  dispatch({ type: "logs_loaded", logs });
  dispatch({ type: "trace_events_loaded", events: tracePage.items, totalCount: tracePage.total_count });
  setGeneratedMaps(maps);
  if (item.status === "processing") await stream.start(item.request_id);
}
