import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  ApartmentOutlined, BranchesOutlined, BulbOutlined, CheckCircleFilled,
  CloudDownloadOutlined, CloseCircleFilled, CopyOutlined, DatabaseOutlined,
  DownOutlined, EyeOutlined, FilterOutlined, PictureOutlined,
  ReloadOutlined, RightOutlined, RobotOutlined, SafetyCertificateOutlined,
  ToolOutlined, WarningOutlined,
} from "@ant-design/icons";
import { Button, Checkbox, Descriptions, Drawer, Empty, Input, Select, Space, Spin, Tag, Tabs, Tooltip } from "antd";
import type { TraceEvent } from "../types/api";

type LogRecord = Record<string, unknown>;

interface ExecutionLogPanelProps {
  logs: LogRecord[];
  traceEvents?: TraceEvent[];
  traceTotalCount?: number | null;
  traceId: string | null;
  requestId?: number | null;
  runId?: number | null;
  isWorking: boolean;
  loadTraceEvent?: (eventId: string) => Promise<TraceEvent | null>;
}

const EVENT_META: Record<string, { label: string; color: string; icon: ReactNode }> = {
  run: { label: "任务执行", color: "blue", icon: <BranchesOutlined /> },
  intent_parse: { label: "识别用户意图", color: "geekblue", icon: <BulbOutlined /> },
  validation: { label: "校验工具参数", color: "cyan", icon: <SafetyCertificateOutlined /> },
  llm_generation: { label: "模型推理", color: "blue", icon: <RobotOutlined /> },
  tool_call: { label: "执行工具", color: "orange", icon: <ToolOutlined /> },
  source_plan: { label: "规划数据源", color: "cyan", icon: <DatabaseOutlined /> },
  data_fetch: { label: "获取地图数据", color: "cyan", icon: <CloudDownloadOutlined /> },
  layer_process: { label: "处理图层", color: "green", icon: <ApartmentOutlined /> },
  render: { label: "渲染地图", color: "green", icon: <PictureOutlined /> },
  preview_update: { label: "更新实时预览", color: "blue", icon: <EyeOutlined /> },
  warning: { label: "警告", color: "gold", icon: <WarningOutlined /> },
  retry: { label: "重试", color: "gold", icon: <ReloadOutlined /> },
  error: { label: "错误", color: "red", icon: <CloseCircleFilled /> },
  run_finished: { label: "任务结束", color: "green", icon: <CheckCircleFilled /> },
  process_log: { label: "执行日志", color: "default", icon: <BranchesOutlined /> },
};

function textValue(value: unknown, fallback = "") {
  return typeof value === "string" || typeof value === "number" ? String(value) : fallback;
}

function formatTime(value: unknown) {
  if (typeof value !== "string" || !value) return "--:--:--";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleTimeString("zh-CN", { hour12: false });
}

function eventMeta(type: string) {
  return EVENT_META[type] || { label: type || "未分类事件", color: "default", icon: <BranchesOutlined /> };
}

function statusTag(status: string) {
  const color = status === "error" ? "error" : status === "warning" ? "warning" : status === "running" ? "processing" : status === "success" ? "success" : "default";
  return <Tag color={color}>{status || "未提供"}</Tag>;
}

function jsonText(value: unknown) {
  if (value === undefined || value === null || value === "") return "未提供";
  try { return JSON.stringify(value, null, 2); } catch { return "无法展示该字段"; }
}

function eventStart(event: TraceEvent, index: number) {
  const value = event.started_at ? new Date(event.started_at).getTime() : Number.NaN;
  return Number.isFinite(value) ? value : index * 10;
}

function flattenEvents(events: TraceEvent[], expanded: Set<string>) {
  const children = new Map<string, TraceEvent[]>();
  const roots: TraceEvent[] = [];
  events.forEach((event) => {
    if (event.parent_event_id) {
      const current = children.get(event.parent_event_id) || [];
      current.push(event);
      children.set(event.parent_event_id, current);
    } else roots.push(event);
  });
  const rows: Array<{ event: TraceEvent; depth: number; hasChildren: boolean }> = [];
  const visit = (event: TraceEvent, depth: number, seen: Set<string>) => {
    if (seen.has(event.event_id)) return;
    const nextSeen = new Set(seen).add(event.event_id);
    const nested = children.get(event.event_id) || [];
    rows.push({ event, depth, hasChildren: nested.length > 0 });
    if (expanded.has(event.event_id)) nested.forEach((child) => visit(child, depth + 1, nextSeen));
  };
  roots.forEach((event) => visit(event, 0, new Set()));
  events.forEach((event) => { if (!rows.some((row) => row.event.event_id === event.event_id)) visit(event, 0, new Set()); });
  return rows;
}

