import type { LayerPayload, MapStreamEvent, ViewStatePayload } from "../types/api";

export interface WorkbenchMessage {
  role: "user" | "assistant" | "system";
  content: string;
}

export interface WorkbenchState {
  requestId: number | null;
  status: "idle" | "pending" | "processing" | "completed" | "failed";
  messages: WorkbenchMessage[];
  logs: Array<Record<string, unknown>>;
  layers: LayerPayload[];
  viewState: ViewStatePayload | null;
  previewUrl: string | null;
  lastEventId: string;
  error: string | null;
}

export const initialWorkbenchState: WorkbenchState = {
  requestId: null,
  status: "idle",
  messages: [],
  logs: [],
  layers: [],
  viewState: null,
  previewUrl: null,
  lastEventId: "",
  error: null,
};

export type WorkbenchAction =
  | { type: "request_created"; requestId: number }
  | { type: "user_message"; content: string }
  | { type: "stream_event"; event: MapStreamEvent }
  | { type: "stream_error"; message: string }
  | { type: "reset" };

function mergeLayer(layers: LayerPayload[], incoming: LayerPayload): LayerPayload[] {
  if (!incoming.name && !incoming.id) return layers;
  const key = incoming.id ?? incoming.name;
  const index = layers.findIndex((layer) => (layer.id ?? layer.name) === key);
  if (index === -1) return [...layers, incoming];
  return layers.map((layer, itemIndex) => (itemIndex === index ? { ...layer, ...incoming } : layer));
}

export function workbenchReducer(state: WorkbenchState, action: WorkbenchAction): WorkbenchState {
  switch (action.type) {
    case "request_created":
      return { ...initialWorkbenchState, requestId: action.requestId, status: "pending" };
    case "user_message":
      return { ...state, messages: [...state.messages, { role: "user", content: action.content }] };
    case "stream_error":
      return { ...state, status: "failed", error: action.message };
    case "reset":
      return initialWorkbenchState;
    case "stream_event": {
      const { event } = action;
      if (event.id && event.id === state.lastEventId) return state;
      const data = event.data;
      const next: WorkbenchState = { ...state, lastEventId: event.id || state.lastEventId };
      if (event.event === "request_started") next.status = "processing";
      if (event.event === "assistant_message" && typeof data.content === "string") {
        next.messages = [...state.messages, { role: "assistant", content: data.content }];
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
        const preview = data.preview as { image_url?: unknown };
        if (typeof preview.image_url === "string") next.previewUrl = preview.image_url;
      }
      if (event.event === "request_completed") next.status = "completed";
      if (event.event === "request_failed") {
        next.status = "failed";
        next.error = typeof data.message === "string" ? data.message : "地图任务失败";
      }
      return next;
    }
  }
}
