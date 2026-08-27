import { BulbOutlined, CheckCircleFilled, CloseCircleFilled, ReloadOutlined, WarningOutlined } from "@ant-design/icons";
import { Alert, Progress, Steps, Tag } from "antd";

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
  if (status === "failed") return { percent: reported ?? 0, current: 2 };
  if (status === "needs_clarification") return { percent: 25, current: 1 };
  if (status === "processing") return { percent: Math.max(reported ?? 58, 34), current: 2 };
  if (status === "pending") return { percent: Math.max(reported ?? 12, 8), current: 0 };
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
  const items = STAGES.map((title, index) => ({
    title,
    status: status === "failed" && index === model.current
      ? "error" as const
      : index < model.current || status === "completed"
        ? "finish" as const
        : index === model.current && (status === "processing" || status === "pending" || status === "partial")
          ? "process" as const
          : "wait" as const,
  }));

  return <section className={`progress-status progress-status-${status}`} aria-label="处理进度">
    <div className="progress-status-header"><div className="progress-status-title"><span className="progress-status-icon" aria-hidden="true">{statusIcon(status)}</span><div><span className="progress-status-kicker">任务进度</span><strong>{copy.label}</strong></div></div><Tag color={copy.color}>{status === "partial" ? "未完全交付" : `${model.percent}%`}</Tag></div>
    <Progress percent={model.percent} status={status === "failed" ? "exception" : status === "completed" ? "success" : "active"} showInfo={false} />
    <Steps className="progress-status-steps" size="small" responsive={false} items={items} />
    <div className="progress-status-message"><strong>{message || copy.detail}</strong>{message && message !== copy.detail && <span>{copy.detail}</span>}</div>
    {status === "failed" && <Alert className="progress-status-alert" type="error" showIcon title="本轮没有完成" description={copy.detail} />}
  </section>;
}
