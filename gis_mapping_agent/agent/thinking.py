"""思考型GIS制图智能体 - 实现显式的思考-行动-观察循环"""

from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
import json
import math
import time


from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage

from ..models.schemas import MapState
from ..utils.config import Config
from ..utils.logger import setup_logger, get_logger
from ..utils.data_path_resolver import data_path_resolver, extract_data_info_from_request, resolve_data_path
from ..data_sources.remote import (
    extract_location_query,
    extract_remote_poi_query,
    extract_remote_poi_request,
    fetch_remote_boundary,
    fetch_remote_named_poi,
    fetch_remote_pois,
    fetch_remote_roads,
    fetch_remote_waterways,
    resolve_location,
    RemoteDataSourceError,
)
from ..data_sources.catalog import DjangoDatasetCatalog
from ..data_sources.planner import (
    plan_local_sources,
    resolve_local_location,
    semantic_plan_from_source_plan,
)
from ..data_sources.coordinator import build_source_plan
from .intent_gateway import recognize_intent
from ..gis import calculate_extent_from_files, format_extent_for_request
from ..state import get_generalization_context
from ..tools.registry import ALL_UNIFIED_TOOLS
from ..tools.base import format_tool_result, tool_failure


def tool_observation_error(observation: str) -> Optional[Dict[str, Any]]:
    """Extract a structured tool failure without guessing from success text."""
    text = str(observation or "").strip()
    payload: Any = None
    try:
        decoded = json.loads(text)
        payload = decoded.get("tool_result") if isinstance(decoded, dict) else None
        if payload is None and isinstance(decoded, dict) and "success" in decoded:
            payload = decoded
    except (TypeError, ValueError, json.JSONDecodeError):
        payload = None

    if isinstance(payload, dict) and payload.get("success") is False:
        return {
            "error_code": payload.get("error_code") or "tool_error",
            "retryable": bool(payload.get("retryable", False)),
            "next_action": payload.get("next_action") or "inspect_trace",
        }
    if text.startswith(("❌", "错误")):
        return {
            "error_code": "tool_error",
            "retryable": True,
            "next_action": "adjust_tool_arguments",
        }
    return None


def _boundary_extent_inputs(boundary_path: Optional[str]) -> Tuple[Optional[str], Optional[List[str]]]:
    """Turn the verified boundary file into the inputs used by extent calculation."""
    if not boundary_path:
        return None, None
    path = Path(boundary_path).resolve()
    return str(path.parent), [path.name]


def _extent_from_location(location: Any) -> Optional[List[float]]:
    """Use the backend-verified location bbox as the runtime map extent."""
    bbox = getattr(location, "bbox", None)
    try:
        values = [float(value) for value in bbox]
    except (TypeError, ValueError):
        return None
    if (
        len(values) != 4
        or not all(math.isfinite(value) for value in values)
        or values[0] >= values[2]
        or values[1] >= values[3]
    ):
        return None
    return values


