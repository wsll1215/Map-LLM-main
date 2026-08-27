import { describe, expect, it } from "vitest";
import { initialWorkbenchState, workbenchReducer } from "./workbenchReducer";

import { isTerminalStreamEvent } from "../hooks/useMapBuildStream";
import { isTerminalTaskStatus } from "../hooks/useTaskStatus";

describe("workbenchReducer", () => {
  it("treats partial as a terminal task and stream state", () => {
    expect(isTerminalTaskStatus("partial")).toBe(true);
    expect(isTerminalStreamEvent("request_partial")).toBe(true);
  });
  it("keeps the latest PNG preview after layer events and busts image cache", () => {
    const created = workbenchReducer(initialWorkbenchState, { type: "request_created", requestId: 8 });
    const withLayer = workbenchReducer(created, {
      type: "stream_event",
      event: {
        id: "1",
        event: "layer_upserted",
        data: { layer: { id: "roads", name: "道路" } },
      },
    });
    const next = workbenchReducer(withLayer, {
      type: "stream_event",
      event: {
        id: "2",
        event: "tool_finished",
        data: { preview: { image_url: "/generated_maps/preview.png", created_at_ms: 1234 } },
      },
    });

    expect(next.layers).toHaveLength(1);
    expect(next.previewUrl).toBe("/generated_maps/preview.png?preview_ts=1234");
  });

  it("shows Redis degradation without turning the map task into a failure", () => {
    const state = workbenchReducer(
      { ...initialWorkbenchState, requestId: 8, status: "processing" },
      {
        type: "stream_event",
        event: {
          id: "preview-1",
          event: "tool_finished",
          data: {
            transport_status: "degraded",
            transport_error: "Redis 不可用",
            preview: { image_url: "/preview.png", created_at_ms: 22 },
          },
        },
      },
    );

    expect(state.status).toBe("processing");
    expect(state.transportStatus).toBe("reconnecting");
    expect(state.transportError).toBe("Redis 不可用");
    expect(state.previewUrl).toBe("/preview.png?preview_ts=22");
  });
  it("keeps the create form locked until request submission finishes", () => {
    const started = workbenchReducer(initialWorkbenchState, {
      type: "submission_started",
    });
    const created = workbenchReducer(started, {
      type: "request_created",
      requestId: 12,
    });
    const finished = workbenchReducer(created, { type: "submission_finished" });

    expect(started.submissionInFlight).toBe(true);
    expect(created.submissionInFlight).toBe(true);
    expect(finished.submissionInFlight).toBe(false);
  });

  it("updates status and assistant content from terminal stream events", () => {
    const withMessage = workbenchReducer(initialWorkbenchState, {
      type: "stream_event",
      event: {
        id: "1",
        event: "assistant_message",
        data: { content: "地图已完成" },
      },
    });
    const completed = workbenchReducer(withMessage, {
      type: "stream_event",
      event: {
        id: "2",
        event: "request_completed",
        data: { status: "completed" },
      },
    });

    expect(completed.messages).toEqual([{ role: "assistant", content: "地图已完成" }]);
    expect(completed.status).toBe("completed");
    expect(completed.lastEventId).toBe("2");
  });

  it("ignores a duplicate event id", () => {
    const state = workbenchReducer(initialWorkbenchState, {
      type: "stream_event",
      event: { id: "4", event: "process_log", data: { message: "step" } },
    });
    const duplicate = workbenchReducer(state, {
      type: "stream_event",
      event: { id: "4", event: "process_log", data: { message: "duplicate" } },
    });

    expect(duplicate.logs).toEqual([{ message: "step" }]);
  });

  it("shows a failure when the SSE fallback closes with a failed status", () => {
    const failed = workbenchReducer(initialWorkbenchState, {
      type: "stream_event",
      event: {
        id: "done-7",
        event: "done",
        data: { status: "failed", message: "未配置OpenAI API密钥" },
      },
    });

    expect(failed.status).toBe("failed");
    expect(failed.error).toBe("未配置OpenAI API密钥");
  });

  it("restores clarification when the terminal fallback only contains done status", () => {
    const waiting = workbenchReducer(
      { ...initialWorkbenchState, requestId: 8, status: "processing" },
      {
        type: "stream_event",
        event: {
          id: "done-clarify-8",
          event: "done",
          data: {
            status: "needs_clarification",
            message: "请补充图层类型。",
            clarification: { missing_fields: ["layer_type"] },
          },
        },
      },
    );

    expect(waiting.status).toBe("needs_clarification");
    expect(waiting.error).toBeNull();
    expect(waiting.clarification?.missing_fields).toEqual(["layer_type"]);
    expect(waiting.messages).toEqual([
      { role: "assistant", content: "请补充图层类型。" },
    ]);
  });

  it("does not turn an SSE disconnect into a map failure", () => {
    const processing = workbenchReducer(
      { ...initialWorkbenchState, requestId: 8, status: "processing" },
      { type: "stream_error", message: "流式连接已断开" },
    );

    expect(processing.status).toBe("processing");
    expect(processing.error).toBeNull();
    expect(processing.transportStatus).toBe("reconnecting");
    expect(processing.transportError).toBe("流式连接已断开");
  });

  it("syncs the terminal task status returned by the REST fallback", () => {
    const completed = workbenchReducer(
      { ...initialWorkbenchState, requestId: 8, status: "processing" },
      { type: "task_status", status: "completed", error: null },
    );

    expect(completed.status).toBe("completed");
    expect(completed.transportStatus).toBe("idle");
  });

  it("shows the backend error when REST fallback reports failure", () => {
    const failed = workbenchReducer(
      { ...initialWorkbenchState, requestId: 8, status: "processing" },
      { type: "task_status", status: "failed", error: "数据源不可用" },
    );

    expect(failed.status).toBe("failed");
    expect(failed.error).toBe("数据源不可用");
  });

  it("keeps an underspecified request in clarification state with next steps", () => {
    const waiting = workbenchReducer(initialWorkbenchState, {
      type: "stream_event",
      event: {
        id: "clarify-1",
        event: "request_needs_clarification",
        data: {
          status: "needs_clarification",
          message: "你想绘制哪里的哪类地图？",
          clarification: {
            missing_fields: ["map_scope", "layer_type"],
            suggestions: ["北京行政区划图"],
          },
        },
      },
    });

    expect(waiting.status).toBe("needs_clarification");
    expect(waiting.error).toBeNull();
    expect(waiting.clarification?.missing_fields).toEqual(["map_scope", "layer_type"]);
    expect(waiting.messages.at(-1)).toEqual({ role: "assistant", content: "你想绘制哪里的哪类地图？" });
  });

  it("restores clarification state from the REST status fallback", () => {
    const waiting = workbenchReducer(
      { ...initialWorkbenchState, requestId: 8, status: "processing" },
      {
        type: "task_status",
        status: "needs_clarification",
        error: null,
        message: "请补充地图范围和图层类型。",
        clarification: { suggestions: ["北京道路图"] },
      },
    );

    expect(waiting.status).toBe("needs_clarification");
    expect(waiting.transportStatus).toBe("idle");
    expect(waiting.clarification?.suggestions).toEqual(["北京道路图"]);
  });

  it("keeps the current map context when a later adjustment fails", () => {
    const completed = workbenchReducer(initialWorkbenchState, {
      type: "history_loaded",
      requestId: 8,
      status: "completed",
      viewState: {
        map: { title: "海淀区地图", layer_count: 1 },
        layers: [{ id: "haidian", name: "海淀区边界", geometry_type: "Polygon" }],
        annotations: [{ text: "清华大学", position: [0.5, 0.1] }],
      },
    });

    const failed = workbenchReducer(completed, {
      type: "task_status",
      status: "failed",
      error: "添加图层需要指定数据源",
    });

    expect(failed.status).toBe("failed");
    expect(failed.error).toBe("添加图层需要指定数据源");
    expect(failed.viewState?.annotations).toEqual([{ text: "清华大学", position: [0.5, 0.1] }]);
    expect(failed.layers[0]?.name).toBe("海淀区边界");
  });

  it("moves a completed map into processing as soon as an adjustment is submitted", () => {
    const completed = workbenchReducer(initialWorkbenchState, {
      type: "history_loaded",
      requestId: 3,
      status: "completed",
    });

    const processing = workbenchReducer(completed, { type: "conversation_started" });

    expect(processing.status).toBe("processing");
    expect(processing.error).toBeNull();
  });

  it("starts a new execution trace for a later adjustment", () => {
    const completed = {
      ...initialWorkbenchState,
      requestId: 3,
      status: "completed" as const,
      logs: [{ message: "旧日志" }],
      traceId: "trace-old",
      runId: 12,
      traceEvents: [{
        event_id: "old-event",
        event_seq: 1,
        event_type: "run",
        status: "success",
        summary: "旧执行",
      }],
      traceTotalCount: 1,
    };

    const processing = workbenchReducer(completed, { type: "conversation_started" });

    expect(processing.status).toBe("processing");
    expect(processing.logs).toEqual([]);
    expect(processing.traceEvents).toEqual([]);
    expect(processing.traceTotalCount).toBeNull();
    expect(processing.traceId).toBeNull();
    expect(processing.runId).toBeNull();
  });

  it("preserves roles when loading a historical conversation", () => {
    const state = workbenchReducer(initialWorkbenchState, {
      type: "message_loaded",
      role: "user",
      content: "绘制广东地图",
    });
    const withAssistant = workbenchReducer(state, {
      type: "message_loaded",
      role: "assistant",
      content: "地图已生成",
    });

    expect(withAssistant.messages).toEqual([
      { role: "user", content: "绘制广东地图" },
      { role: "assistant", content: "地图已生成" },
    ]);
  });

  it("restores process logs when loading a historical task", () => {
    const state = workbenchReducer(initialWorkbenchState, {
      type: "logs_loaded",
      logs: [{ step: "数据源校验", message: "未找到可用的河流数据" }],
    });

    expect(state.logs).toEqual([{ step: "数据源校验", message: "未找到可用的河流数据" }]);
  });

  it("keeps one trace event when legacy and unified SSE events carry the same event", () => {
    const traceEvent = {
      event_id: "evt-1",
      event_seq: 1,
      event_type: "tool_call",
      status: "success",
      summary: "执行工具",
      trace_id: "trace-1",
      run_id: 7,
    };
    const legacy = workbenchReducer(initialWorkbenchState, {
      type: "stream_event",
      event: { id: "1", event: "process_log", data: { trace_event: traceEvent, message: "执行工具" } },
    });
    const unified = workbenchReducer(legacy, {
      type: "stream_event",
      event: { id: "2", event: "trace_event", data: { trace_event: traceEvent } },
    });

    expect(unified.traceEvents).toHaveLength(1);
    expect(unified.traceEvents[0].event_type).toBe("tool_call");
    expect(unified.runId).toBe(7);
  });

  it("keeps every process log available for the trace viewer", () => {
    const logs = Array.from({ length: 34 }, (_, index) => ({
      id: index + 1,
      step: `步骤 ${index + 1}`,
      message: `日志 ${index + 1}`,
      trace_id: "trace-34",
    }));

    const state = workbenchReducer(initialWorkbenchState, {
      type: "logs_loaded",
      logs,
    });

    expect(state.logs).toHaveLength(34);
    expect(state.logs[0]).toEqual(logs[0]);
    expect(state.logs[33]).toEqual(logs[33]);
  });

  it("restores historical map context for the final PNG view", () => {
    const state = workbenchReducer(initialWorkbenchState, {
      type: "history_loaded",
      requestId: 21,
      status: "completed",
      viewState: {
        map: { title: "北京市地图", layer_count: 1 },
        layers: [{ id: "beijing", name: "北京边界", geometry_type: "Polygon" }],
      },
    });

    expect(state.requestId).toBe(21);
    expect(state.status).toBe("completed");
    expect(state.viewState?.map?.title).toBe("北京市地图");
    expect(state.layers[0]?.name).toBe("北京边界");
  });

  it("restores the trace and failure reason for a historical failed run", () => {
    const state = workbenchReducer(initialWorkbenchState, {
      type: "history_loaded",
      requestId: 116,
      status: "failed",
      traceId: "web_session_116:create",
      error: "数据源校验未通过：未找到可用的河流数据",
    });

    expect(state.traceId).toBe("web_session_116:create");
    expect(state.error).toBe("数据源校验未通过：未找到可用的河流数据");
  });
});