function CopyValue({ value }: { value: unknown }) {
  const copy = async () => { if (navigator.clipboard) await navigator.clipboard.writeText(jsonText(value)); };
  return <Tooltip title="复制内容"><Button type="text" size="small" icon={<CopyOutlined />} onClick={() => void copy()} aria-label="复制内容" /></Tooltip>;
}

function JsonPanel({ value }: { value: unknown }) {
  return <div className="trace-json-panel"><div className="trace-json-actions"><CopyValue value={value} /></div><pre>{jsonText(value)}</pre></div>;
}

function EventDetails({ event }: { event: TraceEvent }) {
  const meta = eventMeta(event.event_type);
  return <div className="trace-event-details">
    <Descriptions size="small" bordered column={2}>
      <Descriptions.Item label="事件类型">{meta.label}</Descriptions.Item>
      <Descriptions.Item label="状态">{statusTag(event.status)}</Descriptions.Item>
      <Descriptions.Item label="阶段">{event.phase || "未提供"}</Descriptions.Item>
      <Descriptions.Item label="执行者">{event.actor || "未提供"}</Descriptions.Item>
      <Descriptions.Item label="开始时间">{formatTime(event.started_at)}</Descriptions.Item>
      <Descriptions.Item label="耗时">{event.duration_ms == null ? "未提供" : `${event.duration_ms} ms`}</Descriptions.Item>
      <Descriptions.Item label="摘要" span={2}>{event.summary || "未提供"}</Descriptions.Item>
    </Descriptions>
    <Tabs className="trace-detail-tabs" items={[
      { key: "input", label: "输入", children: <JsonPanel value={event.input} /> },
      { key: "output", label: "输出", children: <JsonPanel value={event.output} /> },
      { key: "error", label: "错误", children: event.error ? <JsonPanel value={event.error} /> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="未提供错误" /> },
      { key: "attributes", label: "属性", children: <JsonPanel value={event.attributes} /> },
      { key: "raw", label: "原始事件", children: <JsonPanel value={event} /> },
    ]} />
  </div>;
}