class ThinkingGISMappingAgent:
    """思考型GIS制图智能体

    实现显式的思考-行动-观察循环，让推理过程更加透明和可控。
    每一步都会显示详细的思考过程、参数配置逻辑和执行结果。
    """

    def __init__(
        self,
        model_name: str = None,
        temperature: float = Config.HYPERPARAMETERS.LLM_TEMPERATURE,
        max_iterations: int = Config.HYPERPARAMETERS.MAX_TOOL_ITERATIONS,
        verbose: bool = True,
        use_unified_tools: bool = True,
        auto_calculate_extent: bool = True,
        data_directory: str = None,
        data_files: List[str] = None,
        margin_ratio: float = Config.HYPERPARAMETERS.AUTO_EXTENT_MARGIN_RATIO
    ):
        """初始化思考型GIS制图智能体"""

        # 设置日志
        setup_logger()
        self.logger = get_logger("ThinkingGISMappingAgent")
        self._default_data_file_path = None
        self._explicit_data_files = False
        self._semantic_data_plan = None
        self._source_plan = None
        self._source_errors = []

        # 验证配置
        self._validate_config()

        # 如果没有指定模型名称，从配置文件读取
        if model_name is None:
            model_name = Config.OPENAI_MODEL

        # 初始化模型
        self.llm = ChatOpenAI(
            model=model_name,
            temperature=temperature,
            openai_api_key=Config.OPENAI_API_KEY,
            base_url=Config.OPENAI_BASE_URL
        )

        # 自动计算数据范围
        self.auto_extent = None
        self.auto_extent_str = None
        if auto_calculate_extent:
            self.auto_extent, self.auto_extent_str = self._calculate_auto_extent(
                data_directory, data_files, margin_ratio, False
            )

        # 初始化工具并绑定到模型
        self.use_unified_tools = use_unified_tools
        self.tools, self.save_tool = self._initialize_tools()
        self.tool_dict = {tool.name: tool for tool in self.tools}
        # Keep an unbound model for semantic intent completion. The execution
        # model remains tool-bound and is used only after Intent validation.
        self.intent_llm = self.llm
        self.llm = self.llm.bind_tools(self.tools)

        # 设置参数
        self.max_iterations = max_iterations
        self.verbose = verbose

        # 当前地图状态
        self.current_map_state: Optional[MapState] = None
        self.last_assistant_message_id: Optional[str] = None
        self._current_intent: Optional[Any] = None

        # self.logger.info("思考型GIS制图智能体初始化完成")

    def create_map(self, user_request: str, intent: Optional[Any] = None) -> Dict[str, Any]:
        """使用思考-行动-观察循环创建地图"""

        try:
            self.logger.info(f"开始处理制图请求")

            # 从用户请求中提取数据目录和文件信息
            explicit_data_files = data_path_resolver.find_data_files_in_request(user_request)
            data_dir_from_request, data_files_from_request = extract_data_info_from_request(user_request)
            if intent is None:
                intent_trace = {"parent_event_id": None}
                recognition = self._run_trace_phase(
                    event_type="intent_parse",
                    phase="intent",
                    summary="识别用户意图",
                    input_data={"request_text": user_request},
                    operation=lambda: recognize_intent(
                        user_request,
                        current_state=getattr(self, "current_map_state", None),
                        llm=getattr(self, "intent_llm", None),
                        trace_callback=lambda **event: self._publish_intent_trace_child(
                            intent_trace["parent_event_id"], event
                        ),
                    ),
                    output_serializer=lambda value: value.model_dump(mode="json"),
                    on_started=lambda span: intent_trace.update(
                        parent_event_id=getattr(span, "event_id", None)
                    ),
                )
                if recognition.status != "accepted" or recognition.intent is None:
                    return self._intent_failure_response(recognition)
                intent = recognition.intent
            self._current_intent = intent
            self._explicit_data_files = bool(explicit_data_files or intent.explicit_sources)
            if not self._explicit_data_files:
                data_dir_from_request, data_files_from_request = None, []
            self._default_data_file_path = None
            self._semantic_data_plan = None
            self._source_errors = []
            self._source_plan = None
            location = None
            if not self._explicit_data_files and data_dir_from_request and data_files_from_request:
                self._default_data_file_path = resolve_data_path(data_dir_from_request) / data_files_from_request[0]

            if not self._explicit_data_files and not data_files_from_request:
                if intent.layers and not intent.location.text:
                    return {
                        "success": False,
                        "status": "needs_clarification",
                        "message": "缺少地图地点，无法确定空间范围。请补充城市、区域或具体地点。",
                        "error_code": "clarification_required",
                        "clarification": {
                            "missing_fields": ["location"],
                            "next_action": "provide_location",
                        },
                    }
            if not self._explicit_data_files:
                self._source_plan = self._run_trace_phase(
                    event_type="source_plan",
                    phase="data_source",
                    summary="规划数据源",
                    input_data={
                        "location": intent.location.text,
                        "roles": [layer.role for layer in intent.layers],
                    },
                    operation=lambda: build_source_plan(
                        intent,
                        request_text=user_request,
                        catalog=DjangoDatasetCatalog(),
                        session_id=getattr(self, "session_id", None),
                    ),
                    output_serializer=self._serialize_source_plan,
                )
                self._semantic_data_plan = semantic_plan_from_source_plan(self._source_plan)
                self._source_errors = [
                    {
                        "role": source.role,
                        "error_code": source.error_code,
                        "retryable": source.retryable,
                        "next_action": source.next_action,
                        "message": source.error_code,
                    }
                    for source in self._source_plan.layers
                    if source.status in {"failed", "rejected"} and source.error_code
                ]
                if self._source_plan.location and self._source_plan.location.bbox:
                    location = self._source_plan.location
                if self._source_plan.issues:
                    message = "数据源校验未通过：" + "；".join(self._source_plan.issues)
                    self.logger.error(message)
                    return {
                        "success": False,
                        "message": message,
                        "error": message,
                        "error_code": (self._source_errors[0].get("error_code")
                                       if self._source_errors else "resource_not_found"),
                        "source_errors": list(self._source_errors),
                    }
            # 自动计算范围
            if not self._explicit_data_files and location is not None:
                self.auto_extent = _extent_from_location(location)
                self.auto_extent_str = (
                    format_extent_for_request(self.auto_extent)
                    if self.auto_extent
                    else None
                )
            else:
                self.auto_extent, self.auto_extent_str = self._calculate_auto_extent(
                    data_directory=data_dir_from_request,
                    data_files=data_files_from_request if data_files_from_request else None,
                    margin_ratio=Config.HYPERPARAMETERS.AUTO_EXTENT_MARGIN_RATIO,
                    verbose=True
                )

            # 增强用户请求
            enhanced_request = self._enhance_request_with_auto_extent(user_request)

            # 执行思考-行动-观察循环
            result = self._execute_thinking_loop(enhanced_request)

            # 自动保存地图
            if result["success"] and self.save_tool:
                from datetime import datetime
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"auto_saved_map_{timestamp}.png"
                save_result = self.save_tool.invoke({"filename": filename})
                self.logger.info(f"地图已自动保存: {save_result}")
                # 将保存结果添加到最终输出中
                result["output"] += f"\n\n地图已自动保存为: {filename}"

            # 获取最终的地图状态
            final_map_state = self._get_final_map_state()

            # 构建返回结果
            response = {
                "success": result["success"],
                "message": result["message"],
                "agent_output": result["output"],
                "intent": self._serialize_intent(intent),
                "map_state": final_map_state.model_dump() if final_map_state else None,
                "thinking_steps": result.get("thinking_steps", []),
                "source_errors": list(self._source_errors),
                "assistant_message_id": self.last_assistant_message_id,
                "source_plan": self._serialize_source_plan(self._source_plan),
            }

            if not result.get("terminal_tool"):
                self.logger.info("地图创建完成")
            return response

        except Exception as e:
            error_msg = f"地图创建失败: {str(e)}"
            self.logger.error(error_msg)

            return {
                "success": False,
                "message": error_msg,
                "error": str(e),
                "error_code": getattr(e, "error_code", "internal_error"),
                "source_errors": list(getattr(self, "_source_errors", [])),
            }

    @staticmethod
    def _serialize_intent(intent):
        if intent is None:
            return None
        if hasattr(intent, "model_dump"):
            return intent.model_dump(mode="json")
        return {
            "location": {
                "text": getattr(getattr(intent, "location", None), "text", None),
                "precision": getattr(getattr(intent, "location", None), "precision", None),
            },
            "layers": [
                {
                    "role": getattr(layer, "role", None),
                    "required": getattr(layer, "required", True),
                }
                for layer in getattr(intent, "layers", ())
            ],
            "explicit_sources": list(getattr(intent, "explicit_sources", ()) or ()),
            "unknown_fields": list(getattr(intent, "unknown_fields", ()) or ()),
        }

    @staticmethod
    def _serialize_source_plan(plan):
        if plan is None:
            return None
        location_geometry = plan.location.geometry if plan.location else None
        if location_geometry is not None and not isinstance(location_geometry, dict):
            try:
                from shapely.geometry import mapping as shapely_mapping

                location_geometry = shapely_mapping(location_geometry)
            except (ImportError, TypeError, ValueError):
                location_geometry = None
        return {
            "location": {
                "text": plan.location.text if plan.location else None,
                "bbox": list(plan.location.bbox) if plan.location and plan.location.bbox else None,
                "geometry": location_geometry,
                "provider": plan.location.provider if plan.location else None,
                "confidence": plan.location.confidence if plan.location else 0,
                "error_code": plan.location.error_code if plan.location else None,
                "retryable": plan.location.retryable if plan.location else False,
                "next_action": plan.location.next_action if plan.location else None,
                "status_code": plan.location.status_code if plan.location else None,
            },
            "layers": [
                {
                    "role": item.role,
                    "source_type": item.source_type,
                    "provider": item.provider,
                    "dataset_id": item.dataset_id,
                    "source_url": item.source_url,
                    "cache_path": item.cache_path,
                    "bbox": list(item.bbox),
                    "status": item.status,
                    "feature_count": item.feature_count,
                    "geometry_valid": item.geometry_valid,
                    "spatial_valid": item.spatial_valid,
                    "error_code": item.error_code,
                    "retryable": item.retryable,
                    "next_action": item.next_action,
                    "attempts": list(item.attempts),
                    "metadata": dict(item.metadata),
                }
                for item in plan.layers
            ],
            "issues": list(plan.issues),
        }

    def _run_trace_phase(
        self,
        *,
        event_type: str,
        phase: str,
        summary: str,
        input_data: Any,
        operation: Callable[[], Any],
        output_serializer: Optional[Callable[[Any], Any]] = None,
        on_started: Optional[Callable[[Any], None]] = None,
    ) -> Any:
        """Execute one agent phase and close its trace span exactly once."""
        try:
            from mapping.trace import (
                finish_trace_event,
                publish_trace_event,
                publish_trace_lifecycle,
                run_for_session,
                start_trace_event,
                trace_lifecycle_names,
            )

            run = run_for_session(getattr(self, "session_id", None))
        except Exception:
            run = None

        span = None
        if run:
            try:
                span = start_trace_event(
                    run=run,
                    event_type=event_type,
                    phase=phase,
                    actor="agent",
                    summary=summary,
                    input_data=input_data,
                )
                lifecycle = trace_lifecycle_names(event_type)
                if lifecycle:
                    publish_trace_lifecycle(span, lifecycle[0])
                else:
                    publish_trace_event(span)
                if on_started:
                    on_started(span)
            except Exception:
                span = None

        try:
            result = operation()
        except Exception as exc:
            if span is not None:
                try:
                    span = finish_trace_event(
                        span,
                        status="error",
                        error={
                            "error_code": getattr(exc, "error_code", "internal_error"),
                            "retryable": bool(getattr(exc, "retryable", False)),
                            "next_action": "inspect_trace",
                        },
                    )
                    lifecycle = trace_lifecycle_names(event_type)
                    if lifecycle:
                        publish_trace_lifecycle(span, lifecycle[1])
                    else:
                        publish_trace_event(span)
                except Exception:
                    pass
            raise

        if span is not None:
            try:
                output = output_serializer(result) if output_serializer else result
            except Exception as exc:
                try:
                    span = finish_trace_event(
                        span,
                        status="error",
                        error={
                            "error_code": "trace_serialization_error",
                            "retryable": False,
                            "next_action": "inspect_trace",
                            "message": str(exc),
                        },
                    )
                    lifecycle = trace_lifecycle_names(event_type)
                    if lifecycle:
                        publish_trace_lifecycle(span, lifecycle[1])
                    else:
                        publish_trace_event(span)
                except Exception:
                    pass
            else:
                try:
                    span = finish_trace_event(span, status="success", output_data=output)
                    lifecycle = trace_lifecycle_names(event_type)
                    if lifecycle:
                        publish_trace_lifecycle(span, lifecycle[1])
                    else:
                        publish_trace_event(span)
                except Exception:
                    # Trace persistence must never change the GIS result.
                    pass
        return result

    def _publish_intent_trace_child(self, parent_event_id: Optional[str], event: Dict[str, Any]) -> None:
        """Persist one recognition phase beneath the intent parent span."""
        if not parent_event_id:
            return
        try:
            from mapping.trace import (
                publish_trace_event,
                record_trace_event,
                run_for_session,
            )

            run = run_for_session(getattr(self, "session_id", None))
            if not run:
                return
            trace_event = record_trace_event(
                run=run,
                event_type=str(event.get("event_type") or "intent_validate"),
                phase="intent",
                actor="agent",
                status=str(event.get("status") or "success"),
                summary={
                    "intent_rule_parse": "规则解析",
                    "intent_llm_parse": "LLM 语义补全",
                    "intent_merge": "合并意图",
                    "intent_validate": "校验意图",
                }.get(str(event.get("event_type")), "识别阶段"),
                parent_event_id=parent_event_id,
                input_data=event.get("input_data") or {},
                output_data=event.get("output_data") or {},
                error=event.get("error"),
            )
            publish_trace_event(trace_event)
        except Exception:
            return

    def _execute_thinking_loop(self, user_request: str) -> Dict[str, Any]:
        """执行思考-行动-观察循环（使用OpenAI工具调用标准）"""
        thinking_steps = []
        iteration = 0

        system_prompt = self._get_thinking_system_prompt()
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_request)
        ]
        last_tool_error: Optional[Dict[str, Any]] = None
        tool_error_counts: Dict[str, int] = {}

        while iteration < self.max_iterations:
            iteration += 1
            if self.verbose:
                print(f"\n🔄 步骤 {iteration}")

            response = self._stream_llm_response(
                messages,
                phase="tool_selection",
                iteration=iteration,
            )
            messages.append(response)

            if not response.tool_calls:
                if self.verbose:
                    print("⚠️ 模型未执行工具，任务尚未完成")

                self.logger.warning("模型在没有工具调用的情况下结束，不能宣称地图完成。")
                thinking_steps.append({
                    "iteration": iteration,
                    "thought": response.content,
                    "action": "NO_TOOL_CALL",
                    "action_input": "",
                    "observation": "任务尚未完成：模型没有执行任何工具"
                })
                if last_tool_error:
                    return {
                        "success": False,
                        "message": "工具调用失败后模型未继续修正参数，任务尚未完成",
                        "output": response.content,
                        "thinking_steps": thinking_steps,
                        "error_code": last_tool_error["error_code"],
                        "retryable": last_tool_error["retryable"],
                        "next_action": last_tool_error["next_action"],
                    }
                return {
                    "success": False,
                    "message": "模型未执行地图工具，任务尚未完成",
                    "output": response.content,
                    "thinking_steps": thinking_steps,
                    "error_code": "agent_no_tool_call",
                    "retryable": True,
                    "next_action": "continue_tool_execution",
                }

            for tool_call in response.tool_calls:
                tool_name = tool_call["name"]
                tool_input = tool_call["args"]

                if self.verbose:
                    # 使用logger中的映射将工具名翻译成中文
                    from ..utils.logger import TOOL_NAME_MAP
                    chinese_tool_name = TOOL_NAME_MAP.get(tool_name, tool_name)
                    print(f"🛠️ {chinese_tool_name}")

                trace_span = None
                trace_owned_by_tool = bool(
                    getattr(self.tool_dict.get(tool_name), "owns_trace_span", False)
                )
                if not trace_owned_by_tool:
                    try:
                        from mapping.trace import (
                            finish_trace_event,
                            publish_trace_lifecycle,
                            run_for_session,
                            start_trace_event,
                        )

                        trace_run = run_for_session(getattr(self, "session_id", None))
                        if trace_run:
                            trace_span = start_trace_event(
                                run=trace_run,
                                event_type="tool_call",
                                phase="tool",
                                actor="agent",
                                summary=f"执行工具: {tool_name}",
                                input_data=tool_input,
                                attributes={"tool_name": tool_name, "iteration": iteration},
                            )
                            publish_trace_lifecycle(trace_span, "tool_started")
                    except Exception:
                        trace_span = None

                observation = self._execute_tool(tool_name, tool_input)
                observation_error = tool_observation_error(observation)
                if trace_span is not None:
                    try:
                        from mapping.trace import finish_trace_event, publish_trace_lifecycle

                        trace_span = finish_trace_event(
                            trace_span,
                            status="error" if observation_error else "success",
                            output_data={"observation": observation},
                            error=observation_error,
                        )
                        publish_trace_lifecycle(trace_span, "tool_finished")
                        from mapping.trace import publish_trace_event

                        publish_trace_event(trace_span)
                    except Exception:
                        pass
                self._publish_realtime_tool_event(
                    iteration=iteration,
                    tool_name=tool_name,
                    tool_input=tool_input,
                    observation=observation,
                )

                if self.verbose:
                    # 简化结果显示
                    if "成功" in observation or "✅" in observation:
                        print(f"✅ 成功")
                    elif "失败" in observation or "❌" in observation:
                        print(f"❌ 失败")
                    else:
                        print(f"📊 完成")

                messages.append(ToolMessage(content=observation, tool_call_id=tool_call["id"]))

                thinking_steps.append({
                    "iteration": iteration,
                    "thought": response.content,
                    "action": tool_name,
                    "action_input": json.dumps(tool_input, ensure_ascii=False),
                    "observation": observation
                })

                if observation_error:
                    error_code = str(observation_error["error_code"])
                    tool_error_counts[error_code] = tool_error_counts.get(error_code, 0) + 1
                    last_tool_error = observation_error
                    if tool_error_counts[error_code] >= 2:
                        return {
                            "success": False,
                            "message": "同一工具错误连续出现，已停止重复调用",
                            "output": observation,
                            "thinking_steps": thinking_steps,
                            "error_code": error_code,
                            "retryable": observation_error["retryable"],
                            "next_action": observation_error["next_action"],
                        }
                else:
                    last_tool_error = None

                if self._is_terminal_tool_success(tool_name, observation):
                    self.logger.debug(f"终止型工具已成功执行，结束任务: {tool_name}")
                    return {
                        "success": True,
                        "message": "地图创建完成",
                        "output": observation,
                        "thinking_steps": thinking_steps,
                        "terminal_tool": tool_name
                    }

        return {
            "success": False,
            "message": f"达到最大迭代次数 {self.max_iterations}",
            "output": "",
            "thinking_steps": thinking_steps
        }

    def _is_terminal_tool_success(self, tool_name: str, observation: str) -> bool:
        """Return True when a tool success means the current task is complete."""
        terminal_tools = {"visualize_generalization", "map_save"}
        if tool_name not in terminal_tools:
            return False

        text = str(observation or "").lower()
        failure_markers = ["失败", "error", "exception", "traceback", "❌", "鉂"]
        if any(marker in text for marker in failure_markers):
            return False

        success_markers = ["完成", "保存", "success", "✅", "鉁"]
        return any(marker in text for marker in success_markers)

    def _validate_config(self) -> None:
        """验证配置"""
        validation_result = Config.validate_api_keys()

        if not validation_result["openai"]:
            raise ValueError("未配置OpenAI API密钥，请设置OPENAI_API_KEY环境变量")

        # DALL·E功能已被移除，不再检查相关配置

    def _initialize_tools(self) -> Tuple[List, Optional[Any]]:
        """初始化所有GIS制图工具"""
        if self.use_unified_tools:
            all_tools = list(ALL_UNIFIED_TOOLS)
            self.logger.info(f"使用统一工具类，初始化了 {len(all_tools)} 个GIS制图工具")
        else:
            all_tools = list(ALL_UNIFIED_TOOLS)
            self.logger.info(f"初始化了 {len(all_tools)} 个GIS制图工具")

        # 过滤掉不需要的工具
        llm_tools = []
        for tool in all_tools:
            if tool.name != 'generate_symbol':  # 排除符号生成工具
                llm_tools.append(tool)

        return llm_tools, None  # 不再分离保存工具

    def _get_thinking_system_prompt(self) -> str:
        """获取思考型智能体的系统提示词（工具调用版）"""

        return """你是一位顶级的GIS制图专家，擅长使用工具逐步解决用户的地图制作需求。

                **核心规则:**
                1.  **严格遵循流程**: 对于传统制图任务，必须严格按照"初始化地图 -> 添加图层 -> 设置样式 -> 添加地图元素 -> 保存地图"的顺序进行操作。
                2.  **`init_map` 优先**: 传统制图任务的第一步**必须**是调用 `init_map` 工具来初始化地图设置。
                3.  **设置图层样式 (`style_layer`)**: 为每个图层精细地调整样式。
                    *   **关键规则**: 必须将一个图层的**所有**样式（如颜色、线宽、符号、大小等）合并到**一次** `style_layer` 调用中。
                    *   例如: 如果用户要求一个图层使用 "蓝色圆形符号，大小为8", 你必须这样调用: `style_layer(layer_name='...', color='blue', marker='o', size=8)`.
                    *   不要为同一个图层的不同样式多次调用 `style_layer`。
                4.  **添加地图元素**: **严格按照用户的明确要求**添加比例尺、指北针或文字说明。**不要**自行添加任何用户未请求的地图元素。图例是自动生成的，**不要**使用 `add_annotation` 手动创建图例说明。
                5.  **保存地图**: 当所有制图步骤完成后，**必须**调用 `map_save` 工具保存地图。用户可以指定保存参数（文件名、输出目录、分辨率、格式等），如果用户没有指定，使用默认参数。
                6.  **处理工具失败**: 工具返回的是 JSON `tool_result`。先读取 `error_code` 和 `next_action`：`validation_error` 调整参数后重试，`network_error` 仅在 `retryable=true` 时重试，`resource_not_found` 更换已验证资源，`render_error` 重试渲染，只有 `clarification_required` 或确实缺少用户决策时才询问用户。不要把工具错误原样当作最终答案，也不要要求用户提供内部参数。

                **路网综合任务特殊规则:**
                对于路网综合可视化任务，流程完全不同：
                1. 首次创建：先调用 `generalize_road_network` 工具执行路网综合，然后调用 `visualize_generalization` 工具生成对比图
                2. 参数调整：如果用户对结果不满意，使用 `modify_generalization_params` 工具调整参数（如算法、比例尺等），然后重新调用 `visualize_generalization`
                3. 添加比例尺/指北针：如果用户要求"添加比例尺"或"添加指北针"，**只需**调用 `add_scalebar` 或 `add_compass` 工具。这些工具会自动触发重新可视化并保存地图，**不需要**再调用 `visualize_generalization` 工具
                4. 删除比例尺/指北针：如果用户要求"删除比例尺"或"删除指北针"，**只需**调用 `remove_scalebar` 或 `remove_compass` 工具。这些工具会自动触发重新可视化并保存地图，**不需要**再调用 `visualize_generalization` 工具
                5. 任务完成！**不需要**调用 init_map、add_layer、map_save 等传统制图工具
                6. 路网综合任务会自动保存会话状态，支持多轮对话修改参数

                **结束任务:**
                当你判断所有制图步骤都已成功完成，并且地图已经保存后，请提供一个最终的总结。这个总结应该以 **"FINAL_ANSWER:"** 开头，并清晰地列出你完成的所有主要步骤和最终成果。
                例如:
                - 传统制图: "FINAL_ANSWER: 地图已成功创建并保存。1. 初始化地图，设置标题为'示例地图'。2. 添加了'cities.shp'和'rivers.shp'两个图层。3. 为'cities'图层设置了红色点状符号，为'rivers'图层设置了蓝色虚线。4. 添加了比例尺和指北针。5. 保存地图为'example_map.png'。"
                - 路网综合: "FINAL_ANSWER: 路网综合可视化已完成。1. 使用网眼密度算法执行路网综合，从1:500缩编到1:2000。2. 生成了综合前后的对比图。对比图已保存到outputs目录。"

                现在，请开始分析用户的请求并执行任务。
                """

    def _execute_tool(self, tool_name: str, tool_input: Dict[str, Any]) -> str:
        """执行指定的工具（工具调用版）"""
        try:
            if tool_name == "add_layer" and not self._explicit_data_files:
                tool_input = dict(tool_input)
                plan = getattr(self, "_semantic_data_plan", None)
                layer_name = tool_input.get("name", "")
                layer_role = plan.role_for_layer(layer_name) if plan else None
                planned_path = plan.path_for_layer(layer_name) if plan else None
                source_meta = (
                    getattr(plan, "source_metadata", {}).get(layer_role, {})
                    if plan and layer_role
                    else {}
                )
                planned_dataset_id = source_meta.get("dataset_id")
                if plan and (
                    not layer_role
                    or layer_role not in plan.requested_roles
                    or (not planned_path and not planned_dataset_id)
                ):
                    role = layer_role or "请求的"
                    return format_tool_result(
                        tool_failure(
                            f"{role}图层没有经过校验的数据源，已阻止使用默认文件。",
                            ValueError("数据源未经过校验"),
                        )
                    )
                if planned_dataset_id:
                    # Implicit requests must use the backend's registered
                    # Dataset. The cache path is provenance only and must not
                    # become an executable tool argument.
                    tool_input["dataset_id"] = str(planned_dataset_id)
                    tool_input["data_path"] = None
                    tool_input["data_source_meta"] = source_meta
                elif planned_path:
                    # Planner-only/legacy callers have no Dataset registry;
                    # retain their explicit compatibility path until migrated.
                    tool_input["data_path"] = planned_path
                    if source_meta:
                        tool_input["data_source_meta"] = source_meta
                elif self._default_data_file_path:
                    tool_input["data_path"] = self._default_data_file_path.as_posix()

                if plan and (planned_path or planned_dataset_id):
                    style = dict(tool_input.get("style") or {})
                    role = plan.role_for_layer(tool_input.get("name", ""))
                    semantic_defaults = {
                        "boundary": {
                            "facecolor": "#E2E8F0",
                            "edgecolor": "#334155",
                            "alpha": 0.45,
                            "linewidth": 1.2,
                        },
                        "road": {
                            "color": "#D97706",
                            "alpha": 0.9,
                            "linewidth": 1.4,
                        },
                        "river": {
                            "color": "#0284C7",
                            "alpha": 0.9,
                            "linewidth": 1.5,
                        },
                        "poi": {
                            "color": "#C2410C",
                            "alpha": 0.95,
                            "size": 90.0,
                            "marker": "o",
                            "edgecolor": "white",
                            "linewidth": 1.2,
                        },
                    }
                    for key, value in semantic_defaults.get(role, {}).items():
                        style.setdefault(key, value)
                    if role == "boundary" and plan.city_label_column:
                        style.setdefault("label_column", plan.city_label_column)
                    tool_input["style"] = style

            # 特殊处理init_map工具，自动注入计算好的范围
            if tool_name == "init_map" and self.auto_extent:
                # 如果用户没有指定extent或extent为空，使用自动计算的范围
                if "extent" not in tool_input or not tool_input["extent"]:
                    tool_input["extent"] = self.auto_extent
                    self.logger.info(
                                            "🎯 自动注入计算的地图范围: [%s]" % 
                                            ", ".join(f"{x:.4f}" for x in self.auto_extent)
                                        )
                # 如果extent是字符串格式，尝试解析为数值列表
                elif isinstance(tool_input.get("extent"), str):
                    try:
                        # 解析字符串格式的extent
                        extent_str = tool_input["extent"]
                        if extent_str.startswith("[") and extent_str.endswith("]"):
                            extent_str = extent_str[1:-1]  # 移除方括号
                        extent_values = [float(x.strip()) for x in extent_str.split(",")]
                        tool_input["extent"] = extent_values
                        self.logger.info(f"🔧 解析extent字符串为数值列表: {extent_values}")
                    except Exception as parse_error:
                        # 解析失败，使用自动计算的范围
                        tool_input["extent"] = self.auto_extent
                        self.logger.warning(f"⚠️ extent解析失败，使用自动计算范围: {parse_error}")

            if tool_name not in self.tool_dict:
                return format_tool_result(
                    tool_failure(
                        f"工具 '{tool_name}' 不存在。可用工具：{list(self.tool_dict.keys())}",
                        ValueError("工具不存在"),
                    )
                )

            tool = self.tool_dict[tool_name]
            tool_input = self._with_session_id(tool, tool_input)
            result = tool.invoke(tool_input)
            observation = str(result)
            if observation.startswith("❌") or observation.startswith("错误"):
                return format_tool_result(tool_failure(observation, ValueError(observation)))
            return observation

        except Exception as e:
            return format_tool_result(tool_failure(f"工具 '{tool_name}' 执行失败: {e}", e))

    def _intent_location_text(self, user_request: str) -> Optional[str]:
        """Return the already-recognized place, with a legacy helper fallback."""
        intent = getattr(self, "_current_intent", None)
        location = getattr(intent, "location", None)
        text = getattr(location, "text", None)
        if text:
            return str(text)
        return extract_location_query(user_request)

    def _add_remote_river_source(self, user_request: str, plan):
        """Fill a missing river role from a place-scoped remote source."""
        if "river" not in plan.requested_roles or plan.river_path:
            return plan
        boundary_path = plan.boundary_path
        location_query = self._intent_location_text(user_request)
        if not boundary_path or not location_query:
            return plan
        try:
            import geopandas as gpd

            boundary_file = resolve_data_path(boundary_path.removeprefix("data/"))
            bounds = gpd.read_file(boundary_file).total_bounds
            bbox = bounds.tolist() if hasattr(bounds, "tolist") else list(bounds)
            remote_path = fetch_remote_waterways(location_query, bbox)
        except Exception as exc:
            self._record_source_error("river", exc)
            self.logger.warning(f"远程河流数据准备失败: {exc}")
            return plan
        if not remote_path:
            self._record_source_error(
                "river",
                RemoteDataSourceError("远程河流没有返回数据", code="resource_not_found"),
            )
            return plan
        issues = tuple(issue for issue in plan.issues if "河流" not in issue)
        return replace(plan, river_path=str(remote_path), issues=issues)

    def _add_remote_road_source(self, user_request: str, plan):
        """Use OSM roads when the verified local catalog has no road layer."""
        if "road" not in plan.requested_roles or plan.road_path:
            return plan
        boundary_path = plan.boundary_path
        location_query = self._intent_location_text(user_request)
        if not boundary_path or not location_query:
            return plan
        try:
            import geopandas as gpd

            boundary_file = resolve_data_path(boundary_path.removeprefix("data/"))
            bbox = gpd.read_file(boundary_file).total_bounds.tolist()
            remote_path = fetch_remote_roads(location_query, bbox)
        except Exception as exc:
            self._record_source_error("road", exc)
            self.logger.warning(f"远程道路数据准备失败: {exc}")
            return plan
        if not remote_path:
            self._record_source_error(
                "road",
                RemoteDataSourceError("远程道路没有返回数据", code="resource_not_found"),
            )
            return plan
        issues = tuple(issue for issue in plan.issues if "道路" not in issue)
        return replace(plan, road_path=str(remote_path), issues=issues)

    def _add_remote_poi_source(self, user_request: str, plan):
        """Plan the first POI layer from OSM using the place boundary as bbox."""
        request = extract_remote_poi_request(user_request)
        if not request or not request.get("place") or plan.poi_path:
            return plan
        batch_place = extract_remote_poi_query(user_request)
        place = self._intent_location_text(user_request) or request["place"]
        boundary_path = plan.boundary_path
        if not boundary_path:
            return replace(
                plan,
                issues=tuple(dict.fromkeys((*plan.issues, "未找到可用的POI边界范围"))),
            )
        try:
            import geopandas as gpd

            boundary_file = resolve_data_path(boundary_path.removeprefix("data/"))
            bounds = gpd.read_file(boundary_file).total_bounds
            bbox = bounds.tolist() if hasattr(bounds, "tolist") else list(bounds)
            remote_path = (
                fetch_remote_named_poi(request["place"], category=request["category"])
                if batch_place is None
                else fetch_remote_pois(place, bbox, category=request["category"])
            )
        except Exception as exc:
            self._record_source_error("poi", exc)
            logger = getattr(self, "logger", None)
            if logger:
                logger.warning(f"远程{request['label']}数据准备失败: {exc}")
            return replace(
                plan,
                issues=tuple(dict.fromkeys((*plan.issues, f"未找到可用的{request['label']}数据"))),
            )
        if not remote_path:
            self._record_source_error(
                "poi",
                RemoteDataSourceError("远程POI没有返回数据", code="resource_not_found"),
            )
            return replace(
                plan,
                issues=tuple(dict.fromkeys((*plan.issues, f"未找到可用的{request['label']}数据"))),
            )
        return replace(
            plan,
            poi_path=str(remote_path).replace("\\", "/"),
            poi_category=request["category"],
            poi_label=request["label"],
            requested_roles=tuple(dict.fromkeys((*plan.requested_roles, "poi"))),
        )

    def _record_source_error(self, role: str, error: Exception) -> None:
        """Keep source failures structured instead of hiding them in logs."""
        errors = getattr(self, "_source_errors", None)
        if errors is None:
            self._source_errors = []
            errors = self._source_errors
        error_code = getattr(error, "error_code", None)
        if not error_code:
            error_code = "resource_not_found" if "没有返回" in str(error) else "internal_error"
        errors.append(
            {
                "role": role,
                "error_code": error_code,
                "retryable": bool(getattr(error, "retryable", False)),
                "next_action": (
                    "retry_remote_source"
                    if bool(getattr(error, "retryable", False))
                    else "inspect_source_plan"
                ),
                "message": str(error),
            }
        )

    @staticmethod
    def _intent_failure_response(recognition: Any) -> Dict[str, Any]:
        """Convert recognition issues into an execution-safe response."""
        issues = list(getattr(recognition, "issues", []) or [])
        first_issue = issues[0] if issues else None
        needs_clarification = recognition.status == "needs_clarification"
        message = (
            getattr(first_issue, "message", None)
            or "无法可靠识别该制图请求"
        )
        return {
            "success": False,
            "status": "needs_clarification" if needs_clarification else "failed",
            "message": message,
            "error": message,
            "error_code": getattr(first_issue, "code", None) or "intent_parse_failed",
            "clarification": {
                "missing_fields": list(getattr(recognition, "missing_fields", []) or []),
                "conflicts": list(getattr(recognition, "conflicts", []) or []),
                "next_action": getattr(first_issue, "next_action", None) or "ask_user",
            },
            "intent": (
                recognition.intent.model_dump(mode="json")
                if getattr(recognition, "intent", None) is not None
                else None
            ),
        }

    def _publish_realtime_tool_event(
        self,
        *,
        iteration: int,
        tool_name: str,
        tool_input: Dict[str, Any],
        observation: str,
    ) -> None:
        """Publish a lightweight vector preview event after each tool call."""
        try:
            from mapping.realtime import publish_agent_map_event
            from ..tools.unified_mapping_tools import get_unified_tools

            tools = get_unified_tools()
            map_state = tools.current_map_state
            publish_agent_map_event(
                session_id=getattr(self, "session_id", None),
                iteration=iteration,
                tool_name=tool_name,
                tool_input=tool_input,
                observation=observation,
                map_state=map_state,
                map_tools=tools,
            )
        except Exception as e:
            self.logger.warning(f"实时制图事件发布失败: {e}")

    def _stream_llm_response(self, messages: List[Any], *, phase: str, iteration: int) -> Any:
        """Stream one model turn and batch visible text events."""
        from mapping.trace import stream_llm_with_trace

        stream = getattr(self.llm, "stream", None)
        if not callable(stream):
            from mapping.trace import invoke_llm_with_trace

            return invoke_llm_with_trace(
                session_id=getattr(self, "session_id", None),
                invoke=self.llm.invoke,
                messages=messages,
                attributes={"model": getattr(self.llm, "model_name", None), "phase": phase},
            )

        from mapping.realtime import publish_assistant_stream_event

        session_id = getattr(self, "session_id", None)
        message_id = f"{session_id or 'session'}:assistant:{iteration}"
        self.last_assistant_message_id = message_id
        publish_assistant_stream_event(
            session_id=session_id,
            event_type="assistant_started",
            message_id=message_id,
            iteration=iteration,
        )
        buffer: List[str] = []
        sequence = 0
        last_published = time.monotonic()

        def flush() -> None:
            nonlocal sequence, last_published
            if not buffer:
                return
            sequence += 1
            content = "".join(buffer)
            buffer.clear()
            publish_assistant_stream_event(
                session_id=session_id,
                event_type="assistant_delta",
                message_id=message_id,
                delta_seq=sequence,
                content=content,
                iteration=iteration,
            )
            last_published = time.monotonic()

        def on_text(content: str) -> None:
            nonlocal last_published
            buffer.append(content)
            if len("".join(buffer)) >= 256 or time.monotonic() - last_published >= 0.05:
                flush()

        try:
            response = stream_llm_with_trace(
                session_id=session_id,
                stream=stream,
                messages=messages,
                attributes={"model": getattr(self.llm, "model_name", None), "phase": phase},
                on_text=on_text,
            )
            flush()
            final_content = (
                response.get("content", "")
                if isinstance(response, dict)
                else getattr(response, "content", "")
            )
            if isinstance(final_content, str):
                publish_assistant_stream_event(
                    session_id=session_id,
                    event_type="assistant_message",
                    message_id=message_id,
                    content=final_content,
                    iteration=iteration,
                )
            return response
        except Exception:
            flush()
            raise

    def _with_session_id(self, tool: Any, tool_input: Dict[str, Any]) -> Dict[str, Any]:
        """Inject session_id for tools that declare it."""
        session_id = getattr(self, "session_id", None)
        if not session_id or not isinstance(tool_input, dict):
            return tool_input

        args_schema = getattr(tool, "args_schema", None)
        fields = getattr(args_schema, "model_fields", None) or getattr(args_schema, "__fields__", {})
        if "session_id" not in fields:
            return tool_input

        if tool_input.get("session_id"):
            return tool_input

        tool_input = dict(tool_input)
        tool_input["session_id"] = session_id
        return tool_input

    def _calculate_auto_extent(
        self,
        data_directory: str = None,
        data_files: List[str] = None,
        margin_ratio: float = Config.HYPERPARAMETERS.AUTO_EXTENT_MARGIN_RATIO,
        verbose: bool = True
    ) -> Tuple[Optional[List[float]], Optional[str]]:
        """自动计算数据范围"""
        try:

            final_data_dir = resolve_data_path(data_directory)

            # if verbose:
            #     self.logger.info(f"📂 使用数据目录: {final_data_dir}")

            extent = None
            if data_files:
                if verbose:
                    self.logger.info(f"📁 使用指定的数据文件")
                extent = calculate_extent_from_files(
                    data_files=data_files,
                    data_dir=str(final_data_dir),
                    margin_ratio=margin_ratio,
                    verbose=verbose
                )

            if extent:
                extent_str = format_extent_for_request(extent)
                # if verbose:
                    # self.logger.info(f"✅ 自动计算范围成功: {extent_str}")
                return extent, extent_str
            else:
                return None, None

        except Exception as e:
            if verbose:
                self.logger.error(f"❌ 自动计算范围出错: {e}")
            return None, None

    def _enhance_request_with_auto_extent(self, user_request: str) -> str:
        """增强用户请求，添加自动计算的范围"""
        instructions = []
        if self.auto_extent_str:
            instructions.append("🎯 系统已自动计算最佳地图范围，在初始化地图时会自动使用。")
        if self._default_data_file_path and not self._explicit_data_files:
            instructions.append(
                f"📁 系统已解析出可用数据文件 {self._default_data_file_path.as_posix()}，添加图层时必须使用该文件，禁止猜测其他路径。"
            )
        plan = getattr(self, "_semantic_data_plan", None)
        if plan and not self._explicit_data_files:
            instructions.append(plan.prompt_instructions())
        if not instructions:
            return user_request

        if "extent=" in user_request.lower() or "范围" in user_request:
            instructions = [item for item in instructions if not item.startswith("🎯")]

        if not instructions:
            return user_request

        return f"{user_request}\n\n" + "\n".join(instructions)

    def _get_final_map_state(self) -> Optional[MapState]:
        """获取最终的地图状态

        优先级：
        1. 如果传统制图状态更新（ID不同），使用传统制图状态
        2. 如果路网综合状态存在且更新，使用路网综合状态
        3. 否则使用当前已有的状态
        """
        # 获取传统制图状态
        traditional_state = None
        try:
            from ..tools.unified_mapping_tools import get_unified_tools

            unified_tools = get_unified_tools()
            if unified_tools.current_map_state:
                traditional_state = unified_tools.current_map_state
        except Exception as e:
            self.logger.debug(f"获取传统制图状态失败: {e}")

        # 获取路网综合状态
        generalization_state = None
        try:
            session_context = get_generalization_context(
                getattr(self, "session_id", None),
                load_persisted=False,
            )
            if session_context and session_context.map_state is not None:
                generalization_state = session_context.map_state
        except Exception as e:
            self.logger.debug(f"获取路网综合状态失败: {e}")

        # 判断使用哪个状态
        # 如果传统制图状态存在且有图层，优先使用传统制图状态
        if traditional_state and len(traditional_state.layers) > 0:
            # 检查是否是新创建的状态（ID不同）
            if not self.current_map_state or id(traditional_state) != id(self.current_map_state):
                self.current_map_state = traditional_state
                # self.logger.info(f"从全局统一工具实例获取到地图状态，ID: {id(self.current_map_state)}, 图层数: {len(self.current_map_state.layers)}, 图层: {[l.name for l in self.current_map_state.layers]}")
                return self.current_map_state

        # 如果路网综合状态存在，使用路网综合状态
        if generalization_state:
            # 检查是否是新创建的状态（ID不同）
            if not self.current_map_state or id(generalization_state) != id(self.current_map_state):
                self.current_map_state = generalization_state
                self.logger.info(f"从会话路网综合状态获取到地图状态")
                return self.current_map_state

        # 如果都没有更新，返回当前状态
        return getattr(self, 'current_map_state', None)
