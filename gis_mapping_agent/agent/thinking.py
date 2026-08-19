"""思考型GIS制图智能体 - 实现显式的思考-行动-观察循环"""

from typing import Any, Dict, List, Optional, Tuple
import json


from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage

from ..models.schemas import MapState
from ..utils.config import Config
from ..utils.logger import setup_logger, get_logger
from ..utils.data_path_resolver import extract_data_info_from_request, resolve_data_path
from ..gis import calculate_extent_from_files, format_extent_for_request
from ..state import get_generalization_context
from ..tools.registry import ALL_UNIFIED_TOOLS


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
        self.llm = self.llm.bind_tools(self.tools)

        # 设置参数
        self.max_iterations = max_iterations
        self.verbose = verbose

        # 当前地图状态
        self.current_map_state: Optional[MapState] = None

        # self.logger.info("思考型GIS制图智能体初始化完成")

    def create_map(self, user_request: str) -> Dict[str, Any]:
        """使用思考-行动-观察循环创建地图"""

        try:
            self.logger.info(f"开始处理制图请求")

            # 从用户请求中提取数据目录和文件信息
            data_dir_from_request, data_files_from_request = extract_data_info_from_request(user_request)

            # 自动计算范围
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
                "map_state": final_map_state.model_dump() if final_map_state else None,
                "thinking_steps": result.get("thinking_steps", []),
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
                "error": str(e)
            }

    def _execute_thinking_loop(self, user_request: str) -> Dict[str, Any]:
        """执行思考-行动-观察循环（使用OpenAI工具调用标准）"""
        thinking_steps = []
        iteration = 0

        system_prompt = self._get_thinking_system_prompt()
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_request)
        ]

        while iteration < self.max_iterations:
            iteration += 1
            if self.verbose:
                print(f"\n🔄 步骤 {iteration}")

            response = self.llm.invoke(messages)
            messages.append(response)

            if not response.tool_calls:
                if self.verbose:
                    print("✅ 任务完成")

                self.logger.info("模型决定结束任务，没有工具调用。")
                thinking_steps.append({
                    "iteration": iteration,
                    "thought": response.content,
                    "action": "FINAL_ANSWER",
                    "action_input": "",
                    "observation": "任务完成"
                })
                return {
                    "success": True,
                    "message": "地图创建完成",
                    "output": response.content,
                    "thinking_steps": thinking_steps
                }

            for tool_call in response.tool_calls:
                tool_name = tool_call["name"]
                tool_input = tool_call["args"]

                if self.verbose:
                    # 使用logger中的映射将工具名翻译成中文
                    from ..utils.logger import TOOL_NAME_MAP
                    chinese_tool_name = TOOL_NAME_MAP.get(tool_name, tool_name)
                    print(f"🛠️ {chinese_tool_name}")

                observation = self._execute_tool(tool_name, tool_input)
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
                return f"错误：工具 '{tool_name}' 不存在。可用工具：{list(self.tool_dict.keys())}"

            tool = self.tool_dict[tool_name]
            tool_input = self._with_session_id(tool, tool_input)
            result = tool.invoke(tool_input)
            return str(result)

        except Exception as e:
            import traceback
            return f"工具 '{tool_name}' 执行失败: {e}\n{traceback.format_exc()}"

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

    def _with_session_id(self, tool: Any, tool_input: Dict[str, Any]) -> Dict[str, Any]:
        """Inject session_id for tools that declare it."""
        session_id = getattr(self, "session_id", None)
        if not session_id or not isinstance(tool_input, dict):
            return tool_input

        args_schema = getattr(tool, "args_schema", None)
        fields = getattr(args_schema, "model_fields", None) or getattr(args_schema, "__fields__", {})
        if "session_id" not in fields:
            return tool_input

        tool_input = dict(tool_input)
        if tool_input.get("session_id") and tool_input.get("session_id") != session_id:
            self.logger.warning(
                f"工具 {getattr(tool, 'name', '<unknown>')} 的 session_id 参数与当前会话不一致，已覆盖为当前会话"
            )
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
        if not self.auto_extent_str:
            return user_request

        if "extent=" in user_request.lower() or "范围" in user_request:
            self.logger.info("用户请求中已包含范围信息，不使用自动计算的范围")
            return user_request

        enhanced_request = f"""{user_request}

🎯 系统已自动计算最佳地图范围，在初始化地图时会自动使用。"""

        
        return enhanced_request

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
