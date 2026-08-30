import { CloudDownloadOutlined, EyeOutlined, PictureOutlined, ReloadOutlined } from "@ant-design/icons";
import { Button, Drawer, Empty, Space } from "antd";
import type { GeneratedMap } from "../types/api";
import { LivePreviewPanel } from "./LivePreviewPanel";

export interface ArtifactDrawerProps {
  open: boolean;
  onClose: () => void;
  imageUrl: string | null;
  title: string;
  meta: string;
  isFinal: boolean;
  loading?: boolean;
  maps?: GeneratedMap[];
  error?: string | null;
  onReload?: () => void;
}

export function ArtifactDrawerContent({
  imageUrl,
  title,
  meta,
  isFinal,
  loading = false,
  maps = [],
  error,
  onReload,
}: Omit<ArtifactDrawerProps, "open" | "onClose">) {
  return <div className="artifact-drawer-content">
    <header className="artifact-drawer-header">
      <div>
        <span className="section-kicker">ARTIFACTS</span>
        <h2>成果预览</h2>
        <p>{isFinal ? "最终 PNG 与历史版本" : "实时生成的中间产物"}</p>
      </div>
      <PictureOutlined aria-hidden="true" />
    </header>

    <LivePreviewPanel imageUrl={imageUrl || undefined} title={title} meta={meta} isFinal={isFinal} loading={loading} />

    {error && <div className="artifact-drawer-error" role="alert">
      <span>{error}</span>
      {onReload && <Button size="small" icon={<ReloadOutlined />} onClick={onReload}>重新加载</Button>}
    </div>}

    {maps.length > 0 ? <section className="artifact-file-list" aria-label="已保存地图文件">
      <div className="artifact-section-heading"><strong>已保存文件</strong><span>{maps.length} 个版本</span></div>
      {maps.map((map) => <div className="artifact-file-row" key={map.id}>
        <div><strong>地图文件 v{map.version}</strong><span>{map.filename}</span></div>
        {map.file_exists === false ? <span className="file-unavailable">文件不可用</span> : <Space size={4}>
          <Button size="small" icon={<EyeOutlined />} href={map.file_path} target="_blank" rel="noreferrer">打开</Button>
          <Button size="small" icon={<CloudDownloadOutlined />} href={map.file_path} download={map.filename}>下载</Button>
        </Space>}
      </div>)}
    </section> : !imageUrl && !loading && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无可用成果" />}
  </div>;
}

export function ArtifactDrawer({
  open,
  onClose,
  imageUrl,
  title,
  meta,
  isFinal,
  loading = false,
  maps = [],
  error,
  onReload,
}: ArtifactDrawerProps) {
  return <Drawer
    rootClassName="artifact-drawer"
    title={null}
    placement="right"
    size="default"
    getContainer={false}
    open={open}
    onClose={onClose}
    destroyOnClose={false}
  >
    <ArtifactDrawerContent imageUrl={imageUrl} title={title} meta={meta} isFinal={isFinal} loading={loading} maps={maps} error={error} onReload={onReload} />
  </Drawer>;
}
