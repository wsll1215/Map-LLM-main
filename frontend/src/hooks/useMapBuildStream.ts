import { useCallback, useEffect, useRef, useState, type MutableRefObject } from "react";
import { consumeSseChunk, parseJsonEvent, type SseEventFrame } from "../lib/sse";
import type { MapStreamEvent } from "../types/api";

type Dispatch = (action: { type: "stream_event"; event: MapStreamEvent } | { type: "stream_error"; message: string }) => void;

export function useMapBuildStream(dispatch: Dispatch) {
  const controllerRef = useRef<AbortController | null>(null);
  const lastIdRef = useRef("");
  const terminalRef = useRef(false);
  const [connected, setConnected] = useState(false);

  const stop = useCallback(() => { controllerRef.current?.abort(); controllerRef.current = null; setConnected(false); }, []);
  const start = useCallback(async (requestId: number) => {
    stop();
    terminalRef.current = false;
    const controller = new AbortController(); controllerRef.current = controller;
    let delay = 500;
    for (let attempt = 0; attempt < 4 && !controller.signal.aborted; attempt += 1) {
      try {
        const headers = new Headers({ Accept: "text/event-stream" });
        if (lastIdRef.current) headers.set("Last-Event-ID", lastIdRef.current);
        const response = await fetch(`/mapping/api/stream/${requestId}/`, { headers, credentials: "same-origin", signal: controller.signal });
        if (!response.ok || !response.body) throw new Error(`流式连接失败 (${response.status})`);
        setConnected(true); delay = 500;
        const reader = response.body.getReader(); const decoder = new TextDecoder(); let remainder = "";
        while (!controller.signal.aborted) {
          const { done, value } = await reader.read();
          if (done) break;
          const parsed = consumeSseChunk(remainder, decoder.decode(value, { stream: true })); remainder = parsed.remainder;
          for (const frame of parsed.events) handleFrame(frame, dispatch, lastIdRef, terminalRef);
          if (terminalRef.current) break;
        }
        if (remainder.trim()) { const parsed = consumeSseChunk(remainder, "\n\n"); for (const frame of parsed.events) handleFrame(frame, dispatch, lastIdRef, terminalRef); }
        if (!controller.signal.aborted && !terminalRef.current) throw new Error("流式连接已断开");
      } catch (error) {
        if (controller.signal.aborted) break;
        if (attempt === 3) dispatch({ type: "stream_error", message: error instanceof Error ? error.message : "流式连接失败" });
        else await new Promise((resolve) => setTimeout(resolve, delay));
        delay = Math.min(delay * 2, 8000);
      }
    }
    setConnected(false);
  }, [dispatch, stop]);
  useEffect(() => stop, [stop]);
  return { start, stop, connected };
}

function handleFrame(frame: SseEventFrame, dispatch: Dispatch, lastIdRef: MutableRefObject<string>, terminalRef: MutableRefObject<boolean>) {
  if (frame.id) lastIdRef.current = frame.id;
  if (!frame.data || frame.event === "message") return;
  try {
    const data = parseJsonEvent<Record<string, unknown>>(frame);
    dispatch({ type: "stream_event", event: { id: frame.id, event: frame.event, data } as MapStreamEvent });
    if (["done", "request_completed", "request_failed"].includes(frame.event)) terminalRef.current = true;
  } catch { dispatch({ type: "stream_error", message: "收到无法解析的 SSE 事件" }); }
}
