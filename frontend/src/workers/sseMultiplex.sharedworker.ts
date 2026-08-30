import { consumeSseChunk, parseJsonEvent, type SseEventFrame } from "../lib/sse";
import { isCursorAfter, subscriptionNeedsRefresh } from "../lib/sseSubscription";
import { isRetryableSseStatus, shouldEnterSsePolling, sseResponseErrorCode, sseRetryDelayMs } from "../lib/sseRetry";

type WorkerCommand =
  | { type: "start"; requestId: number; cursor?: string }
  | { type: "token"; token: string }
  | { type: "stop"; requestId: number }
  | { type: "close" };
type WorkerPort = MessagePort;
type WorkerMessage =
  | { type: "connected" }
  | { type: "event"; requestId: number; cursor: string; frame: SseEventFrame; data: Record<string, unknown> }
  | { type: "error"; message: string; errorCode?: string; retryable?: boolean };

const ports = new Set<WorkerPort>();
const TRANSPORT_TERMINAL_EVENTS = new Set(["done"]);
const subscribers = new Map<number, Set<WorkerPort>>();
const cursors = new Map<number, string>();
let controller: AbortController | null = null;
let connecting = false;
let connectedRequestIds = new Set<number>();
let restartRequested = false;
let authToken = "";

const sharedWorkerScope = self as unknown as {
  onconnect: (event: MessageEvent) => void;
};

sharedWorkerScope.onconnect = (event: MessageEvent) => {
  const port = event.ports[0];
  ports.add(port);
  port.onmessage = ({ data }: MessageEvent<WorkerCommand>) => {
    if (data.type === "start") {
      const requestPorts = subscribers.get(data.requestId) || new Set<WorkerPort>();
      requestPorts.add(port);
      subscribers.set(data.requestId, requestPorts);
      if (data.cursor && isCursorAfter(data.cursor, cursors.get(data.requestId) || "")) cursors.set(data.requestId, data.cursor);
      refreshSubscriptionIfNeeded();
      void ensureConnection();
      return;
    }
    if (data.type === "token") {
      authToken = data.token;
      if (connecting) {
        restartRequested = true;
        controller?.abort();
      }
      return;
    }
    if (data.type === "close") {
      removePort(port);
      return;
    }
    subscribers.get(data.requestId)?.delete(port);
    if (subscribers.get(data.requestId)?.size === 0) subscribers.delete(data.requestId);
    refreshSubscriptionIfNeeded();
  };
  port.onmessageerror = () => removePort(port);
  port.start();
};

function removePort(port: WorkerPort) {
  ports.delete(port);
  for (const [requestId, requestPorts] of subscribers) {
    requestPorts.delete(port);
    if (requestPorts.size === 0) subscribers.delete(requestId);
  }
  refreshSubscriptionIfNeeded();
}

function broadcast(message: WorkerMessage, requestId?: number) {
  const targets = requestId === undefined ? ports : subscribers.get(requestId) || [];
  for (const port of targets) {
    try { port.postMessage(message); } catch { removePort(port); }
  }
}

async function ensureConnection() {
  if (connecting || subscribers.size === 0) return;
  connecting = true;
  let attempt = 0;
  try {
    while (subscribers.size > 0) {
      controller = new AbortController();
      try {
        const ids = [...subscribers.keys()];
        const query = new URLSearchParams({
          request_ids: ids.join(","),
          cursors: JSON.stringify(Object.fromEntries(ids.map((id) => [String(id), cursors.get(id) || ""]))),
        });
        const response = await fetch(`/mapping/api/stream/?${query.toString()}`, {
          credentials: "same-origin",
          headers: { Accept: "text/event-stream", ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}) },
          signal: controller.signal,
        });
        if (!response.ok || !response.body) {
          const body = await response.clone().json().catch(() => ({})) as { error_code?: string; message?: string; error?: string; retryable?: boolean };
          const retryable = body.retryable ?? isRetryableSseStatus(response.status);
          const errorCode = sseResponseErrorCode(response.status, body.error_code);
          broadcast({ type: "error", message: body.message || body.error || `实时连接失败 (${response.status})`, errorCode, retryable });
          if (response.status === 401 && errorCode) return;
          if (!retryable) return;
          if (shouldEnterSsePolling(errorCode)) {
            await wait(15000, controller.signal);
            attempt += 1;
            continue;
          }
          throw new Error(`stream_${response.status}`);
        }
        broadcast({ type: "connected" });
        connectedRequestIds = new Set(ids);
        attempt = 0;
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let remainder = "";
        while (subscribers.size > 0) {
          const { done, value } = await reader.read();
          if (done) break;
          const parsed = consumeSseChunk(remainder, decoder.decode(value, { stream: true }));
          remainder = parsed.remainder;
          parsed.events.forEach(handleFrame);
        }
        if (remainder.trim()) consumeSseChunk(remainder, "\n\n").events.forEach(handleFrame);
        if (subscribers.size === 0) return;
        throw new Error("stream_disconnected");
      } catch (error) {
        if (controller.signal.aborted || subscribers.size === 0) return;
        attempt += 1;
        broadcast({ type: "error", message: error instanceof Error ? error.message : "实时连接已断开", retryable: true });
        await wait(sseRetryDelayMs(attempt), controller.signal);
      }
    }
  } finally {
    controller = null;
    connecting = false;
    if (restartRequested && subscribers.size > 0) {
      restartRequested = false;
      void ensureConnection();
    }
  }
}

function refreshSubscriptionIfNeeded() {
  if (subscribers.size === 0) {
    controller?.abort();
    return;
  }
  if (!subscriptionNeedsRefresh(connectedRequestIds, subscribers.keys())) return;
  if (connecting) {
    restartRequested = true;
    controller?.abort();
  }
}

function handleFrame(frame: SseEventFrame) {
  if (!frame.data || frame.event === "message") return;
  try {
    const data = parseJsonEvent<Record<string, unknown>>(frame);
    const requestId = typeof data.request_id === "number" ? data.request_id : Number(frame.id.split(":", 1)[0]);
    if (!Number.isInteger(requestId) || !subscribers.has(requestId)) return;
    const cursor = typeof data.stream_cursor === "string" ? data.stream_cursor : frame.id.split(":").pop() || frame.id;
    const currentCursor = cursors.get(requestId) || "";
    if (frame.event === "stream_reauth_required") {
      broadcast({ type: "event", requestId, cursor: currentCursor || cursor, frame, data }, requestId);
      controller?.abort();
      return;
    }
    if (!isCursorAfter(cursor, currentCursor) && !TRANSPORT_TERMINAL_EVENTS.has(frame.event)) return;
    cursors.set(requestId, cursor);
    broadcast({ type: "event", requestId, cursor, frame, data }, requestId);
    if (TRANSPORT_TERMINAL_EVENTS.has(frame.event)) {
      subscribers.delete(requestId);
      cursors.delete(requestId);
    }
  } catch { broadcast({ type: "error", message: "收到无法解析的 SSE 事件", retryable: false }); }
}

function wait(delay: number, signal: AbortSignal) {
  return new Promise<void>((resolve) => {
    const timer = setTimeout(resolve, delay);
    signal.addEventListener("abort", () => { clearTimeout(timer); resolve(); }, { once: true });
  });
}
