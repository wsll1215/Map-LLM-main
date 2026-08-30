import { BranchesOutlined, ReloadOutlined, RobotOutlined } from "@ant-design/icons";
import type { TraceEvent } from "../types/api";
import type { WorkbenchMessage } from "../state/workbenchReducer";

export function conversationActivity(event?: TraceEvent | null): string | null {
  if (!event) return null;
  const attributes = event.attributes || {};
  const toolName = typeof attributes.tool_name === "string" ? attributes.tool_name : null;
  const role = typeof attributes.role === "string" ? attributes.role : null;
  if (event.event_type === "intent_parse") return "正在理解制图需求并确认地点与图层";
  if (event.event_type === "source_plan") return "正在选择可用数据源并校验空间范围";
  if (event.event_type === "data_fetch") return "正在获取地图数据并检查返回结果";
  if (event.event_type === "tool_call") return toolName ? `正在执行 ${toolName}` : "正在执行地图工具";
  if (event.event_type === "layer_process") return "正在整理图层并校验空间数据";
  if (event.event_type === "render") return "正在更新地图预览";
  if (event.event_type === "preview_update") return "中间产物已更新，正在同步到画布";
  if (event.event_type === "llm_generation") return role === "agent" ? "正在生成下一步制图动作" : "正在处理模型输出";
  if (event.event_type === "retry") return "上一步需要重试，正在按恢复策略继续";
  if (event.event_type === "process_log" && event.summary) return event.summary;
  if ((event.event_type === "warning" || event.event_type === "error") && event.summary) return event.summary;
  return event.status === "running" ? "正在继续处理地图任务" : null;
}

export function ConversationFeed({ messages, activity, isWorking }: { messages: WorkbenchMessage[]; activity?: string | null; isWorking: boolean }) {
  const visibleMessages = messages.slice(-8);
  return (
    <section className="conversation-section" aria-label="对话流">
      <div className="section-title"><span>对话流</span><span className={`conversation-live ${isWorking ? "conversation-live-active" : ""}`}><i />{isWorking ? "实时输出" : "已完成"}</span></div>
      <div className="conversation-feed" aria-live="polite">
        {visibleMessages.length === 0 && !activity ? <p className="conversation-empty">提交需求后，模型输出会在这里逐段显示。</p> : visibleMessages.map((message, index) => (
          <article className={`conversation-message conversation-message-${message.role}`} key={`${message.role}-${index}-${message.content.slice(0, 12)}`}>
            <span className="conversation-avatar" aria-hidden="true">{message.role === "user" ? <BranchesOutlined /> : <RobotOutlined />}</span>
            <div className="conversation-message-body"><span className="conversation-message-label">{message.role === "user" ? "你的需求" : message.role === "assistant" ? "Agent" : "系统"}</span><p>{message.content || "正在接收输出..."}{isWorking && message.role === "assistant" && index === visibleMessages.length - 1 && <ReloadOutlined className="conversation-cursor" spin />}</p></div>
          </article>
        ))}
        {isWorking && activity && <article className="conversation-message conversation-message-system"><span className="conversation-avatar conversation-avatar-live" aria-hidden="true"><i /></span><div className="conversation-message-body conversation-activity"><span className="conversation-message-label">执行进展</span><p>{activity}<ReloadOutlined className="conversation-cursor" spin /></p></div></article>}
      </div>
    </section>
  );
}
