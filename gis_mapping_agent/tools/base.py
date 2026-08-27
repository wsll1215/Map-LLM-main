"""GIS制图工具基类"""

from abc import ABC, abstractmethod
import json
import time
from typing import Any, Dict, Optional, Type
from pydantic import BaseModel, Field, ValidationError
from langchain_core.tools import BaseTool
from langchain_core.callbacks import CallbackManagerForToolRun

from ..models.schemas import MapState
from ..utils.logger import get_logger
from ..utils.helpers import generate_unique_id
from ..state import get_session_context, record_tool_trace, save_map_state_context


class GISToolInput(BaseModel):
    """GIS工具输入基类"""
    pass


class GISToolOutput(BaseModel):
    """GIS工具输出基类"""
    success: bool = Field(description="操作是否成功")
    message: str = Field(description="操作结果消息")
    data: Optional[Dict[str, Any]] = Field(default=None, description="返回的数据")
    map_state: Optional[MapState] = Field(default=None, description="更新后的地图状态")
    error_code: Optional[str] = Field(default=None, description="机器可读错误类型")
    recoverable: bool = Field(default=False, description="模型是否可以继续修正或重试")
    retryable: bool = Field(default=False, description="是否建议自动重试")
    next_action: Optional[str] = Field(default=None, description="模型下一步动作")


def classify_tool_error(error: Exception) -> Dict[str, Any]:
    """Map exceptions to stable recovery instructions for the LLM."""
    message = str(error).lower()
    error_code = getattr(error, "error_code", None)
    retryable = bool(getattr(error, "retryable", False))
    if error_code is None:
        if any(token in message for token in ["网络", "timeout", "timed out", "connection"]):
            error_code = "network_error"
            retryable = True
        elif "渲染" in message or "render" in message:
            error_code = "render_error"
            retryable = True
        elif any(token in message for token in ["不存在", "找不到", "路径", "resource"]):
            error_code = "resource_not_found"
        elif isinstance(error, (ValidationError, ValueError, TypeError)):
            error_code = "validation_error"
        elif isinstance(error, FileNotFoundError):
            error_code = "resource_not_found"
        elif isinstance(error, TimeoutError):
            error_code = "network_error"
            retryable = True
        else:
            error_code = "internal_error"

    next_actions = {
        "validation_error": "adjust_tool_arguments",
        "resource_not_found": "select_valid_resource",
        "network_error": "retry_tool",
        "remote_data_empty": "choose_alternative_data_source",
        "state_error": "load_or_create_map_state",
        "render_error": "retry_render",
        "clarification_required": "ask_user",
        "intent_unclear": "reclassify_request",
    }
    recoverable = error_code != "internal_error"
    return {
        "error_code": error_code,
        "recoverable": recoverable,
        "retryable": retryable,
        "next_action": next_actions.get(error_code, "retry_or_report"),
    }


def tool_failure(message: str, error: Optional[Exception] = None, *, data: Optional[Dict[str, Any]] = None) -> GISToolOutput:
    """Create a structured failure without raising past the tool boundary."""
    details = classify_tool_error(error or RuntimeError(message))
    payload = dict(data or {})
    payload.update(details)
    return GISToolOutput(success=False, message=message, data=payload, **details)


def format_tool_result(result: GISToolOutput) -> str:
    """Serialize a tool result for a LangChain ToolMessage."""
    payload = result.model_dump(exclude_none=True, exclude={"map_state"})
    return json.dumps({"tool_result": payload}, ensure_ascii=False, default=str)


