import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ProgressStatus } from "./ProgressStatus";

describe("ProgressStatus", () => {
  it("does not invent a percentage when the backend has not reported one", () => {
    const markup = renderToStaticMarkup(
      <ProgressStatus status="processing" message="正在获取数据" />,
    );

    expect(markup).toContain("等待后端进度");
    expect(markup).not.toContain("58%");
  });

  it("shows a deterministic stage and percentage for a running task", () => {
    const markup = renderToStaticMarkup(
      <ProgressStatus
        status="processing"
        message="正在处理道路图层"
        latestProgress={58}
      />,
    );

    expect(markup).toContain("获取数据");
    expect(markup).toContain("58%");
    expect(markup).toContain("正在处理道路图层");
    expect(markup).toContain('aria-valuenow="58"');
  });

  it("uses a compact phase rail that remains readable in the inspector", () => {
    const markup = renderToStaticMarkup(
      <ProgressStatus status="processing" message="正在处理道路图层" latestProgress={58} />,
    );

    expect(markup).toContain('aria-label="处理阶段"');
    expect(markup).toContain('class="progress-phase progress-phase-active"');
    expect(markup).not.toContain("ant-steps");
  });

  it("does not present a partial result as fully completed", () => {
    const markup = renderToStaticMarkup(
      <ProgressStatus status="partial" message="小学图层未能获取" />,
    );

    expect(markup).toContain("部分完成");
    expect(markup).toContain("小学图层未能获取");
    expect(markup).toContain("未完全交付");
    expect(markup).toContain('aria-valuenow="100"');
    expect(markup).not.toContain("progress-status-alert");
    expect(markup).not.toContain("ant-progress-status-exception");
    expect(markup).not.toContain("ant-steps-item-error");
  });
});
