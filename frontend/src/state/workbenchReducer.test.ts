import { describe, expect, it } from "vitest";
import { initialWorkbenchState, workbenchReducer } from "./workbenchReducer";

describe("workbenchReducer", () => {
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
});
