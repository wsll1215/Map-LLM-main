import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ConversationFeed, conversationActivity } from "./ConversationFeed";

describe("ConversationFeed", () => {
  it("renders the assistant stream as a readable conversation, not only a status", () => {
    const markup = renderToStaticMarkup(
      <ConversationFeed
        messages={[
          { role: "user", content: "绘制城市道路" },
          { role: "assistant", content: "正在查询道路数据" },
        ]}
        isWorking
      />,
    );

    expect(markup).toContain("绘制城市道路");
    expect(markup).toContain("正在查询道路数据");
    expect(markup).toContain("实时输出");
  });

  it("shows readable execution progress when a tool call has no model text", () => {
    const markup = renderToStaticMarkup(
      <ConversationFeed
        messages={[{ role: "user", content: "绘制城市道路" }]}
        activity="正在获取道路数据并更新地图"
        isWorking
      />,
    );

    expect(markup).toContain("正在获取道路数据并更新地图");
    expect(markup).toContain("执行进展");
  });

  it("keeps process trace summaries visible between model chunks", () => {
    expect(conversationActivity({ event_id: "evt-1", event_seq: 1, event_type: "process_log", status: "success", summary: "数据请求已返回 120 个要素" })).toBe("数据请求已返回 120 个要素");

    const markup = renderToStaticMarkup(
      <ConversationFeed
        messages={[{ role: "user", content: "绘制城市道路" }]}
        activity="数据请求已返回 120 个要素"
        isWorking
      />,
    );

    expect(markup).toContain("数据请求已返回 120 个要素");
  });
});
