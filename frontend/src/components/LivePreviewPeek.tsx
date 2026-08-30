import { EyeOutlined, LoadingOutlined, PictureOutlined } from "@ant-design/icons";

export interface LivePreviewPeekProps {
  imageUrl: string | null;
  title: string;
  meta: string;
  isFinal: boolean;
  loading?: boolean;
  onOpen: () => void;
}

export function LivePreviewPeek({ imageUrl, title, meta, isFinal, loading = false, onOpen }: LivePreviewPeekProps) {
  if (!imageUrl && !loading) return null;

  return <button
    type="button"
    className={`map-preview-peek ${isFinal ? "map-preview-peek-final" : "map-preview-peek-live"}`}
    onClick={onOpen}
    aria-label={`${title}，打开成果预览`}
  >
    <span className="map-preview-peek-header">
      <span className="map-preview-peek-icon" aria-hidden="true">{isFinal ? <PictureOutlined /> : <EyeOutlined />}</span>
      <span className="map-preview-peek-title"><strong>{isFinal ? "成果预览" : "实时预览"}</strong><small>{title}</small></span>
      {loading && <LoadingOutlined className="map-preview-peek-loading" spin aria-hidden="true" />}
    </span>
    {imageUrl ? <span className="map-preview-peek-image-wrap"><img className="map-preview-peek-image" src={imageUrl} alt={`${title}缩略图`} /></span> : <span className="map-preview-peek-empty"><LoadingOutlined spin aria-hidden="true" />等待中间产物</span>}
    <span className="map-preview-peek-footer"><span>{meta || "等待渲染事件"}</span><span>打开成果</span></span>
  </button>;
}
