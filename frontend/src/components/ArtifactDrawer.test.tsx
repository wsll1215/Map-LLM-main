import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ArtifactDrawerContent } from "./ArtifactDrawer";

describe("ArtifactDrawer", () => {
  it("keeps intermediate preview and saved files behind one results entry", () => {
    const markup = renderToStaticMarkup(
      <ArtifactDrawerContent
        imageUrl="/generated_maps/preview.png?preview_ts=8"
        title="中间产物"
        meta="v2 · render_map"
        isFinal={false}
        maps={[{
          id: 2,
          request_id: 9,
          filename: "map-v2.png",
          version: 2,
          file_path: "/generated_maps/map-v2.png",
          file_exists: true,
        }]}
      />,
    );

    expect(markup).toContain("中间产物");
    expect(markup).toContain("地图文件 v2");
    expect(markup).toContain("map-v2.png");
  });
});
