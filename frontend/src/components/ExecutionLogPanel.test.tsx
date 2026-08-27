import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ExecutionLogPanel } from "./ExecutionLogPanel";

describe("ExecutionLogPanel", () => {
  it("renders all logs and their trace metadata instead of only the tail", () => {
    const logs = Array.from({ length: 34 }, (_, index) => ({
      id: index + 1,
      step: `步骤 ${index + 1}`,
      message: `日志 ${index + 1}`,
      trace_id: "trace-34",
      tool_name: index === 33 ? "render_map" : undefined,
    }));

    const markup = renderToStaticMarkup(
      <ExecutionLogPanel logs={logs} traceId="trace-34" isWorking={false} />,
    );

    expect(markup.match(/class="log-line /g)).toHaveLength(34);
    expect(markup).toContain("步骤 1");
    expect(markup).toContain("步骤 34");
    expect(markup).toContain("日志 34 条");
    expect(markup).toContain("trace-34");
    expect(markup).toContain("render_map");
  });

  it("keeps Trace available when a historical run exists before events load", () => {
    const markup = renderToStaticMarkup(
      <ExecutionLogPanel
        logs={[]}
        traceId="trace-history"
        runId={18}
        requestId={133}
        isWorking={false}
      />,
    );

    expect(markup).toContain("打开 Trace");
    expect(markup).not.toContain('disabled=""');
  });

  it("separates ordinary log count from trace event count", () => {
    const markup = renderToStaticMarkup(
      <ExecutionLogPanel
        logs={[{ id: 1, message: "日志 1" }, { id: 2, message: "日志 2" }]}
        traceEvents={[
          { event_id: "evt-1", event_seq: 1, event_type: "run", status: "success", summary: "任务" },
          { event_id: "evt-2", event_seq: 2, event_type: "render", status: "success", summary: "渲染" },
        ]}
        traceId="trace-counts"
        traceTotalCount={2}
        runId={18}
        isWorking={false}
      />,
    );

    expect(markup).toContain("日志 2 条");
    expect(markup).toContain("Trace 2 个事件");
  });

  it("shows loaded and total trace counts when the event list is paginated", () => {
    const markup = renderToStaticMarkup(
      <ExecutionLogPanel
        logs={[]}
        traceEvents={[{ event_id: "evt-1", event_seq: 1, event_type: "run", status: "success", summary: "任务" }]}
        traceTotalCount={65}
        traceId="trace-paged"
        isWorking={false}
      />,
    );

    expect(markup).toContain("Trace 已加载 1 / 共 65 个事件");
  });

  it("labels the trace count independently from the visible log window", () => {
    const markup = renderToStaticMarkup(
      <ExecutionLogPanel
        logs={Array.from({ length: 50 }, (_, index) => ({ id: index + 1, message: `日志 ${index + 1}` }))}
        traceEvents={Array.from({ length: 65 }, (_, index) => ({
          event_id: `evt-${index + 1}`,
          event_seq: index + 1,
          event_type: "process_log",
          status: "success",
          summary: `事件 ${index + 1}`,
        }))}
        traceId="trace-65"
        runId={197}
        isWorking={false}
      />,
    );

    expect(markup).toContain("日志 50 条");
    expect(markup).toContain("Trace 65 个事件");
  });

});
