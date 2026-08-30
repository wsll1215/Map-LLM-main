export type PreviewPresentationStatus = "processing" | "pending" | "completed" | "partial" | "failed" | "idle" | "needs_clarification";

export interface PreviewPresentationInput {
  status: PreviewPresentationStatus;
  currentPreviewUrl: string | null;
  finalMapUrl: string | null;
  hasStoredMap: boolean;
}

export interface PreviewPresentation {
  imageUrl: string | null;
  title: string;
  isFinal: boolean;
}

export function choosePreviewPresentation({ status, currentPreviewUrl, finalMapUrl, hasStoredMap }: PreviewPresentationInput): PreviewPresentation {
  if (status === "completed" && hasStoredMap) return { imageUrl: finalMapUrl, title: "最终产物", isFinal: true };
  if ((status === "partial" || status === "failed") && currentPreviewUrl) return { imageUrl: currentPreviewUrl, title: "最近预览", isFinal: false };
  if ((status === "partial" || status === "failed") && hasStoredMap) return { imageUrl: finalMapUrl, title: "已保留成果", isFinal: true };
  return { imageUrl: currentPreviewUrl, title: "中间产物", isFinal: false };
}
