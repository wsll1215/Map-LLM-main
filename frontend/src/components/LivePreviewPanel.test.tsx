import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { LivePreviewPanel } from "./LivePreviewPanel";
describe("LivePreviewPanel", () => {
  it("keeps the intermediate artifact visible outside the map canvas", () => {
    const markup = renderToStaticMarkup(
      <LivePreviewPanel
        imageUrl="/generated_maps/preview-v3.png?preview_ts=3"
        title="中间产物"
        meta="v3 · render_map"
        isFinal={false}
      />,
    );

    expect(markup).toContain("中间产物");
    expect(markup).toContain("preview-v3.png");
    expect(markup).toContain("实时更新");
  });
});
