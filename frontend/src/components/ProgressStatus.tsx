import { BulbOutlined, CheckCircleFilled, CloseCircleFilled, ReloadOutlined, WarningOutlined } from "@ant-design/icons";
import { Progress, Tag } from "antd";

export type ProgressStatusValue = "idle" | "pending" | "processing" | "needs_clarification" | "completed" | "partial" | "failed";

const STAGES = ["任务提交", "理解需求", "获取数据", "完成交付"];
const STATUS_COPY: Record<ProgressStatusValue, { label: string; detail: string; color: string }> = {
  idle: { label: "准备开始", detail: "提交需求后显示执行进度", color: "default" },
  pending: { label: "任务已提交", detail: "正在创建任务并准备数据", color: "processing" },
  processing: { label: "生成中", detail: "正在获取数据并处理图层", color: "processing" },
  needs_clarification: { label: "等待补充信息", detail: "补充信息后会继续当前任务", color: "blue" },
  completed: { label: "已完成", detail: "地图已生成，可以查看成果", color: "success" },
  partial: { label: "部分完成", detail: "结果可查看，缺失图层需要补齐", color: "warning" },
  failed: { label: "生成失败", detail: "请根据错误信息修正后重试", color: "error" },
};

export function progressModel(status: ProgressStatusValue, latestProgress?: number | null) {
  const reported = typeof latestProgress === "number" ? Math.max(0, Math.min(100, latestProgress)) : null;
  if (status === "completed") return { percent: 100, current: 3 };
  if (status === "partial") return { percent: 100, current: 3 };
  if (status === "failed") return { percent: reported, current: 2 };
  if (status === "needs_clarification") return { percent: 25, current: 1 };
  if (status === "processing") return { percent: reported, current: 2 };
  if (status === "pending") return { percent: reported, current: 0 };
  return { percent: 0, current: 0 };
}

function statusIcon(status: ProgressStatusValue) {
  if (status === "completed") return <CheckCircleFilled />;
  if (status === "failed") return <CloseCircleFilled />;
  if (status === "partial") return <WarningOutlined />;
  if (status === "needs_clarification") return <BulbOutlined />;
  return <ReloadOutlined />;
}

export function ProgressStatus({ status, message, latestProgress }: { status: ProgressStatusValue; message?: string; latestProgress?: number | null }) {
  const copy = STATUS_COPY[status];
  const model = progressModel(status, latestProgress);
  const phaseStatus = (index: number) => {
    if (status === "failed" && index === model.current) return "error";
    if (index < model.current || status === "completed" || status === "partial") return "done";
    if (index === model.current && (status === "processing" || status === "pending" || status === "needs_clarification")) return "active";
    return "pending";
  };

  return <section className={`progress-status progress-status-${status}`} aria-label="处理进度">
    <div className="progress-status-header"><div className="progress-status-title"><span className="progress-status-icon" aria-hidden="true">{statusIcon(status)}</span><div><span className="progress-status-kicker">任务进度</span><strong>{copy.label}</strong></div></div><Tag color={copy.color}>{status === "partial" ? "未完全交付" : model.percent == null ? "等待后端进度" : `${model.percent}%`}</Tag></div>
    <Progress className={model.percent == null && (status === "pending" || status === "processing") ? "progress-indeterminate" : undefined} percent={model.percent ?? 0} status={status === "failed" ? "exception" : status === "completed" ? "success" : "active"} showInfo={false} />
    <div className="progress-phase-rail" role="list" aria-label="处理阶段">{STAGES.map((title, index) => { const phase = phaseStatus(index); return <div className={`progress-phase progress-phase-${phase}`} role="listitem" key={title}><span className="progress-phase-marker" aria-hidden="true">{phase === "done" ? <CheckCircleFilled /> : phase === "error" ? <CloseCircleFilled /> : index + 1}</span><span className="progress-phase-label">{title}</span></div>; })}</div>
    <div className="progress-status-message" aria-live="polite"><strong>{message || copy.detail}</strong>{message && message !== copy.detail && <span>{copy.detail}</span>}</div>
  </section>;
}
