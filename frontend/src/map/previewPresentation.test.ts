import { describe, expect, it } from "vitest";
import { choosePreviewPresentation } from "./previewPresentation";

describe("choosePreviewPresentation", () => {
  it("keeps the current run preview visible after a failed run", () => {
    expect(choosePreviewPresentation({
      status: "failed",
      currentPreviewUrl: "/preview/latest.png",
      finalMapUrl: "/maps/v1.png",
      hasStoredMap: true,
    })).toEqual({ imageUrl: "/preview/latest.png", title: "最近预览", isFinal: false });
  });

  it("uses the stored artifact when a failed run produced no preview", () => {
    expect(choosePreviewPresentation({
      status: "failed",
      currentPreviewUrl: null,
      finalMapUrl: "/maps/v1.png",
      hasStoredMap: true,
    })).toEqual({ imageUrl: "/maps/v1.png", title: "已保留成果", isFinal: true });
  });

  it("uses the final artifact only after a completed run", () => {
    expect(choosePreviewPresentation({
      status: "completed",
      currentPreviewUrl: "/preview/latest.png",
      finalMapUrl: "/maps/v2.png",
      hasStoredMap: true,
    })).toEqual({ imageUrl: "/maps/v2.png", title: "最终产物", isFinal: true });
  });
});
