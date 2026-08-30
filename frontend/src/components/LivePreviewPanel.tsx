import { EyeOutlined, PictureOutlined } from "@ant-design/icons";
import { Tag } from "antd";

export interface LivePreviewPanelProps {
  imageUrl?: string | null;
  title: string;
  meta?: string;
  isFinal: boolean;
  loading?: boolean;
}

export function LivePreviewPanel({ imageUrl, title, meta, isFinal, loading }: LivePreviewPanelProps) {
  return (
    <aside className={`live-preview-panel ${isFinal ? "live-preview-panel-final" : "live-preview-panel-streaming"}`} aria-label={title}>
      <div className="live-preview-header">
        <div className="live-preview-heading"><span className="live-preview-icon" aria-hidden="true">{isFinal ? <PictureOutlined /> : <EyeOutlined />}</span><div><strong>{title}</strong><span>{isFinal ? "最终交付" : "每次工具调用后更新"}</span></div></div>
        <Tag color={isFinal ? "success" : "processing"}>{isFinal ? "FINAL" : "LIVE"}</Tag>
      </div>
      <div className="live-preview-image-wrap">
        {imageUrl ? <img className="live-preview-image" src={imageUrl} alt={`${title}预览`} /> : <div className="live-preview-empty" role="status">{loading ? "正在生成中间产物" : "等待第一张预览图"}</div>}
      </div>
      <div className="live-preview-meta"><span>{meta || (isFinal ? "PNG 文件" : "尚未收到渲染事件")}</span>{!isFinal && <i aria-label="实时更新中" title="实时更新中" />}</div>
    </aside>
  );
}