export function ExecutionLogPanel({ logs, traceEvents = [], traceTotalCount, traceId, requestId, runId, isWorking, loadTraceEvent }: ExecutionLogPanelProps) {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(traceEvents[0]?.event_id || null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set(traceEvents.filter((event) => !event.parent_event_id).map((event) => event.event_id)));
  const [eventType, setEventType] = useState<string>();
  const [status, setStatus] = useState<string>();
  const [phase, setPhase] = useState<string>();
  const [query, setQuery] = useState("");
  const [errorsOnly, setErrorsOnly] = useState(false);
  const [selectedDetails, setSelectedDetails] = useState<TraceEvent | null>(null);
  const [detailsLoading, setDetailsLoading] = useState(false);
  const [detailsError, setDetailsError] = useState<string | null>(null);
  const [detailsRetryToken, setDetailsRetryToken] = useState(0);
  const logsRef = useRef<HTMLDivElement | null>(null);
  const followLogsRef = useRef(true);
  const visibleEvents = useMemo(() => traceEvents.filter((event) => {
    if (eventType && event.event_type !== eventType) return false;
    if (status && event.status !== status) return false;
    if (phase && event.phase !== phase) return false;
    if (errorsOnly && event.status !== "error" && !event.error) return false;
    return !query.trim() || `${event.summary} ${event.event_type} ${event.phase || ""}`.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase());
  }), [errorsOnly, eventType, phase, query, status, traceEvents]);
  const rows = useMemo(() => flattenEvents(visibleEvents, expanded), [expanded, visibleEvents]);
  const selected = visibleEvents.find((event) => event.event_id === selectedId) || visibleEvents[0] || null;
  useEffect(() => {
    let cancelled = false;
    if (!drawerOpen || !selected || !loadTraceEvent || !selected.has_details || selected.input !== undefined) {
      setSelectedDetails(null);
      setDetailsError(null);
      return;
    }
    setDetailsLoading(true);
    setDetailsError(null);
    void loadTraceEvent(selected.event_id).then((event) => { if (!cancelled) setSelectedDetails(event); }).catch((error) => { if (!cancelled) { setSelectedDetails(null); setDetailsError(error instanceof Error ? error.message : "事件详情加载失败"); } }).finally(() => { if (!cancelled) setDetailsLoading(false); });
    return () => { cancelled = true; };
  }, [detailsRetryToken, drawerOpen, loadTraceEvent, selected]);
  const minStart = Math.min(...traceEvents.map(eventStart), 0);
  const maxEnd = Math.max(...traceEvents.map((event, index) => eventStart(event, index) + (event.duration_ms || 1)), minStart + 1);
  const totalDuration = Math.max(maxEnd - minStart, 1);
  const traceJson = JSON.stringify({ trace_id: traceId, request_id: requestId, run_id: runId, events: traceEvents }, null, 2);
  const totalTraceEvents = Math.max(traceTotalCount ?? traceEvents.length, traceEvents.length);
  const traceCountLabel = totalTraceEvents > traceEvents.length
    ? `Trace 已加载 ${traceEvents.length} / 共 ${totalTraceEvents} 个事件`
    : `Trace ${totalTraceEvents} 个事件`;
  const copyTrace = async () => { if (traceId && navigator.clipboard) await navigator.clipboard.writeText(traceId); };
  const exportTrace = () => { const url = URL.createObjectURL(new Blob([traceJson], { type: "application/json" })); const link = document.createElement("a"); link.href = url; link.download = `${traceId || "trace"}.json`; link.click(); URL.revokeObjectURL(url); };
  useEffect(() => {
    followLogsRef.current = true;
  }, [requestId, runId]);
  useEffect(() => {
    const container = logsRef.current;
    if (!container || !logs.length || !followLogsRef.current) return;
    container.scrollTo({ top: container.scrollHeight, behavior: "auto" });
  }, [isWorking, logs.length]);

  return <div className="panel log-panel">
    <div className="panel-heading log-heading"><div className="log-heading-main"><span className="section-kicker">ACTIVITY / TRACE</span><h2>执行日志</h2><span className={`log-live-state ${isWorking ? "log-live-state-active" : ""}`}><i />{isWorking ? "实时接收中" : traceId ? "已收敛" : "等待任务"}</span><div className="log-trace-summary"><span>Trace</span><code title={traceId || "等待 Trace ID"}>{traceId || "等待 Trace ID"}</code></div></div><div className="log-heading-actions"><span className="log-count">日志 {logs.length} 条</span><span className="log-count trace-count">{traceCountLabel}</span><Button size="small" type="primary" icon={<BranchesOutlined />} onClick={() => setDrawerOpen(true)} disabled={!runId && !traceEvents.length}>打开 Trace</Button><Tooltip title="复制 Trace"><Button size="small" icon={<CopyOutlined />} onClick={() => void copyTrace()} disabled={!traceId} aria-label="复制 Trace" /></Tooltip></div></div>
    <div className="logs" ref={logsRef} onScroll={(event) => { const container = event.currentTarget; followLogsRef.current = container.scrollHeight - container.scrollTop - container.clientHeight < 32; }} aria-live="polite" aria-label="完整执行日志">{logs.length === 0 ? <p className="log-placeholder">{isWorking ? "已提交，正在等待第一条处理进度。" : "提交需求后，数据匹配、图层生成和渲染进度会出现在这里。"}</p> : logs.map((log, index) => { const level = textValue(log.level, "info").toLowerCase(); const trace = textValue(log.trace_id, traceId || "") || "未返回"; return <article className={`log-line log-level-${level}`} key={textValue(log.id, `${textValue(log.created_at)}-${index}`)}><div className="log-line-heading"><span className="log-sequence">#{index + 1}</span><strong>{textValue(log.step, level.toUpperCase())}</strong><span className="log-time">{formatTime(log.created_at)}</span></div><p>{textValue(log.message || log.content, "无日志内容")}</p><div className="log-line-meta"><span>Trace <code title={trace}>{trace}</code></span>{textValue(log.tool_name) && <span>工具 <b>{textValue(log.tool_name)}</b></span>}{textValue(log.run_id) && <span>Run <b>{textValue(log.run_id)}</b></span>}{textValue(log.iteration) && <span>迭代 <b>{textValue(log.iteration)}</b></span>}</div></article>; })}</div>
    <Drawer rootClassName="trace-drawer" title={null} placement="bottom" open={drawerOpen} onClose={() => setDrawerOpen(false)} destroyOnClose={false}>
      <div className="trace-drawer-header"><div><span className="section-kicker">TRACE INSPECTOR</span><h2>调用链详情</h2><div className="trace-identifiers"><code>{traceId || "未返回 Trace ID"}</code>{requestId != null && <span>Request #{requestId}</span>}{runId != null && <span>Run #{runId}</span>}<span>{traceCountLabel}</span><span>日志 {logs.length} 条</span></div></div><Space><Button icon={<CopyOutlined />} onClick={() => void copyTrace()} disabled={!traceId}>复制 Trace</Button><Button icon={<CopyOutlined />} onClick={() => void navigator.clipboard?.writeText(traceJson)}>复制 JSON</Button><Button icon={<ReloadOutlined />} onClick={() => setExpanded(new Set(traceEvents.map((event) => event.event_id)))}>展开全部</Button><Button icon={<DownOutlined />} onClick={() => setExpanded(new Set())}>折叠全部</Button><Button icon={<CopyOutlined />} onClick={exportTrace}>导出 JSON</Button></Space></div>
      <div className="trace-filter-bar"><Select allowClear placeholder="事件类型" value={eventType} onChange={setEventType} options={[...new Set(traceEvents.map((event) => event.event_type))].map((value) => ({ value, label: eventMeta(value).label }))} /><Select allowClear placeholder="状态" value={status} onChange={setStatus} options={[...new Set(traceEvents.map((event) => event.status))].map((value) => ({ value, label: value }))} /><Select allowClear placeholder="阶段" value={phase} onChange={setPhase} options={[...new Set(traceEvents.map((event) => event.phase).filter(Boolean))].map((value) => ({ value, label: value }))} /><Input allowClear prefix={<FilterOutlined />} placeholder="搜索摘要、类型或阶段" value={query} onChange={(event) => setQuery(event.target.value)} /><Checkbox checked={errorsOnly} onChange={(event) => setErrorsOnly(event.target.checked)}>只看错误</Checkbox></div>
      <div className="trace-layout"><div className="trace-visual-pane"><div className="trace-tree" aria-label="Trace 事件树">{rows.length === 0 ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有匹配的事件" /> : rows.map(({ event, depth, hasChildren }) => { const meta = eventMeta(event.event_type); const isExpanded = expanded.has(event.event_id); return <button type="button" className={`trace-row ${selected?.event_id === event.event_id ? "trace-row-selected" : ""}`} key={event.event_id} style={{ paddingLeft: 12 + depth * 22 }} onClick={() => setSelectedId(event.event_id)}><span className="trace-row-toggle" onClick={(click) => { click.stopPropagation(); setExpanded((current) => { const next = new Set(current); if (next.has(event.event_id)) next.delete(event.event_id); else next.add(event.event_id); return next; }); }}>{hasChildren ? (isExpanded ? <DownOutlined /> : <RightOutlined />) : <span />}</span><span className="trace-row-icon">{meta.icon}</span><span className="trace-row-copy"><strong>#{event.event_seq} {meta.label}</strong><small>{event.summary || "未提供摘要"}</small></span>{statusTag(event.status)}<span className="trace-row-duration">{event.duration_ms == null ? "--" : `${event.duration_ms} ms`}</span></button>; })}</div><div className="trace-waterfall" aria-label="Trace 瀑布时间线">{rows.map(({ event, depth }, index) => { const start = eventStart(event, index); const left = `${((start - minStart) / totalDuration) * 100}%`; const width = `${Math.max(((event.duration_ms || 1) / totalDuration) * 100, 0.8)}%`; return <button type="button" key={event.event_id} className={`trace-waterfall-row ${selected?.event_id === event.event_id ? "trace-waterfall-selected" : ""}`} onClick={() => setSelectedId(event.event_id)}><span className="trace-waterfall-track" style={{ marginLeft: `${depth * 10}px` }}><i style={{ left, width }} /></span></button>; })}</div></div><div className="trace-detail-panel">{detailsLoading ? <div className="trace-loading"><Spin /> 正在加载事件详情</div> : detailsError ? <div className="trace-detail-error" role="alert"><strong>事件详情加载失败</strong><p>{detailsError}</p><Button size="small" icon={<ReloadOutlined />} onClick={() => setDetailsRetryToken((value) => value + 1)}>重新加载</Button></div> : selected ? <EventDetails event={selectedDetails?.event_id === selected.event_id ? selectedDetails : selected} /> : <Empty description="选择一个事件查看详情" />}</div></div>
    </Drawer>
  </div>;
}
