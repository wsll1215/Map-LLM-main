import type { ClarificationData, LayerPayload, MapStreamEvent, TraceEvent, ViewStatePayload } from "../types/api";

export interface WorkbenchMessage {
  role: "user" | "assistant" | "system";
  content: string;
}

export interface WorkbenchState {
  requestId: number | null;
  submissionInFlight: boolean;
  status: "idle" | "pending" | "processing" | "needs_clarification" | "completed" | "partial" | "failed";
  messages: WorkbenchMessage[];
  logs: Array<Record<string, unknown>>;
  layers: LayerPayload[];
  viewState: ViewStatePayload | null;
  previewUrl: string | null;
  lastEventId: string;
  error: string | null;
  transportStatus: "idle" | "connecting" | "connected" | "reconnecting";
  transportError: string | null;
  clarification: ClarificationData | null;
  traceId: string | null;
  runId: number | null;
  traceEvents: TraceEvent[];
  traceTotalCount: number | null;
}

export const initialWorkbenchState: WorkbenchState = {
  requestId: null,
  submissionInFlight: false,
  status: "idle",
  messages: [],
  logs: [],
  layers: [],
  viewState: null,
  previewUrl: null,
  lastEventId: "",
  error: null,
  transportStatus: "idle",
  transportError: null,
  clarification: null,
  traceId: null,
  runId: null,
  traceEvents: [],
  traceTotalCount: null,
};

export type WorkbenchAction =
  | { type: "submission_started" }
  | { type: "submission_finished" }
  | { type: "request_created"; requestId: number }
  | { type: "history_loaded"; requestId: number; status: WorkbenchState["status"]; viewState?: ViewStatePayload | null; clarification?: ClarificationData | null; traceId?: string | null; runId?: number | null; error?: string | null }
  | { type: "conversation_started" }
  | { type: "user_message"; content: string }
  | { type: "message_loaded"; role: "user" | "assistant" | "system"; content: string }
  | { type: "logs_loaded"; logs: Array<Record<string, unknown>> }
  | { type: "trace_events_loaded"; events: TraceEvent[]; totalCount?: number }
  | { type: "stream_event"; event: MapStreamEvent }
  | { type: "stream_error"; message: string }
  | { type: "stream_status"; status: Exclude<WorkbenchState["transportStatus"], "idle"> }
  | { type: "task_status"; status: Exclude<WorkbenchState["status"], "idle">; error: string | null; message?: string; clarification?: ClarificationData | null; traceId?: string | null }
  | { type: "task_status_error"; message: string }
  | { type: "task_error"; message: string }
  | { type: "reset" };

function mergeLayer(layers: LayerPayload[], incoming: LayerPayload): LayerPayload[] {
  if (!incoming.name && !incoming.id) return layers;
  const key = incoming.id ?? incoming.name;
  const index = layers.findIndex((layer) => (layer.id ?? layer.name) === key);
  if (index === -1) return [...layers, incoming];
  return layers.map((layer, itemIndex) => (itemIndex === index ? { ...layer, ...incoming } : layer));
}

function appendTraceEvent(events: TraceEvent[], incoming: TraceEvent): TraceEvent[] {
  if (!incoming.event_id || events.some((event) => event.event_id === incoming.event_id)) return events;
  return [...events, incoming].sort((left, right) => left.event_seq - right.event_seq);
}

function traceEventFromData(data: Record<string, unknown>): TraceEvent | null {
  const candidate = data.trace_event;
  if (!candidate || typeof candidate !== "object") return null;
  const event = candidate as Partial<TraceEvent>;
  if (typeof event.event_id !== "string" || typeof event.event_seq !== "number" || typeof event.event_type !== "string") return null;
  return { ...event, summary: typeof event.summary === "string" ? event.summary : event.event_type, status: event.status || "success" } as TraceEvent;
}

