import {
  Alert,
  Badge,
  Button,
  ConfigProvider,
  Input,
  Layout,
  Space,
  Tag,
  Tabs,
  Tooltip,
} from "antd";
import {
  ArrowDownOutlined,
  ArrowUpOutlined,
  CheckCircleFilled,
  DatabaseOutlined,
  ExclamationCircleFilled,
  FullscreenOutlined,
  HistoryOutlined,
  LoadingOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  PictureOutlined,
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
import { getAuthStatus, subscribeAuth, type AuthStatus } from "./api/client";
import { initialWorkbenchState, workbenchReducer, type WorkbenchAction } from "./state/workbenchReducer";
import { shouldStopStreamForStatus, useMapBuildStream } from "./hooks/useMapBuildStream";
import { useSessionHistory } from "./hooks/useSessionHistory";
import { useConversation } from "./hooks/useConversation";
import { useMapData } from "./hooks/useMapData";
import { shouldPollTaskStatus, useTaskStatus } from "./hooks/useTaskStatus";
import { ExecutionLogPanel } from "./components/ExecutionLogPanel";
import { ConversationFeed, conversationActivity } from "./components/ConversationFeed";
import { ArtifactDrawer } from "./components/ArtifactDrawer";
import { LivePreviewPeek } from "./components/LivePreviewPeek";
import { ProgressStatus } from "./components/ProgressStatus";
import type { GeneratedMap, MapRequestSummary } from "./types/api";
import type { Bbox } from "./map/mapDataLoader";
import type { PerformanceSnapshot } from "./map/performanceMetrics";
import { choosePreviewPresentation } from "./map/previewPresentation";
import { loadPanelPreferences, savePanelPreferences, type PanelPreferences } from "./state/workbenchLayout";
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
  const [mapPerformance, setMapPerformance] = useState<PerformanceSnapshot | null>(null);
  const [panelPreferences, setPanelPreferences] = useState<PanelPreferences>(() => loadPanelPreferences());
  const [inspectorTab, setInspectorTab] = useState<"details" | "conversation">("details");
  const [artifactDrawerOpen, setArtifactDrawerOpen] = useState(false);
  const [authStatus, setAuthStatus] = useState<AuthStatus>(() => getAuthStatus());
  const mapStageRef = useRef<HTMLDivElement | null>(null);
  const historyListRef = useRef<HTMLDivElement | null>(null);
  const submitInFlightRef = useRef(false);
  const generatedLoadGenerationRef = useRef(0);
  const { history, loading: historyLoading, error: historyError, refresh: loadHistory } = useSessionHistory();
  const stream = useMapBuildStream(dispatch);
  const conversation = useConversation(state.requestId);
  const mapData = useMapData(state.requestId, state.layers, viewportBbox, mapRetryToken);
  const loadTraceEvent = useCallback((eventId: string) => state.requestId != null && state.runId != null ? mappingApi.traceEvent(state.requestId, state.runId, eventId) : Promise.resolve(null), [state.requestId, state.runId]);
  const loadTracePage = useCallback((params: string) => state.requestId != null && state.runId != null ? mappingApi.traceEvents(state.requestId, state.runId, params) : Promise.resolve({ items: [], next_cursor: null, total_count: 0 }), [state.requestId, state.runId]);
  const isWorking = state.submissionInFlight || state.status === "pending" || state.status === "processing";
  const hasStoredMap = generatedMaps.some((map) => map.file_exists !== false);
  const canContinue = state.requestId !== null && (state.status === "needs_clarification" || state.status === "completed" || state.status === "partial" || (state.status === "failed" && hasStoredMap));
  const latestAssistant = [...state.messages].reverse().find((message) => message.role === "assistant");
  const latestRequest = [...state.messages].reverse().find((message) => message.role === "user");
  const latestLog = [...state.logs].reverse()[0];
  const latestTraceEvent = state.traceEvents[state.traceEvents.length - 1] ?? null;
  const liveActivity = conversationActivity(latestTraceEvent);
  const latestProgress = typeof latestLog?.progress === "number" ? latestLog.progress : null;
  const availableMap = generatedMaps.find((map) => map.file_exists !== false) ?? null;
  const finalMapUrl = availableMap?.file_path || (state.status === "completed" ? null : state.previewUrl);
  const previewPresentation = choosePreviewPresentation({ status: state.status, currentPreviewUrl: state.previewUrl, finalMapUrl, hasStoredMap });
  const normalizedHistoryQuery = historyQuery.trim().toLocaleLowerCase();
  const visibleHistory = normalizedHistoryQuery
    ? history.filter((item) => [item.title, item.request_text, item.result_message].filter(Boolean).some((value) => String(value).toLocaleLowerCase().includes(normalizedHistoryQuery)))
    : history;
  useTaskStatus(state.requestId, shouldPollTaskStatus(isWorking, state.transportStatus), dispatch);

  useEffect(() => subscribeAuth((status) => {
    setAuthStatus(status);
    if (status === "reauth_required") {
      const next = `${window.location.pathname}${window.location.search}`;
      window.location.replace(`/accounts/login?next=${encodeURIComponent(next)}`);
    }
  }), []);

  useEffect(() => {
    savePanelPreferences(panelPreferences);
  }, [panelPreferences]);

  useEffect(() => {
    if (state.transportStatus === "idle" && shouldStopStreamForStatus(state.status)) stream.stop();
  }, [state.status, state.transportStatus, stream.stop]);

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

  useEffect(() => {
    if (!state.requestId || !state.runId || !state.transportError?.startsWith("stream_cursor_gap:")) return;
    let cancelled = false;
    void mappingApi.traceEvents(state.requestId, state.runId, "limit=100").then((page) => {
      if (!cancelled) dispatch({ type: "trace_events_loaded", events: page.items, totalCount: page.total_count, nextCursor: page.next_cursor });
    }).catch(() => undefined);
    return () => { cancelled = true; };
  }, [state.requestId, state.runId, state.transportError]);

  const loadGeneratedMaps = useCallback(async (requestId: number) => {
    const generation = ++generatedLoadGenerationRef.current;
    setFinalMapLoading(true);
    setFinalMapError(null);
    try {
      const maps = await mappingApi.generated(requestId);
      if (generation !== generatedLoadGenerationRef.current) return;
      setGeneratedMaps(maps);
      if (!maps.some((map) => map.file_exists !== false)) {
        setFinalMapError("最终 PNG 尚未找到，实时预览已停止显示。请重试或查看任务日志。");
      }
    } catch (error) {
      if (generation !== generatedLoadGenerationRef.current) return;
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
    generatedLoadGenerationRef.current += 1;
    setFinalMapError(null);
    setViewportBbox(null);
    setMapCanvasError(null);
    setMapRetryToken(0);
    setMapPerformance(null);
    setInspectorTab("conversation");
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
    setInspectorTab("conversation");
    setMapPerformance(null);
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
    generatedLoadGenerationRef.current += 1;
    setFinalMapLoading(false);
    setFinalMapError(null);
    setMapPerformance(null);
    setHistoryNotice(null);
    dispatch({ type: "reset" });
  };
  const togglePanel = (panel: keyof PanelPreferences) => {
    setPanelPreferences((current) => ({ ...current, [panel]: !current[panel] }));
  };
  const toggleMapFullscreen = async () => {
    const stage = mapStageRef.current;
    if (!stage) return;
    try {
      if (document.fullscreenElement === stage) await document.exitFullscreen();
      else await stage.requestFullscreen();
    } catch {
      setMapCanvasError("当前浏览器不支持地图全屏");
    }
  };
  const connectionLabel = state.transportStatus === "connected" ? "实时进度已连接" : state.transportStatus === "polling" ? "实时通道受限，状态同步中" : state.transportStatus === "reconnecting" ? "实时通道重连中" : isWorking ? "任务已提交" : state.status === "completed" ? "地图已完成" : state.status === "partial" ? "部分结果可用" : state.status === "needs_clarification" ? "等待补充信息" : state.status === "failed" ? "任务需重试" : "准备制图";

  return (
    <ConfigProvider theme={{ token: { colorPrimary: "#286b86", borderRadius: 6, fontFamily: '"Atkinson Hyperlegible", "Microsoft YaHei", system-ui, sans-serif' } }}>
      <Layout className="workbench-shell">
        <Layout.Header className="topbar">
          <div className="brand-block"><span className="eyebrow">MAP-LLM / CARTOGRAPHY WORKBENCH</span><h1>智能制图工作台</h1><p>自然语言制图 · 实时进度 · 版本调整</p></div>
          <Space className="topbar-actions" size={16}><Badge className={`connection connection-${state.transportStatus}`} status={state.transportStatus === "connected" ? "success" : state.transportStatus === "reconnecting" ? "error" : state.transportStatus === "polling" ? "warning" : isWorking ? "processing" : "default"} text={connectionLabel} />{authStatus === "refreshing" || authStatus === "connection_recovering" ? <Tag color="gold">正在恢复登录</Tag> : null}<Button icon={<PlusOutlined />} onClick={resetWorkbench}>新建任务</Button></Space>
        </Layout.Header>

        <Layout.Content className="workbench-content">
          <section className={`workspace-grid ${!panelPreferences.historyOpen ? "history-collapsed" : ""} ${!panelPreferences.inspectorOpen ? "inspector-collapsed" : ""}`}>
            <aside className={`panel history-panel ${!panelPreferences.historyOpen ? "panel-collapsed" : ""}`} aria-label="历史成果">
              {panelPreferences.historyOpen ? <>
                <div className="panel-heading history-heading"><div><span className="section-kicker">ARCHIVE</span><div className="heading-row"><h2>历史成果</h2><span className="history-total">{history.length}</span></div></div><Space className="history-heading-actions" size={2}><Button type="link" size="small" icon={<ReloadOutlined />} onClick={() => void loadHistory()} loading={historyLoading}>刷新</Button><Tooltip title="折叠历史"><Button type="text" shape="circle" icon={<MenuFoldOutlined />} onClick={() => togglePanel("historyOpen")} aria-label="折叠历史" /></Tooltip></Space></div>
                <div className="history-intro">选择一条记录，恢复地图版本和对话。</div>
                <div className="history-search"><label htmlFor="history-search-input">搜索历史</label><Input id="history-search-input" prefix={<SearchOutlined />} value={historyQuery} onChange={(event) => setHistoryQuery(event.target.value)} placeholder="按需求或编号搜索" allowClear /></div>
                {historyError && <div className="inline-notice error-notice" role="alert">{historyError}</div>}
                {historyNotice && <div className="inline-notice" role="status">{historyNotice}</div>}
                <div className="history-list" ref={historyListRef} aria-label="历史成果列表">{historyLoading && history.length === 0 ? <p className="muted">正在读取历史成果…</p> : visibleHistory.length === 0 ? <p className="muted">{history.length === 0 ? "暂无已生成地图" : "没有匹配的历史记录"}</p> : visibleHistory.map((item) => <Button className={`history-item ${state.requestId === item.request_id ? "history-item-selected" : ""}`} type="text" block key={item.request_id} onClick={() => { const generation = ++generatedLoadGenerationRef.current; setHistoryNotice(null); setFinalMapError(null); setGeneratedMaps(item.maps || []); void openHistory(item, dispatch, stream, setGeneratedMaps, () => generation === generatedLoadGenerationRef.current).catch((error) => { if (generation === generatedLoadGenerationRef.current) setHistoryNotice(error instanceof Error ? error.message : "历史成果加载失败"); }); }}><span className="history-item-title">{item.title}</span><span className="history-item-meta"><span className={`history-dot status-dot-${item.status}`} />{statusLabel(item.status)}<b>#{item.request_id}</b></span></Button>)}</div>
                <div className="history-footer"><span>{normalizedHistoryQuery ? `${visibleHistory.length} / ${history.length} 条记录` : "按时间倒序"}</span><Space size={2}><Tooltip title="跳到最早"><Button type="text" shape="circle" icon={<ArrowDownOutlined />} onClick={() => { const list = historyListRef.current; list?.scrollTo({ top: list.scrollHeight, behavior: "smooth" }); }} disabled={!history.length} aria-label="跳到最早历史" /></Tooltip><Tooltip title="跳到最新"><Button type="text" shape="circle" icon={<ArrowUpOutlined />} onClick={() => historyListRef.current?.scrollTo({ top: 0, behavior: "smooth" })} disabled={!history.length} aria-label="跳到最新历史" /></Tooltip></Space></div>
              </> : <div className="collapsed-rail"><Tooltip title="展开历史"><Button type="text" icon={<MenuUnfoldOutlined />} onClick={() => togglePanel("historyOpen")} aria-label="展开历史" /></Tooltip><HistoryOutlined aria-hidden="true" /><span>历史</span></div>}
            </aside>

            <section className="center-column">
              <div className="panel map-panel">
                <div className="map-header"><div className="map-title"><span className="section-kicker">LIVE CANVAS</span><h2>{state.viewState?.map?.title || "地图预览"}</h2></div><div className="map-meta"><Tag color={statusColor(state.status)}>{statusLabel(state.status)}</Tag>{state.layers.length > 0 && <span>{state.layers.length} 个图层</span>}</div></div>
                <div className="map-stage" ref={mapStageRef} data-map-performance={mapPerformance ? JSON.stringify(mapPerformance) : undefined}>
                  {state.status === "needs_clarification" ? <div className="map-shell clarification-shell" role="status" aria-live="polite"><span className="clarification-mark" aria-hidden="true">?</span><strong>需要补充制图信息</strong><p>{state.clarification?.question || latestAssistant?.content || "请补充地图范围和图层类型。"}</p><div className="clarification-suggestions">{(state.clarification?.suggestions || []).map((suggestion) => <button type="button" className="clarification-chip" key={suggestion} onClick={() => setPrompt(suggestion)}>{suggestion}</button>)}</div></div> : <Suspense fallback={<div className="map-shell map-loading" role="status">正在加载实时地图画布</div>}><MapCanvas key={mapRetryToken} requestId={state.requestId} layers={mapData.layers} status={state.status} mapCrs={state.viewState?.map?.crs} dataError={mapData.error || mapCanvasError} dataLoading={mapData.loading} onViewportChange={setViewportBbox} onError={setMapCanvasError} onRetry={() => { setMapCanvasError(null); setMapRetryToken((value) => value + 1); }} onPerformanceMetrics={setMapPerformance} /></Suspense>}
                  <div className="map-toolbox" aria-label="地图工具"><Tooltip title="打开成果预览"><Button type="primary" icon={<PictureOutlined />} onClick={() => setArtifactDrawerOpen(true)} aria-label="打开成果预览">成果</Button></Tooltip><Tooltip title="查看图层和数据源"><Button icon={<DatabaseOutlined />} onClick={() => { setInspectorTab("details"); setPanelPreferences((current) => ({ ...current, inspectorOpen: true })); }} aria-label="查看图层和数据源">图层</Button></Tooltip><Tooltip title="地图全屏"><Button icon={<FullscreenOutlined />} onClick={() => void toggleMapFullscreen()} aria-label="地图全屏" /></Tooltip></div>
                  {isWorking && <LivePreviewPeek imageUrl={state.previewUrl} title="中间产物" meta={state.previewMeta ? `v${state.previewMeta.version ?? "-"} · ${state.previewMeta.tool_name || "render_map"}` : "等待渲染事件"} isFinal={false} loading={!state.previewUrl} onOpen={() => setArtifactDrawerOpen(true)} />}
                </div>
                {finalMapError && <div className="map-inline-notice" role="alert"><span>{finalMapError}</span><Button type="link" size="small" onClick={() => state.requestId && void loadGeneratedMaps(state.requestId)}>重新加载成果</Button></div>}
              </div>
            </section>

            <aside className={`panel inspector-panel ${!panelPreferences.inspectorOpen ? "panel-collapsed" : ""}`} aria-label="任务 Inspector">
              {panelPreferences.inspectorOpen ? <>
                <div className="panel-heading inspector-heading"><div><span className="section-kicker">TASK INSPECTOR</span><h2>任务上下文</h2></div><Space size={6}><span className="request-id">{state.requestId ? `#${state.requestId}` : "未开始"}</span><Tooltip title="折叠任务面板"><Button type="text" shape="circle" icon={<MenuUnfoldOutlined />} onClick={() => togglePanel("inspectorOpen")} aria-label="折叠任务面板" /></Tooltip></Space></div>
                <Tabs className="inspector-tabs" activeKey={inspectorTab} onChange={(key) => setInspectorTab(key as "details" | "conversation")} items={[
                  { key: "details", label: "任务详情", children: <div className="inspector-scroll"><section className={`task-status status-card status-card-${state.status}`}><div className="status-card-top"><div><span className="card-label">当前状态</span><strong>{statusLabel(state.status)}</strong></div><span className="status-icon" aria-hidden="true">{state.status === "completed" ? <CheckCircleFilled /> : state.status === "failed" ? <ExclamationCircleFilled /> : state.status === "partial" ? <WarningOutlined /> : state.status === "needs_clarification" ? "?" : state.status === "idle" ? "·" : <LoadingOutlined spin />}</span></div><p>{state.status === "failed" && state.error ? "本轮任务未完成，请根据失败原因处理后重试。" : statusDetail(state.status, state.transportStatus)}</p>{state.traceId && <div className="trace-line"><span>Trace</span><code>{state.traceId}</code></div>}{state.status === "failed" && state.error && <div className="failure-detail" role="alert"><strong>失败原因</strong><p>{state.error}</p><span>修正需求后可继续当前地图，不会覆盖已有成果。</span><Button className="retry-button" size="small" onClick={() => setPrompt(latestRequest?.content || "")}>带入原需求</Button></div>}{state.transportError && <Alert className="transport-notice" type="warning" showIcon message={state.transportError} description="正在用任务状态同步恢复。" />}</section><ProgressStatus status={state.status} message={isWorking && latestLog ? String(latestLog.message || latestLog.content || "") : undefined} latestProgress={latestProgress} />{latestRequest && <section className="inspector-section"><div className="section-title"><span>本次需求</span></div><div className="request-card">{latestRequest.content}</div></section>}{state.layers.length > 0 && <section className="inspector-section"><div className="section-title"><span>数据来源</span><span className="section-count">{state.layers.length} 个图层</span></div><div className="source-list">{state.layers.map((layer, index) => { const id = layer.id || layer.name || `layer-${index}`; const source = layer.data_source_meta; const remote = source?.source_type === "remote"; return <div className="source-row" key={id}><div><strong>{layer.name || id}</strong><span>{source?.provider || (remote ? "远程数据源" : "本地数据")}</span></div><b className={remote ? "source-tag source-tag-remote" : "source-tag"}>{remote ? "远程" : "本地"}</b></div>; })}</div></section>}</div> },
                  { key: "conversation", label: "AI 对话", children: <div className="inspector-scroll inspector-conversation"><ConversationFeed messages={state.messages} activity={liveActivity} isWorking={isWorking} /></div> },
                ]} />
                <form onSubmit={canContinue ? continueRequest : startRequest} className="composer"><label htmlFor="map-prompt">{state.status === "needs_clarification" ? "补充制图信息" : canContinue ? "继续调整地图" : "输入制图需求"}</label><Input.TextArea id="map-prompt" value={prompt} onChange={(event) => setPrompt(event.target.value)} placeholder={state.status === "needs_clarification" ? "请补充地图范围、图层类型或数据源" : canContinue ? "例如：标注清华大学，并生成 v2" : "例如：给我绘制北京的地图"} autoSize={{ minRows: 3, maxRows: 6 }} disabled={isWorking} aria-describedby="composer-status" /><div className="composer-footer"><span id="composer-status">{isWorking ? "任务进行中，页面会持续显示进度" : state.status === "needs_clarification" ? "选择上方建议或补充缺少的信息后继续" : canContinue ? "当前成果可继续调整" : "支持自然语言描述"}</span><Button type="primary" htmlType="submit" icon={isWorking ? <LoadingOutlined spin /> : undefined} disabled={isWorking || !prompt.trim()}>{isWorking ? "生成中" : state.status === "needs_clarification" ? "继续处理" : canContinue ? "发送调整" : "开始制图"}</Button></div></form>
              </> : <div className="collapsed-rail"><Tooltip title="展开任务面板"><Button type="text" icon={<MenuFoldOutlined />} onClick={() => togglePanel("inspectorOpen")} aria-label="展开任务面板" /></Tooltip><span className="collapsed-rail-icon"><DatabaseOutlined /></span><span>任务</span></div>}
            </aside>
          </section>
          <ExecutionLogPanel logs={state.logs} traceEvents={state.traceEvents} traceTotalCount={state.traceTotalCount} traceNextCursor={state.traceNextCursor} traceId={state.traceId} requestId={state.requestId} runId={state.runId} isWorking={isWorking} loadTraceEvent={loadTraceEvent} loadTracePage={loadTracePage} onTracePageLoaded={(page) => dispatch({ type: "trace_events_loaded", events: [...state.traceEvents, ...page.items], totalCount: page.total_count, nextCursor: page.next_cursor })} collapsed={!panelPreferences.logsOpen} onToggle={() => togglePanel("logsOpen")} />
        </Layout.Content>
        <ArtifactDrawer open={artifactDrawerOpen} onClose={() => setArtifactDrawerOpen(false)} imageUrl={previewPresentation.imageUrl} title={previewPresentation.title} meta={previewPresentation.isFinal ? `v${availableMap?.version || 1} · PNG` : state.previewMeta ? `v${state.previewMeta.version ?? "-"} · ${state.previewMeta.tool_name || "render_map"}` : "等待渲染事件"} isFinal={previewPresentation.isFinal} loading={isWorking || finalMapLoading} maps={generatedMaps} error={finalMapError} onReload={() => state.requestId && void loadGeneratedMaps(state.requestId)} />
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

function statusDetail(status: "idle" | "pending" | "processing" | "needs_clarification" | "completed" | "partial" | "failed", transportStatus: "idle" | "connecting" | "connected" | "reconnecting" | "polling") {
  if (status === "idle") return "还没有正在处理的制图任务。";
  if (status === "pending") return transportStatus === "connected" ? "任务已进入实时队列。" : "任务已提交，正在建立进度连接。";
  if (status === "processing") return transportStatus === "polling" ? "实时连接数受限，正在通过任务状态同步，稍后自动恢复实时通道。" : transportStatus === "reconnecting" ? "实时通道暂时断开，任务状态同步仍在继续。" : "服务正在处理数据并生成地图，进度会持续更新。";
  if (status === "completed") return "地图已经生成，可以查看成果或继续调整。";
  if (status === "partial") return "部分图层已生成，可以查看结果或补充缺失图层。";
  if (status === "needs_clarification") return "任务已暂停，补充信息后会继续当前请求，不会新建地图。";
  return "任务没有完成，请根据下面的错误信息检查后重试。";
}

async function openHistory(item: MapRequestSummary, dispatch: Dispatch<WorkbenchAction>, stream: ReturnType<typeof useMapBuildStream>, setGeneratedMaps: (maps: GeneratedMap[]) => void, isCurrent: () => boolean = () => true) {
  dispatch({ type: "history_loaded", requestId: item.request_id, status: item.status, viewState: item.view_state, clarification: item.clarification, traceId: item.latest_run?.trace_id, runId: item.latest_run?.id, error: item.error_message || item.latest_run?.error_message || null });
  setGeneratedMaps(item.maps || []);
  const [messages, maps, logs, tracePage] = await Promise.all([
    mappingApi.messages(item.request_id),
    mappingApi.generated(item.request_id),
    mappingApi.logs(item.request_id, item.latest_run?.id),
    item.latest_run?.id ? mappingApi.traceEvents(item.request_id, item.latest_run.id) : Promise.resolve({ items: [], next_cursor: null, total_count: 0 }),
  ]);
  if (!isCurrent()) return;
  messages.forEach((message) => dispatch({ type: "message_loaded", role: message.type === "user" ? "user" : message.type === "assistant" ? "assistant" : "system", content: message.content }));
  dispatch({ type: "logs_loaded", logs });
  dispatch({ type: "trace_events_loaded", events: tracePage.items, totalCount: tracePage.total_count, nextCursor: tracePage.next_cursor });
  setGeneratedMaps(maps);
  if (item.status === "processing" && isCurrent()) await stream.start(item.request_id);
}
