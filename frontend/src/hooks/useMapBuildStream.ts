import { useCallback, useEffect, useRef, useState, type MutableRefObject } from "react";
import { consumeSseChunk, parseJsonEvent, type SseEventFrame } from "../lib/sse";
import { isCursorAfter } from "../lib/sseSubscription";
import { createSharedSseClient, type SharedSseClient } from "../lib/sharedSseClient";
import { isNonRetryableSseStatus, isRetryableSseStatus, shouldEnterSsePolling, sseRetryDelayMs } from "../lib/sseRetry";
import { ApiRequestError, ensureAccessToken, getAccessToken, refreshAccessToken, subscribeAuth } from "../api/client";
import type { MapStreamEvent } from "../types/api";

export { isNonRetryableSseStatus, sseRetryDelayMs, sseRetryDelayForStatus } from "../lib/sseRetry";

type Dispatch = (action: { type: "stream_event"; event: MapStreamEvent } | { type: "stream_error"; message: string; retryable?: boolean } | { type: "stream_status"; status: "connecting" | "connected" | "reconnecting" | "polling" }) => void;

export function isCurrentStreamGeneration(current: number, expected: number) {
  return current === expected;
}

export function isTerminalStreamEvent(eventName: string): boolean {
  return ["done", "request_completed", "request_partial", "request_failed", "request_needs_clarification"].includes(eventName);
}

/** Compatibility status events update task state; only `done` closes transport. */
export function isTransportTerminalStreamEvent(eventName: string): boolean {
  return eventName === "done";
}

export function shouldStopStreamForStatus(status: string): boolean {
  return ["completed", "partial", "failed", "needs_clarification"].includes(status);
}

export function shouldSuspendSseForError(errorCode?: string): boolean {
  return shouldEnterSsePolling(errorCode);
}

export function shouldRefreshSseForAuthError(errorCode?: string): boolean {
  return ["stream_reauth_required", "access_token_expired", "access_token_invalid", "access_token_missing"].includes(errorCode || "");
}

export function isTerminalSseAuthError(errorCode?: string): boolean {
  return [
    "refresh_token_expired",
    "refresh_token_revoked",
    "refresh_token_reuse_detected",
    "refresh_token_invalid",
    "refresh_token_missing",
  ].includes(errorCode || "");
}

/** SSE multiplex ids are rendered as `${requestId}:${eventId}` on the wire. */
export function normalizeStreamCursor(value: string): string {
  const separator = value.indexOf(":");
  return separator > -1 ? value.slice(separator + 1) : value;
}

