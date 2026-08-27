import { useCallback, useEffect, useRef, useState, type MutableRefObject } from "react";
import { consumeSseChunk, parseJsonEvent, type SseEventFrame } from "../lib/sse";
import type { MapStreamEvent } from "../types/api";

type Dispatch = (action: { type: "stream_event"; event: MapStreamEvent } | { type: "stream_error"; message: string } | { type: "stream_status"; status: "connecting" | "connected" | "reconnecting" }) => void;

export function isCurrentStreamGeneration(current: number, expected: number) {
  return current === expected;
}

export function isTerminalStreamEvent(eventName: string): boolean {
  return ["done", "request_completed", "request_partial", "request_failed", "request_needs_clarification"].includes(eventName);
}

export function useMapBuildStream(dispatch: Dispatch) {
  const controllerRef = useRef<AbortController | null>(null);
  const lastIdRef = useRef("");
  const requestIdRef = useRef<number | null>(null);
  const terminalRef = useRef(false);
  const generationRef = useRef(0);
  const [connected, setConnected] = useState(false);

  const stop = useCallback(() => {
    generationRef.current += 1;
    controllerRef.current?.abort();
    controllerRef.current = null;
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
    const controller = new AbortController(); controllerRef.current = controller;
    let delay = 500;
    for (let attempt = 0; attempt < 4 && !controller.signal.aborted; attempt += 1) {
      try {
        const headers = new Headers({ Accept: "text/event-stream" });
        if (lastIdRef.current) headers.set("Last-Event-ID", lastIdRef.current);
        const cursor = lastIdRef.current ? `?after=${encodeURIComponent(lastIdRef.current)}` : "";
        const response = await fetch(`/mapping/api/stream/${requestId}/${cursor}`, { headers, credentials: "same-origin", signal: controller.signal });
        if (!response.ok || !response.body) throw new Error(`流式连接失败 (${response.status})`);
        if (!isCurrentStreamGeneration(generationRef.current, generation)) break;
        setConnected(true); dispatch({ type: "stream_status", status: "connected" }); delay = 500;
        const reader = response.body.getReader(); const decoder = new TextDecoder(); let remainder = "";
        while (!controller.signal.aborted) {
          const { done, value } = await reader.read();
          if (done) break;
          const parsed = consumeSseChunk(remainder, decoder.decode(value, { stream: true })); remainder = parsed.remainder;
          for (const frame of parsed.events) handleFrame(frame, dispatch, lastIdRef, terminalRef, generationRef, generation);
          if (terminalRef.current) break;
        }
        if (remainder.trim()) { const parsed = consumeSseChunk(remainder, "\n\n"); for (const frame of parsed.events) handleFrame(frame, dispatch, lastIdRef, terminalRef, generationRef, generation); }
        if (!controller.signal.aborted && !terminalRef.current) throw new Error("流式连接已断开");
      } catch (error) {
        if (controller.signal.aborted) break;
        if (!isCurrentStreamGeneration(generationRef.current, generation)) break;
        dispatch({ type: "stream_status", status: "reconnecting" });
        if (attempt === 3) dispatch({ type: "stream_error", message: error instanceof Error ? error.message : "流式连接失败" });
        else await new Promise((resolve) => setTimeout(resolve, delay));
        delay = Math.min(delay * 2, 8000);
      }
    }
    if (isCurrentStreamGeneration(generationRef.current, generation)) setConnected(false);
  }, [dispatch, stop]);
  useEffect(() => stop, [stop]);
  return { start, stop, connected };
}

function handleFrame(
  frame: SseEventFrame,
  dispatch: Dispatch,
  lastIdRef: MutableRefObject<string>,
  terminalRef: MutableRefObject<boolean>,
  generationRef: MutableRefObject<number>,
  generation: number,
) {
  if (generationRef.current !== generation) return;
  if (frame.id) lastIdRef.current = frame.id;
  if (!frame.data || frame.event === "message") return;
  try {
    const data = parseJsonEvent<Record<string, unknown>>(frame);
    dispatch({ type: "stream_event", event: { id: frame.id, event: frame.event, data } as MapStreamEvent });
    if (isTerminalStreamEvent(frame.event)) terminalRef.current = true;
  } catch { dispatch({ type: "stream_error", message: "收到无法解析的 SSE 事件" }); }
}
