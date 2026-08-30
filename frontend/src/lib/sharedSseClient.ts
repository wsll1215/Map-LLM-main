import { consumeSseChunk, parseJsonEvent, type SseEventFrame } from "./sse";
import { isCursorAfter, subscriptionNeedsRefresh } from "./sseSubscription";
import { isRetryableSseStatus, shouldEnterSsePolling, sseResponseErrorCode, sseRetryDelayForStatus, sseRetryDelayMs } from "./sseRetry";

export type SharedSseMessage =
  | { type: "connected" }
  | { type: "event"; requestId: number; cursor: string; frame: { id: string; event: string; data: string }; data: Record<string, unknown> }
  | { type: "error"; message: string; errorCode?: string; retryable?: boolean };

export interface SharedSseClient {
  setHandler(handler: (message: SharedSseMessage) => void): void;
  updateToken(token: string): void;
  start(requestId: number, cursor?: string): void;
  stop(requestId: number): void;
  close(): void;
}

type BroadcastMessage =
  | { type: "hello" | "presence" | "leave"; tabId: string }
  | { type: "start"; tabId: string; requestId: number; cursor?: string }
  | { type: "stop"; tabId: string; requestId: number }
  | { type: "close"; tabId: string }
  | { type: "token"; tabId: string; token: string }
  | { type: "connected" }
  | { type: "error"; message: string; errorCode?: string; retryable?: boolean }
  | { type: "event"; requestId: number; cursor: string; frame: SseEventFrame; data: Record<string, unknown> };

type RequestSubscription = { cursor: string; tabs: Set<string> };

const CHANNEL_NAME = "map-llm-sse-v1";
const TRANSPORT_TERMINAL_EVENTS = new Set(["done"]);

export function createSharedSseClient(handler: (message: SharedSseMessage) => void): SharedSseClient | null {
  if (typeof SharedWorker !== "undefined") {
    try {
      const worker = new SharedWorker(new URL("../workers/sseMultiplex.sharedworker.ts", import.meta.url), { type: "module" });
      worker.port.start();
      let currentHandler = handler;
      worker.port.onmessage = ({ data }: MessageEvent<SharedSseMessage>) => currentHandler(data);
      return {
        setHandler(nextHandler) { currentHandler = nextHandler; },
        updateToken(token) { worker.port.postMessage({ type: "token", token }); },
        start(requestId, cursor) { worker.port.postMessage({ type: "start", requestId, cursor }); },
        stop(requestId) { worker.port.postMessage({ type: "stop", requestId }); },
        close() { worker.port.postMessage({ type: "close" }); worker.port.close(); },
      };
    } catch {
      // Some embedded browsers expose SharedWorker but reject module workers.
    }
  }
  if (typeof BroadcastChannel !== "undefined") return new BroadcastChannelSseClient(handler);
  return null;
}

export function selectLeader(tabId: string, peers: Iterable<string>): string {
  return [tabId, ...peers].sort()[0] || tabId;
}

class BroadcastChannelSseClient implements SharedSseClient {
  private readonly tabId = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
  private readonly channel = new BroadcastChannel(CHANNEL_NAME);
  private readonly knownRequests = new Map<number, RequestSubscription>();
  private readonly localRequests = new Set<number>();
  private readonly peers = new Set<string>();
  private readonly peerSeenAt = new Map<string, number>();
  private currentHandler: (message: SharedSseMessage) => void;
  private controller: AbortController | null = null;
  private connecting = false;
  private retryAttempt = 0;
  private heartbeatTimer: number | undefined;
  private closed = false;
  private connectedRequestIds = new Set<number>();
  private restartRequested = false;
  private authToken = "";

  constructor(handler: (message: SharedSseMessage) => void) {
    this.currentHandler = handler;
    this.channel.onmessage = ({ data }: MessageEvent<BroadcastMessage>) => this.handleMessage(data);
    this.channel.postMessage({ type: "hello", tabId: this.tabId });
    this.heartbeatTimer = window.setInterval(() => {
      const previousLeader = this.leaderId;
      const now = Date.now();
      for (const peer of this.peers) {
        if (now - (this.peerSeenAt.get(peer) || 0) > 12000) {
          this.peers.delete(peer);
          this.peerSeenAt.delete(peer);
        }
      }
      this.channel.postMessage({ type: "presence", tabId: this.tabId });
      if (previousLeader !== this.leaderId) {
        this.controller?.abort();
        void this.ensureConnection();
      }
    }, 5000);
  }

  setHandler(handler: (message: SharedSseMessage) => void): void {
    this.currentHandler = handler;
  }

  updateToken(token: string): void {
    this.authToken = token;
    this.channel.postMessage({ type: "token", tabId: this.tabId, token });
    if (this.connecting) {
      this.restartRequested = true;
      this.controller?.abort();
    }
  }