export function useMapBuildStream(dispatch: Dispatch) {
  const controllerRef = useRef<AbortController | null>(null);
  const lastIdRef = useRef("");
  const requestIdRef = useRef<number | null>(null);
  const terminalRef = useRef(false);
  const generationRef = useRef(0);
  const sharedClientRef = useRef<SharedSseClient | null>(null);
  const sharedRequestRef = useRef<number | null>(null);
  const pollingRecoveryTimerRef = useRef<number | undefined>(undefined);
  const authRecoveryRef = useRef(false);
  const [connected, setConnected] = useState(false);

  const stop = useCallback(() => {
    generationRef.current += 1;
    if (pollingRecoveryTimerRef.current !== undefined) {
      window.clearTimeout(pollingRecoveryTimerRef.current);
      pollingRecoveryTimerRef.current = undefined;
    }
    controllerRef.current?.abort();
    controllerRef.current = null;
    if (sharedRequestRef.current !== null) {
      sharedClientRef.current?.stop(sharedRequestRef.current);
      sharedRequestRef.current = null;
    }
    setConnected(false);
  }, []);
  const start = useCallback(async (requestId: number, afterEventId?: string) => {
    stop();
    const generation = generationRef.current;
    dispatch({ type: "stream_status", status: "connecting" });
    if (requestIdRef.current !== requestId) {
      lastIdRef.current = "";
      requestIdRef.current = requestId;
    }
    if (afterEventId) lastIdRef.current = afterEventId;
    terminalRef.current = false;
    let token: string;
    try {
      token = await ensureAccessToken();
    } catch (error) {
      dispatch({ type: "stream_error", message: error instanceof Error ? error.message : "登录状态恢复失败", retryable: false });
      return;
    }

    const sharedClient = sharedClientRef.current || createSharedSseClient(() => undefined);
    if (sharedClient) {
      sharedClientRef.current = sharedClient;
      sharedClient.updateToken(token);
      const scheduleSharedRecovery = () => {
        if (pollingRecoveryTimerRef.current !== undefined) return;
        pollingRecoveryTimerRef.current = window.setTimeout(() => {
          pollingRecoveryTimerRef.current = undefined;
          if (generationRef.current === generation && !terminalRef.current) {
            sharedClient.start(requestId, lastIdRef.current || undefined);
          }
        }, 15000);
      };
      const recoverSharedAuth = () => {
        if (authRecoveryRef.current) return;
        authRecoveryRef.current = true;
        setConnected(false);
        dispatch({ type: "stream_status", status: "reconnecting" });
        void refreshAccessToken().then((nextToken) => {
          if (generationRef.current === generation && !terminalRef.current) {
            sharedClient.updateToken(nextToken);
            sharedClient.start(requestId, lastIdRef.current || undefined);
          }
        }).catch((error) => {
          if (generationRef.current !== generation) return;
          sharedClient.stop(requestId);
          sharedRequestRef.current = null;
          if (isTerminalSseAuthError(error instanceof ApiRequestError ? error.errorCode : undefined)) {
            dispatch({ type: "stream_error", message: error instanceof Error ? error.message : "登录状态已失效", retryable: false });
            return;
          }
          dispatch({ type: "stream_status", status: "polling" });
          dispatch({ type: "stream_error", message: error instanceof Error ? error.message : "登录状态恢复中", retryable: true });
          scheduleSharedRecovery();
        }).finally(() => { authRecoveryRef.current = false; });
      };
      sharedClient.setHandler((message) => {
        if (generationRef.current !== generation) return;
        if (message.type === "connected") {
          setConnected(true);
          dispatch({ type: "stream_status", status: "connected" });
          return;
        }
        if (message.type === "error") {
          if (shouldRefreshSseForAuthError(message.errorCode)) {
            recoverSharedAuth();
            return;
          }
          if (isTerminalSseAuthError(message.errorCode)) {
            sharedClient.stop(requestId);
            sharedRequestRef.current = null;
            setConnected(false);
            dispatch({ type: "stream_error", message: `${message.errorCode}: ${message.message}`, retryable: false });
            return;
          }
          if (shouldSuspendSseForError(message.errorCode)) {
            sharedClient.stop(requestId);
            sharedRequestRef.current = null;
            setConnected(false);
            dispatch({ type: "stream_status", status: "polling" });
            scheduleSharedRecovery();
          } else if (message.retryable !== false) {
            dispatch({ type: "stream_status", status: "reconnecting" });
          }
          dispatch({ type: "stream_error", message: message.errorCode ? `${message.errorCode}: ${message.message}` : message.message, retryable: message.retryable });
          return;
        }
        if (shouldRefreshSseForAuthError(message.frame.event)) {
          recoverSharedAuth();
          return;
        }
        handleFrame(
          { ...message.frame, data: JSON.stringify(message.data) },
          dispatch,
          lastIdRef,
          terminalRef,
          generationRef,
          generation,
          message.cursor,
        );
        if (terminalRef.current) {
          sharedClient.stop(requestId);
          sharedRequestRef.current = null;
          setConnected(false);
        }
      });
      sharedRequestRef.current = requestId;
      sharedClient.start(requestId, lastIdRef.current || undefined);
      return;
    }

    const controller = new AbortController(); controllerRef.current = controller;
    let attempt = 0;
    while (!controller.signal.aborted) {
      try {
        token = await ensureAccessToken();
        const headers = new Headers({ Accept: "text/event-stream", Authorization: `Bearer ${token}` });
        if (lastIdRef.current) headers.set("Last-Event-ID", lastIdRef.current);
        const cursor = lastIdRef.current ? `?after=${encodeURIComponent(lastIdRef.current)}` : "";
        const response = await fetch(`/mapping/api/stream/${requestId}/${cursor}`, { headers, credentials: "same-origin", signal: controller.signal });
        if (response.status === 429 || response.status === 503) {
          const body = await response.clone().json().catch(() => ({})) as { error_code?: string; message?: string; error?: string; retryable?: boolean; next_action?: string };
          if (shouldEnterSsePolling(body.error_code) || response.status === 429) {
            dispatch({ type: "stream_status", status: "polling" });
            dispatch({ type: "stream_error", message: body.message || body.error || "实时通道暂不可用，正在使用任务状态同步" });
            await new Promise((resolve) => setTimeout(resolve, 15000));
            continue;
          }
        }
        if (response.status === 429) {
          dispatch({ type: "stream_status", status: "polling" });
          dispatch({ type: "stream_error", message: "实时连接数已达上限，正在使用任务状态同步" });
          await new Promise((resolve) => setTimeout(resolve, 15000));
          continue;
        }
        if (response.status === 401) {
          const body = await response.clone().json().catch(() => ({})) as { error_code?: string; message?: string; retryable?: boolean };
          if (shouldRefreshSseForAuthError(body.error_code)) {
            token = await refreshAccessToken();
            attempt = 0;
            continue;
          }
          dispatch({ type: "stream_error", message: body.message || "登录状态已失效", retryable: false });
          break;
        }
        if (isNonRetryableSseStatus(response.status)) {
          dispatch({ type: "stream_error", message: `流式连接失败 (${response.status})` });
          break;
        }
        if (!response.ok || !response.body) {
          if (!isRetryableSseStatus(response.status)) {
            dispatch({ type: "stream_error", message: `流式连接失败 (${response.status})` });
            break;
          }
          throw new Error(`流式连接失败 (${response.status})`);
        }
        if (!isCurrentStreamGeneration(generationRef.current, generation)) break;
        setConnected(true); dispatch({ type: "stream_status", status: "connected" }); attempt = 0;
        const reader = response.body.getReader(); const decoder = new TextDecoder(); let remainder = "";
        while (!controller.signal.aborted) {
          const { done, value } = await reader.read();
          if (done) break;
          const parsed = consumeSseChunk(remainder, decoder.decode(value, { stream: true })); remainder = parsed.remainder;
          let reauthenticated = false;
          for (const frame of parsed.events) {
            if (shouldRefreshSseForAuthError(frame.event)) {
              token = await refreshAccessToken();
              attempt = 0;
              reauthenticated = true;
              break;
            }
            handleFrame(frame, dispatch, lastIdRef, terminalRef, generationRef, generation);
          }
          if (reauthenticated) continue;
          if (terminalRef.current) break;
        }
        if (remainder.trim()) {
          const parsed = consumeSseChunk(remainder, "\n\n");
          const reauthFrame = parsed.events.find((frame) => shouldRefreshSseForAuthError(frame.event));
          if (reauthFrame) {
            token = await refreshAccessToken();
            attempt = 0;
            continue;
          }
          for (const frame of parsed.events) handleFrame(frame, dispatch, lastIdRef, terminalRef, generationRef, generation);
        }
        if (!controller.signal.aborted && !terminalRef.current) throw new Error("流式连接已断开");
      } catch (error) {
        if (controller.signal.aborted) break;
        if (!isCurrentStreamGeneration(generationRef.current, generation)) break;
        if (error instanceof ApiRequestError && ["refresh_token_expired", "refresh_token_revoked", "refresh_token_reuse_detected", "refresh_token_invalid", "refresh_token_missing"].includes(error.errorCode || "")) {
          dispatch({ type: "stream_error", message: error.message, retryable: false });
          break;
        }
        attempt += 1;
        dispatch({ type: "stream_status", status: "reconnecting" });
        dispatch({ type: "stream_error", message: error instanceof Error ? error.message : "流式连接失败" });
        await new Promise((resolve) => setTimeout(resolve, sseRetryDelayMs(attempt)));
      }
    }
    if (isCurrentStreamGeneration(generationRef.current, generation)) setConnected(false);
  }, [dispatch, stop]);
  useEffect(() => () => { stop(); sharedClientRef.current?.close(); sharedClientRef.current = null; }, [stop]);
  useEffect(() => subscribeAuth((status) => {
    if (status !== "authenticated" || !requestIdRef.current || terminalRef.current) return;
    const currentRequestId = requestIdRef.current;
    const nextToken = getAccessToken();
    if (!nextToken) return;
    if (sharedRequestRef.current !== null) {
      sharedClientRef.current?.updateToken(nextToken);
      return;
    }
    if (controllerRef.current) {
      controllerRef.current.abort();
      void start(currentRequestId, lastIdRef.current);
    }
  }), [start]);
  return { start, stop, connected };
}

function handleFrame(
  frame: SseEventFrame,
  dispatch: Dispatch,
  lastIdRef: MutableRefObject<string>,
  terminalRef: MutableRefObject<boolean>,
  generationRef: MutableRefObject<number>,
  generation: number,
  cursorOverride?: string,
) {
  if (generationRef.current !== generation) return;
  const cursor = normalizeStreamCursor(cursorOverride || frame.id || "");
  if (cursor && lastIdRef.current && !isCursorAfter(cursor, lastIdRef.current)) return;
  if (cursor) lastIdRef.current = cursor;
  if (!frame.data || frame.event === "message") return;
  try {
    const data = parseJsonEvent<Record<string, unknown>>(frame);
    dispatch({ type: "stream_event", event: { id: frame.id, event: frame.event, data } as MapStreamEvent });
    if (isTransportTerminalStreamEvent(frame.event)) terminalRef.current = true;
  } catch { dispatch({ type: "stream_error", message: "收到无法解析的 SSE 事件", retryable: false }); }
}
