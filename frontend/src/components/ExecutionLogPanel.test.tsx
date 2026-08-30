import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { EventDetails, ExecutionLogPanel } from "./ExecutionLogPanel";

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

  it("can render as a one-line collapsed log strip", () => {
    const markup = renderToStaticMarkup(
      <ExecutionLogPanel
        logs={[{ id: 1, message: "不要在折叠状态显示正文" }]}
        traceId="trace-collapsed"
        isWorking={false}
        collapsed
      />,
    );

    expect(markup).toContain('aria-expanded="false"');
    expect(markup).toContain("日志 1 条");
    expect(markup).not.toContain("不要在折叠状态显示正文");
  });

  it("shows tool-specific inputs and result fields in trace details", () => {
    const markup = renderToStaticMarkup(
      <EventDetails event={{
          event_id: "tool-1",
          event_seq: 1,
          event_type: "tool_call",
          status: "success",
          summary: "执行道路查询",
          input: { location: "北京" },
          output: { tool_result: { success: true, data: { feature_count: 8 } } },
          attributes: {
            tool_name: "fetch_roads",
            tool_description: "查询道路数据",
            validated_input: { location: "北京" },
            actual_input: { location: "北京", bbox: [116, 39, 117, 40] },
            map_state_changed: true,
          },
        }} />,
    );

    expect(markup).toContain("工具名称");
    expect(markup).toContain("工具描述");
    expect(markup).toContain("校验后参数");
    expect(markup).toContain("实际执行参数");
    expect(markup).toContain("ToolResult");
    expect(markup).toContain("修改地图状态");
  });

  it("renders structured metadata values without passing objects to React", () => {
    const markup = renderToStaticMarkup(
      <EventDetails event={{
        event_id: "source-1",
        event_seq: 1,
        event_type: "source_plan",
        status: "success",
        summary: "规划数据源",
        attributes: {
          source_type: "remote",
          provider: { name: "Overpass", endpoint: "primary" },
          bbox: [116, 39, 117, 40],
        },
      }} />,
    );

    expect(markup).toContain("Overpass");
    expect(markup).not.toContain("[object Object]");
  });

});