class BaseGISTool(BaseTool):
    """GIS制图工具基类

    所有GIS制图工具都应该继承此基类，并实现相应的抽象方法。
    """

    # 内部状态
    _current_map_state: Optional[MapState] = None
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # 动态创建logger，避免pickle问题
        logger = get_logger("GISTool")
        logger.info(f"初始化工具: {self.name}")
    
    @property
    def current_map_state(self) -> Optional[MapState]:
        """获取当前地图状态"""
        return self._current_map_state
    
    @current_map_state.setter
    def current_map_state(self, state: MapState) -> None:
        """设置当前地图状态"""
        self._current_map_state = state
        logger = get_logger("GISTool")
        logger.debug(f"更新地图状态: {state.config.map_id}")
    
    def _run(
        self,
        run_manager: Optional[CallbackManagerForToolRun] = None,
        **kwargs: Any,
    ) -> str:
        """执行工具的主要逻辑"""
        start_time = time.time()
        trace_event = None
        validated_payload = {}
        try:
            logger = get_logger("GISTool")
            logger.info(f"开始执行工具: {self.name}")
            logger.debug(f"输入参数: {kwargs}")

            try:
                from mapping.trace import publish_trace_event, run_for_session, start_trace_event

                trace_run = run_for_session(kwargs.get("session_id"))
                if trace_run:
                    trace_event = start_trace_event(
                        run=trace_run,
                        event_type="tool_call",
                        phase="tool",
                        actor="agent",
                        summary=f"执行工具: {self.name}",
                        input_data=kwargs,
                        attributes={"tool_name": self.name, "tool_description": self.description or ""},
                    )
                    publish_trace_event(trace_event)
            except Exception:
                trace_event = None

            # 验证输入参数
            validated_input = self.args_schema(**kwargs)
            validated_payload = validated_input.model_dump() if hasattr(validated_input, "model_dump") else validated_input.dict()

            # 执行具体的工具逻辑
            result = self._execute_tool(validated_input, run_manager)

            logger.info(
                f"工具{'执行成功' if result.success else '返回失败结果'}: {self.name}"
            )
            logger.debug(f"输出结果: {result.message}")

            # 更新地图状态
            if result.map_state:
                self.current_map_state = result.map_state
                # 同步状态到所有工具
                self._sync_state_to_all_tools()

            map_state = result.map_state or self._current_map_state
            session_id = kwargs.get("session_id")
            if map_state is not None:
                session_id = map_state.get_session_id()
                save_map_state_context(session_id, map_state)
            context = get_session_context(session_id, create=False)
            record_tool_trace(
                session_id=session_id,
                task_id=getattr(context, "task_id", None),
                tool_name=self.name,
                args=kwargs,
                result_summary={"message": result.message, "data": result.data},
                success=result.success,
                error=None if result.success else result.message,
                duration_ms=int((time.time() - start_time) * 1000),
            )

            if trace_event:
                from mapping.trace import finish_trace_event, publish_trace_event

                trace_event = finish_trace_event(
                    trace_event,
                    status="success" if result.success else "error",
                    output_data={"message": result.message, "data": result.data},
                    attributes={"validated_input": validated_payload, "map_state_changed": bool(result.map_state)},
                    error=None if result.success else {
                        "error_code": result.error_code or "tool_error",
                        "retryable": result.retryable,
                        "next_action": result.next_action or "inspect_trace",
                    },
                )
                publish_trace_event(trace_event)

            return self._format_output(result)

        except Exception as e:
            error_msg = f"工具执行失败 {self.name}: {str(e)}"
            logger = get_logger("GISTool")
            logger.error(error_msg)
            session_id = kwargs.get("session_id")
            if self._current_map_state is not None:
                session_id = self._current_map_state.get_session_id()
            context = get_session_context(session_id, create=False)
            record_tool_trace(
                session_id=session_id,
                task_id=getattr(context, "task_id", None),
                tool_name=self.name,
                args=kwargs,
                result_summary=None,
                success=False,
                error=str(e),
                duration_ms=int((time.time() - start_time) * 1000),
            )

            if trace_event:
                from mapping.trace import finish_trace_event, publish_trace_event

                trace_event = finish_trace_event(
                    trace_event,
                    status="error",
                    output_data={"message": error_msg},
                    attributes={"validated_input": validated_payload},
                    error={"error_code": getattr(e, "error_code", "internal_error"), "retryable": bool(getattr(e, "retryable", False)), "next_action": "inspect_trace"},
                )
                publish_trace_event(trace_event)
            
            error_result = tool_failure(error_msg, e, data={"error": str(e)})
            return self._format_output(error_result)
    
    @abstractmethod
    def _execute_tool(
        self,
        input_data: GISToolInput,
        run_manager: Optional[CallbackManagerForToolRun] = None,
    ) -> GISToolOutput:
        """执行具体的工具逻辑
        
        Args:
            input_data: 验证后的输入数据
            run_manager: 回调管理器
            
        Returns:
            GISToolOutput: 工具执行结果
        """
        pass
    
    def _format_output(self, result: GISToolOutput) -> str:
        """Return a compact JSON observation that the LLM can act on."""
        return format_tool_result(result)
    
    def _generate_id(self) -> str:
        """生成唯一ID"""
        return generate_unique_id()
    
    def _validate_map_state(self) -> bool:
        """验证当前地图状态是否有效"""
        return self._current_map_state is not None
    
    def _get_map_state_or_create(self) -> MapState:
        """获取地图状态；没有已验证范围时拒绝创建全球占位地图。"""
        if self._current_map_state is None:
            raise ValueError("缺少经过验证的地图范围，无法创建地图状态")
        
        return self._current_map_state

    def _sync_state_to_all_tools(self):
        """同步地图状态到所有工具"""
        if hasattr(self, '_tool_registry') and self._current_map_state:
            for tool in self._tool_registry:
                if hasattr(tool, '_current_map_state'):
                    tool._current_map_state = self._current_map_state
