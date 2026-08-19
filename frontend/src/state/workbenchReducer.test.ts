import { describe, expect, it } from "vitest";
import { initialWorkbenchState, workbenchReducer } from "./workbenchReducer";

describe("workbenchReducer", () => {
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
});