export function workbenchReducer(state: WorkbenchState, action: WorkbenchAction): WorkbenchState {
  switch (action.type) {
    case "submission_started":
      return { ...state, submissionInFlight: true, error: null };
    case "submission_finished":
      return { ...state, submissionInFlight: false };
    case "request_created":
      return { ...initialWorkbenchState, requestId: action.requestId, submissionInFlight: true, status: "pending", transportStatus: "connecting", traceId: `web_session_${action.requestId}:create` };
    case "history_loaded":
      return {
        ...initialWorkbenchState,
        requestId: action.requestId,
        status: action.status,
        viewState: action.viewState ?? null,
        layers: action.viewState?.layers ?? [],
        clarification: action.clarification ?? null,
        traceId: action.traceId ?? null,
        runId: action.runId ?? null,
        error: action.error ?? null,
        transportStatus: action.status === "pending" || action.status === "processing" ? "connecting" : "idle",
      };
    case "conversation_started":
      return {
        ...state,
        status: "processing",
        error: null,
        clarification: null,
        logs: [],
        traceEvents: [],
        traceTotalCount: null,
        traceId: null,
        runId: null,
        lastEventId: "",
      };
    case "user_message":
      return { ...state, messages: [...state.messages, { role: "user", content: action.content }] };
    case "message_loaded":
      return { ...state, messages: [...state.messages, { role: action.role, content: action.content }] };
    case "logs_loaded":
      return { ...state, logs: action.logs };
    case "trace_events_loaded":
      return { ...state, traceEvents: action.events, traceTotalCount: action.totalCount ?? action.events.length };
    case "stream_error":
      return { ...state, transportStatus: "reconnecting", transportError: action.message };
    case "stream_status":
      return { ...state, transportStatus: action.status, transportError: null };
    case "task_status":
      return {
        ...state,
        status: action.status,
        error: action.status === "failed" ? action.error || "地图任务失败" : null,
        transportStatus: action.status === "pending" || action.status === "processing" ? "connected" : "idle",
        transportError: null,
        clarification: action.status === "needs_clarification" ? action.clarification ?? state.clarification : null,
        traceId: action.traceId ?? state.traceId,
        messages: action.message && !state.messages.some((message) => message.role === "assistant" && message.content === action.message)
          ? [...state.messages, { role: "assistant", content: action.message }]
          : state.messages,
      };
    case "task_status_error":
      return { ...state, transportStatus: "reconnecting", transportError: action.message };
    case "task_error":
      return { ...state, submissionInFlight: false, status: "failed", error: action.message };
    case "reset":
      return initialWorkbenchState;
    case "stream_event": {
      const { event } = action;
      if (event.id && event.id === state.lastEventId) return state;
      const data = event.data;
      const next: WorkbenchState = { ...state, lastEventId: event.id || state.lastEventId, transportStatus: "connected", transportError: null };
      if (data.transport_status === "degraded") {
        next.transportStatus = "reconnecting";
        next.transportError = typeof data.transport_error === "string"
          ? data.transport_error
          : "实时通道已降级，正在用任务状态同步恢复";
      }
      if (typeof data.trace_id === "string") next.traceId = data.trace_id;
      if (typeof data.run_id === "number") next.runId = data.run_id;
      if (event.event === "request_started") next.status = "processing";
      if (event.event === "assistant_message" && typeof data.content === "string") {
        next.messages = [...state.messages, { role: "assistant", content: data.content }];
      }
      if (event.event === "request_needs_clarification") {
        next.status = "needs_clarification";
        next.error = null;
        next.clarification = data.clarification as ClarificationData | undefined ?? null;
        if (typeof data.message === "string" && !next.messages.some((message) => message.role === "assistant" && message.content === data.message)) {
          next.messages = [...next.messages, { role: "assistant", content: data.message }];
        }
      }
      const traceEvent = traceEventFromData(data);
      if (traceEvent) {
        next.traceEvents = appendTraceEvent(state.traceEvents, traceEvent);
        next.traceTotalCount = Math.max(state.traceTotalCount ?? 0, next.traceEvents.length);
        if (traceEvent.trace_id) next.traceId = traceEvent.trace_id;
        if (typeof traceEvent.run_id === "number") next.runId = traceEvent.run_id;
      }
      if (event.event === "process_log") next.logs = [...state.logs, data];
      if (event.event === "layer_upserted" && data.layer && typeof data.layer === "object") {
        next.layers = mergeLayer(state.layers, data.layer as LayerPayload);
      }
      if (data.view_state && typeof data.view_state === "object") {
        const viewState = data.view_state as ViewStatePayload;
        next.viewState = viewState;
        if (viewState.layers) next.layers = viewState.layers;
      }
      if (data.preview && typeof data.preview === "object") {
        const preview = data.preview as { image_url?: unknown; created_at_ms?: unknown };
        if (typeof preview.image_url === "string") {
          const separator = preview.image_url.includes("?") ? "&" : "?";
          const timestamp = typeof preview.created_at_ms === "number" ? preview.created_at_ms : Date.now();
          next.previewUrl = `${preview.image_url}${separator}preview_ts=${timestamp}`;
        }
      }
      if (event.event === "request_completed") next.status = "completed";
      if (event.event === "request_partial") {
        next.status = "partial";
        next.error = typeof data.message === "string" ? data.message : null;
      }
      if (event.event === "request_failed") {
        next.status = "failed";
        next.error = typeof data.message === "string" ? data.message : "地图任务失败";
      }
      if (event.event === "done") {
        const terminalStatus = data.status;
        if (terminalStatus === "completed") next.status = "completed";
        if (terminalStatus === "partial") {
          next.status = "partial";
          next.error = typeof data.message === "string" ? data.message : null;
        }
        if (terminalStatus === "needs_clarification") {
          next.status = "needs_clarification";
          next.error = null;
          next.clarification = data.clarification as ClarificationData | undefined ?? null;
          if (typeof data.message === "string" && !next.messages.some((message) => message.role === "assistant" && message.content === data.message)) {
            next.messages = [...next.messages, { role: "assistant", content: data.message }];
          }
        }
        if (terminalStatus === "failed") {
          next.status = "failed";
          next.error = typeof data.message === "string" ? data.message : "地图任务失败";
        }
      }
      return next;
    }
  }
}
