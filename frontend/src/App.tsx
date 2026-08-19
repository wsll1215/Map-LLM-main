import { useReducer, useState, type Dispatch, type FormEvent } from "react";
import { mappingApi } from "./api/mappingApi";
import { MapCanvas } from "./components/MapCanvas";
import { initialWorkbenchState, workbenchReducer, type WorkbenchAction } from "./state/workbenchReducer";
import { useMapBuildStream } from "./hooks/useMapBuildStream";
import { useSessionHistory } from "./hooks/useSessionHistory";
import { useConversation } from "./hooks/useConversation";
import type { MapRequestSummary } from "./types/api";
import "./styles/app.css";

export default function App() {
  const [state, dispatch] = useReducer(workbenchReducer, initialWorkbenchState);
  const [prompt, setPrompt] = useState("");
  const { history, refresh: loadHistory } = useSessionHistory();
  const stream = useMapBuildStream(dispatch);
  const conversation = useConversation(state.requestId);
  const startRequest = async (event: FormEvent) => {
    event.preventDefault(); const text = prompt.trim(); if (!text) return;
    try { const created = await mappingApi.create(text); dispatch({ type: "request_created", requestId: created.request_id }); dispatch({ type: "user_message", content: text }); void stream.start(created.request_id); await mappingApi.process(created.request_id); }
    catch (error) { dispatch({ type: "stream_error", message: error instanceof Error ? error.message : "创建任务失败" }); }
    setPrompt("");
  };
  const continueRequest = async (event: FormEvent) => {
    event.preventDefault(); const text = prompt.trim(); if (!text || !state.requestId) return;
    dispatch({ type: "user_message", content: text }); setPrompt("");
    try { void stream.start(state.requestId); await conversation.send(text); } catch (error) { dispatch({ type: "stream_error", message: error instanceof Error ? error.message : "继续对话失败" }); }
  };
  return <main className="workbench">
    <header className="topbar"><div><span className="eyebrow">MAP-LLM / CARTOGRAPHY WORKBENCH</span><h1>智能制图工作台</h1></div><span className={`connection ${stream.connected ? "online" : "idle"}`}>{stream.connected ? "实时连接" : "待连接"}</span></header>
    <section className="workspace-grid">
      <aside className="panel history-panel"><div className="panel-heading"><h2>历史任务</h2><button onClick={() => void loadHistory()}>刷新</button></div>{history.length === 0 ? <p className="muted">暂无已生成地图</p> : history.map((item) => <button className="history-item" key={item.request_id} onClick={() => void openHistory(item, dispatch, stream)}><strong>{item.title}</strong><small>{item.status} · #{item.request_id}</small></button>)}</aside>
      <section className="center-column"><div className="panel map-panel"><div className="panel-heading"><h2>{state.viewState?.map?.title || "地图预览"}</h2><span className="status">{state.status}</span></div><MapCanvas layers={state.layers}/>{state.previewUrl && <img className="png-fallback" src={state.previewUrl} alt="地图 PNG 降级预览"/>}</div><div className="panel log-panel"><div className="panel-heading"><h2>过程日志</h2><span>{state.logs.length} events</span></div><div className="logs">{state.logs.slice(-8).map((log, index) => <div className="log-line" key={index}><span>{String(log.step || log.level || "INFO")}</span>{String(log.message || log.content || "")}</div>)}</div></div></section>
      <aside className="panel chat-panel"><div className="panel-heading"><h2>对话</h2><button onClick={() => { stream.stop(); dispatch({ type: "reset" }); }}>清空</button></div><div className="messages">{state.messages.map((message, index) => <div className={`message ${message.role}`} key={index}><span>{message.role === "user" ? "你" : "Map-LLM"}</span><p>{message.content}</p></div>)}{state.error && <div className="error-box">{state.error}</div>}</div><form onSubmit={state.requestId ? continueRequest : startRequest} className="composer"><textarea value={prompt} onChange={(event) => setPrompt(event.target.value)} placeholder={state.requestId ? "描述下一步地图调整…" : "描述你要制作的地图…"} rows={4}/><button type="submit">{state.requestId ? "发送调整" : "开始制图"}</button></form></aside>
    </section>
  </main>;
}

async function openHistory(item: MapRequestSummary, dispatch: Dispatch<WorkbenchAction>, stream: ReturnType<typeof useMapBuildStream>) {
  dispatch({ type: "request_created", requestId: item.request_id });
  try { const messages = await mappingApi.messages(item.request_id); messages.forEach((message) => dispatch({ type: "user_message", content: message.content })); } catch { /* stale history remains selectable */ }
  if (item.status === "processing") await stream.start(item.request_id);
}