  start(requestId: number, cursor = ""): void {
    this.localRequests.add(requestId);
    const subscription = this.knownRequests.get(requestId) || { cursor, tabs: new Set<string>() };
    if (cursor && isCursorAfter(cursor, subscription.cursor)) subscription.cursor = cursor;
    subscription.tabs.add(this.tabId);
    this.knownRequests.set(requestId, subscription);
    this.channel.postMessage({ type: "start", tabId: this.tabId, requestId, cursor: subscription.cursor });
    this.refreshSubscriptionIfNeeded();
    void this.ensureConnection();
  }

  stop(requestId: number): void {
    this.localRequests.delete(requestId);
    this.removeSubscription(requestId, this.tabId);
    this.channel.postMessage({ type: "stop", tabId: this.tabId, requestId });
    this.refreshSubscriptionIfNeeded();
  }

  close(): void {
    if (this.closed) return;
    this.closed = true;
    for (const requestId of this.localRequests) this.channel.postMessage({ type: "stop", tabId: this.tabId, requestId });
    this.channel.postMessage({ type: "close", tabId: this.tabId });
    this.channel.postMessage({ type: "leave", tabId: this.tabId });
    if (this.heartbeatTimer !== undefined) window.clearInterval(this.heartbeatTimer);
    this.controller?.abort();
    this.channel.close();
  }

  private get leaderId(): string {
    return selectLeader(this.tabId, this.peers);
  }

  private handleMessage(message: BroadcastMessage): void {
    if (message.type === "hello" || message.type === "presence") {
      if (message.tabId !== this.tabId) {
        const previousLeader = this.leaderId;
        this.peers.add(message.tabId);
        this.peerSeenAt.set(message.tabId, Date.now());
        this.channel.postMessage({ type: "presence", tabId: this.tabId });
        this.announceLocalRequests();
        if (previousLeader !== this.leaderId) this.controller?.abort();
        void this.ensureConnection();
      }
      return;
    }
    if (message.type === "leave") {
      const previousLeader = this.leaderId;
      this.peers.delete(message.tabId);
      this.peerSeenAt.delete(message.tabId);
      if (message.tabId === previousLeader) {
        this.controller?.abort();
        void this.ensureConnection();
      }
      return;
    }
    if (message.type === "start") {
      const subscription = this.knownRequests.get(message.requestId) || { cursor: message.cursor || "", tabs: new Set<string>() };
      if (message.cursor && isCursorAfter(message.cursor, subscription.cursor)) subscription.cursor = message.cursor;
      subscription.tabs.add(message.tabId);
      this.knownRequests.set(message.requestId, subscription);
      this.refreshSubscriptionIfNeeded();
      void this.ensureConnection();
      return;
    }
    if (message.type === "close") {
      this.peers.delete(message.tabId);
      this.peerSeenAt.delete(message.tabId);
      return;
    }
    if (message.type === "token") {
      this.authToken = message.token;
      if (this.leaderId === this.tabId && this.connecting) {
        this.restartRequested = true;
        this.controller?.abort();
      }
      return;
    }
    if (message.type === "stop") {
      this.removeSubscription(message.requestId, message.tabId);
      this.refreshSubscriptionIfNeeded();
      return;
    }
    if (message.type === "connected") {
      this.currentHandler({ type: "connected" });
      return;
    }
    if (message.type === "error") {
      this.currentHandler({ type: "error", message: message.message, errorCode: message.errorCode, retryable: message.retryable });
      return;
    }
    if (message.type === "event" && this.localRequests.has(message.requestId)) {
      const subscription = this.knownRequests.get(message.requestId);
      const isReauthControl = message.frame.event === "stream_reauth_required";
      if (subscription && subscription.cursor && !isCursorAfter(message.cursor, subscription.cursor) && !TRANSPORT_TERMINAL_EVENTS.has(message.frame.event) && !isReauthControl) return;
      if (subscription && !isReauthControl && isCursorAfter(message.cursor, subscription.cursor)) subscription.cursor = message.cursor;
      this.currentHandler({ type: "event", requestId: message.requestId, cursor: message.cursor, frame: message.frame, data: message.data });
    }
  }

  private removeSubscription(requestId: number, tabId: string): void {
    const subscription = this.knownRequests.get(requestId);
    if (!subscription) return;
    subscription.tabs.delete(tabId);
    if (!subscription.tabs.size) this.knownRequests.delete(requestId);
  }

  private announceLocalRequests(): void {
    for (const requestId of this.localRequests) {
      const subscription = this.knownRequests.get(requestId);
      this.channel.postMessage({ type: "start", tabId: this.tabId, requestId, cursor: subscription?.cursor || "" });
    }
  }

