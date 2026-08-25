import { useEffect, useRef } from "react";
import { mappingApi } from "../api/mappingApi";
import type { MapRequestSummary } from "../types/api";

const TERMINAL = new Set<MapRequestSummary["status"]>(["completed", "needs_clarification", "failed"]);

export function useTaskStatus(
  requestId: number | null,
  active: boolean,
  dispatch: (action: { type: "task_status"; status: MapRequestSummary["status"]; error: string | null; message?: string; clarification?: MapRequestSummary["clarification"] } | { type: "task_status_error"; message: string }) => void,
) {
  const dispatchRef = useRef(dispatch);
  dispatchRef.current = dispatch;

  useEffect(() => {
    if (!requestId || !active) return;
    let cancelled = false;
    let timer: number | undefined;

    const poll = async () => {
      try {
        const task = await mappingApi.status(requestId);
        if (cancelled) return;
        dispatchRef.current({
          type: "task_status",
          status: task.status,
          error: task.error_message || task.latest_run?.error_message || null,
          message: task.result_message || undefined,
          clarification: task.clarification,
        });
        if (!TERMINAL.has(task.status)) timer = window.setTimeout(() => void poll(), 2000);
      } catch (error) {
        if (cancelled) return;
        dispatchRef.current({ type: "task_status_error", message: error instanceof Error ? error.message : "任务状态同步失败" });
        timer = window.setTimeout(() => void poll(), 3000);
      }
    };

    timer = window.setTimeout(() => void poll(), 500);
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [active, requestId]);
}
