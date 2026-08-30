import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { LivePreviewPeek } from "./LivePreviewPeek";

describe("LivePreviewPeek", () => {
  it("shows the current intermediate image without reserving a map column", () => {
    const markup = renderToStaticMarkup(
      <LivePreviewPeek
        imageUrl="/generated_maps/preview-v4.png?preview_ts=4"
        title="中间产物"
        meta="v4 · render_map"
        isFinal={false}
        onOpen={() => undefined}
      />,
    );

    expect(markup).toContain("preview-v4.png");
    expect(markup).toContain("中间产物");
    expect(markup).toContain("实时预览");
    expect(markup).toContain("map-preview-peek");
    expect(markup).not.toContain("live-preview-panel");
  });

  it("keeps a compact loading affordance before the first preview arrives", () => {
    const markup = renderToStaticMarkup(
      <LivePreviewPeek
        imageUrl={null}
        title="中间产物"
        meta="等待渲染事件"
        isFinal={false}
        loading
        onOpen={() => undefined}
      />,
    );

    expect(markup).toContain("等待中间产物");
    expect(markup).toContain("等待渲染事件");
  });
});