  private async ensureConnection(): Promise<void> {
    if (this.closed || this.connecting || this.leaderId !== this.tabId || !this.knownRequests.size) return;
    this.connecting = true;
    try {
      while (!this.closed && this.leaderId === this.tabId && this.knownRequests.size) {
        this.controller = new AbortController();
        const ids = [...this.knownRequests.keys()];
        const query = new URLSearchParams({
          request_ids: ids.join(","),
          cursors: JSON.stringify(Object.fromEntries(ids.map((id) => [String(id), this.knownRequests.get(id)?.cursor || ""]))),
        });
        try {
          const response = await fetch(`/mapping/api/stream/?${query.toString()}`, {
            credentials: "same-origin",
            headers: { Accept: "text/event-stream", ...(this.authToken ? { Authorization: `Bearer ${this.authToken}` } : {}) },
            signal: this.controller.signal,
          });
          if (!response.ok || !response.body) {
            const body = await response.clone().json().catch(() => ({})) as { error_code?: string; message?: string; error?: string; retryable?: boolean };
            const retryable = body.retryable ?? isRetryableSseStatus(response.status);
            const errorCode = sseResponseErrorCode(response.status, body.error_code);
            this.broadcast({ type: "error", message: body.message || body.error || (response.status === 429 ? "实时连接数已达上限，正在使用任务状态同步" : `实时连接失败 (${response.status})`), errorCode, retryable });
            if (response.status === 401 && errorCode) return;
            if (!retryable) return;
            this.retryAttempt += 1;
            await wait(shouldEnterSsePolling(errorCode) ? 15000 : sseRetryDelayForStatus(response.status, this.retryAttempt), this.controller.signal);
            continue;
          }
          this.retryAttempt = 0;
          this.connectedRequestIds = new Set(ids);
          this.broadcast({ type: "connected" });
          const reader = response.body.getReader();
          const decoder = new TextDecoder();
          let remainder = "";
          while (!this.closed && this.leaderId === this.tabId && this.knownRequests.size) {
            const { done, value } = await reader.read();
            if (done) break;
            const parsed = consumeSseChunk(remainder, decoder.decode(value, { stream: true }));
            remainder = parsed.remainder;
            parsed.events.forEach((frame) => this.handleFrame(frame));
          }
          if (remainder.trim()) consumeSseChunk(remainder, "\n\n").events.forEach((frame) => this.handleFrame(frame));
          if (this.closed || this.leaderId !== this.tabId || !this.knownRequests.size) return;
          throw new Error("stream_disconnected");
        } catch (error) {
          if (this.controller.signal.aborted || this.closed || this.leaderId !== this.tabId) return;
          this.retryAttempt += 1;
          this.broadcast({ type: "error", message: error instanceof Error ? error.message : "实时连接已断开", retryable: true });
          await wait(sseRetryDelayMs(this.retryAttempt), this.controller.signal);
        }
      }
    } finally {
      this.controller = null;
      this.connecting = false;
      if (this.restartRequested && !this.closed && this.knownRequests.size) {
        this.restartRequested = false;
        void this.ensureConnection();
      }
    }
  }

  private refreshSubscriptionIfNeeded(): void {
    if (!this.knownRequests.size) {
      this.controller?.abort();
      return;
    }
    if (!subscriptionNeedsRefresh(this.connectedRequestIds, this.knownRequests.keys())) return;
    if (this.connecting) {
      this.restartRequested = true;
      this.controller?.abort();
    }
  }

  private handleFrame(frame: SseEventFrame): void {
    if (!frame.data || frame.event === "message") return;
    try {
      const data = parseJsonEvent<Record<string, unknown>>(frame);
      const requestId = typeof data.request_id === "number" ? data.request_id : Number(frame.id.split(":", 1)[0]);
      if (!Number.isInteger(requestId) || !this.knownRequests.has(requestId)) return;
      const cursor = typeof data.stream_cursor === "string" ? data.stream_cursor : frame.id.split(":").pop() || frame.id;
      const subscription = this.knownRequests.get(requestId);
      if (frame.event === "stream_reauth_required") {
        this.broadcast({ type: "event", requestId, cursor: subscription?.cursor || cursor, frame, data });
        this.controller?.abort();
        return;
      }
      if (subscription) subscription.cursor = cursor;
      this.broadcast({ type: "event", requestId, cursor, frame, data });
      if (TRANSPORT_TERMINAL_EVENTS.has(frame.event)) this.knownRequests.delete(requestId);
    } catch {
      this.broadcast({ type: "error", message: "收到无法解析的 SSE 事件", retryable: false });
    }
  }

  private broadcast(message: BroadcastMessage): void {
    this.channel.postMessage(message);
    if (message.type === "connected") this.currentHandler({ type: "connected" });
    if (message.type === "error") this.currentHandler({ type: "error", message: message.message, errorCode: message.errorCode, retryable: message.retryable });
    if (message.type === "event" && this.localRequests.has(message.requestId)) this.currentHandler({ type: "event", requestId: message.requestId, cursor: message.cursor, frame: message.frame, data: message.data });
  }
}

function wait(delay: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    const timer = window.setTimeout(resolve, delay);
    signal.addEventListener("abort", () => { window.clearTimeout(timer); resolve(); }, { once: true });
  });
}
