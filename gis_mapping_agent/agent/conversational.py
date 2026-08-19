"""对话式GIS制图智能体 - 支持多轮对话和增量修改"""

from typing import Any, Dict, List, Optional, TypedDict, Annotated
import operator
import re
from datetime import datetime

from langchain_openai import ChatOpenAI
from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage, AIMessage
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode

from ..models.schemas import MapState, SessionInfo, MapVersion
from ..specs import GeneralizationSpec, MapSpec
from ..utils.config import Config
from ..utils.logger import setup_logger, get_logger
from ..state import (
    clear_session_context,
    get_generalization_context,
    get_map_state_context,
    get_session_context,
    get_state_manager,
    save_generalization_context,
    save_map_state_context,
)
from ..adjustment import get_modification_engine
from ..rendering.renderer import get_map_renderer
from ..tools.conversation_tools import CONVERSATION_TOOLS
from ..tools.registry import ALL_UNIFIED_TOOLS
from .thinking import ThinkingGISMappingAgent


class ConversationState(TypedDict):
    """对话状态模型"""
    messages: Annotated[List[BaseMessage], operator.add]
    current_map_state: Optional[MapState]
    session_id: Optional[str]
    user_intent: str  # "create" | "modify" | "query" | "undo" | "save" | "load"
    task_type: Optional[str]
    patch: Optional[Dict[str, Any]]
    tool_trace_id: Optional[str]
    render_result: Optional[Dict[str, Any]]
    error: Optional[str]
    requires_confirmation: bool
    clarification_questions: List[str]
    last_operation: Optional[str]
    conversation_history: List[Dict[str, Any]]


class ConversationalMappingAgent:
    """对话式GIS制图智能体
    
    支持多轮对话、增量修改、状态管理和版本控制
    """
    
    def __init__(
        self,
        model_name: Optional[str] = None,
        temperature: float = Config.HYPERPARAMETERS.LLM_TEMPERATURE,
        verbose: bool = True,
        session_id: Optional[str] = None
    ):
        """初始化对话式制图智能体"""
        
        # 设置日志
        setup_logger()
        self.logger = get_logger("ConversationalMappingAgent")
        
        # 初始化模型
        if model_name is None:
            model_name = Config.OPENAI_MODEL
            
        self.llm = ChatOpenAI(
            model=model_name,
            temperature=temperature,
            openai_api_key=Config.OPENAI_API_KEY,
            openai_api_base=Config.OPENAI_BASE_URL
        )
        
        self.verbose = verbose
        
        # 初始化组件
        self.state_manager = get_state_manager()
        self.modification_engine = get_modification_engine()
        self.map_renderer = get_map_renderer()
        
        # 初始化传统制图Agent（用于创建新地图）
        self.creation_agent = ThinkingGISMappingAgent(
            model_name=model_name,
            temperature=temperature,
            verbose=True,  # ✅ 启用详细日志输出，让用户看到完整的制图过程
            auto_calculate_extent=True
        )
        
        # 合并工具集
        all_tools = CONVERSATION_TOOLS + ALL_UNIFIED_TOOLS
        self.tools = {tool.name: tool for tool in all_tools}
        
        # 构建对话流程图
        self.workflow = self._build_workflow()
        self.app = self.workflow.compile()
        
        # 会话管理
        self.session_id = session_id
        self._last_chat_session_id_explicit = False
        self.current_state: Optional[ConversationState] = None
        
        self.logger.info("制图智能体初始化完成")
    
    def chat(self, user_input: str, session_id: Optional[str] = None) -> Dict[str, Any]:
        """处理用户输入，支持多轮对话
        
        Args:
            user_input: 用户输入
            session_id: 会话ID，如果不提供则使用当前会话或创建新会话
            
        Returns:
            Dict: 响应结果
        """
        try:
            # 管理会话
            previous_session_id = self.session_id
            self._last_chat_session_id_explicit = bool(session_id)
            if session_id:
                if session_id != previous_session_id:
                    self.current_state = None
                self.session_id = session_id
            elif not self.session_id:
                # 创建新会话
                session_info = SessionInfo()
                self.session_id = session_info.session_id
            get_session_context(self.session_id)
            
            is_new_map_request = self._looks_like_new_map_request(user_input)
            if is_new_map_request:
                try:
                    from gis_mapping_agent.tools.unified_mapping_tools.singleton import reset_unified_tools
                    reset_unified_tools()
                except Exception as e:
                    self.logger.warning(f"重置统一制图工具失败: {e}")
                clear_session_context(self.session_id)
                self.current_state = None

            # 初始化或更新对话状态
            if self.current_state is None:
                # New map requests must not hydrate old state from the same web session.
                load_existing = not is_new_map_request
                self.current_state = self._initialize_conversation_state(load_existing=load_existing)
                if self.current_state.get("current_map_state") is not None:
                    save_map_state_context(self.session_id, self.current_state["current_map_state"])
            
            # 添加用户消息
            # 限制消息历史长度，避免内存溢出
            if len(self.current_state["messages"]) > 20:
                # 保留最近的20条消息
                self.current_state["messages"] = self.current_state["messages"][-20:]

            self.current_state["messages"].append(HumanMessage(content=user_input))
            
            # 运行对话流程
            result = self.app.invoke(self.current_state)
            
            # 更新当前状态
            self.current_state = result
            
            # 提取响应
            last_message = result["messages"][-1]
            
            response = {
                "success": not bool(result.get("error")),
                "response": last_message.content if hasattr(last_message, 'content') else str(last_message),
                "session_id": self.session_id,
                "intent": result.get("user_intent", "unknown"),
                "task_type": result.get("task_type"),
                "patch": result.get("patch"),
                "tool_trace_id": result.get("tool_trace_id"),
                "render_result": result.get("render_result"),
                "error": result.get("error"),
                "requires_confirmation": result.get("requires_confirmation", False),
                "clarification_questions": result.get("clarification_questions", []),
                "current_map_state": result.get("current_map_state") is not None,
                "last_operation": result.get("last_operation")
            }
            
            # 如果有地图状态，添加相关信息
            if result.get("current_map_state"):
                map_state = result["current_map_state"]
                response["map_info"] = {
                    "version": map_state.get_current_version(),
                    "layer_count": len(map_state.layers),
                    "last_modified": map_state.updated_at
                }
            
            return response
            
        except Exception as e:
            self.logger.error(f"对话处理失败: {e}")
            import traceback
            self.logger.error(f"错误堆栈: {traceback.format_exc()}")
            return {
                "success": False,
                "error": str(e),
                "response": "抱歉，处理您的请求时出现了错误，请重试。",
                "session_id": self.session_id  # 确保返回session_id
            }
    
    def _build_workflow(self) -> StateGraph:
        """构建对话工作流"""
        workflow = StateGraph(ConversationState)
        
        # 添加节点
        workflow.add_node("classify_intent", self._classify_intent)
        workflow.add_node("create_map", self._create_map)
        workflow.add_node("generalize_network", self._generalize_network)
        workflow.add_node("visualize_generalization", self._visualize_generalization)
        workflow.add_node("modify_generalization", self._modify_generalization)
        workflow.add_node("modify_map", self._modify_map)
        workflow.add_node("handle_query", self._handle_query)
        workflow.add_node("handle_confirmation", self._handle_confirmation)
        workflow.add_node("handle_error", self._handle_error)
        workflow.add_node("generate_response", self._generate_response)
        
        # 设置入口点
        workflow.set_entry_point("classify_intent")
        
        # 添加条件边
        workflow.add_conditional_edges(
            "classify_intent",
            self._route_by_intent,
            {
                "create": "create_map",
                "generalization": "generalize_network",
                "visualize_generalization": "visualize_generalization",
                "modify_generalization": "modify_generalization",
                "modify": "modify_map",
                "query": "handle_query",
                "confirmation": "handle_confirmation",
                "response": "generate_response"
            }
        )
        
        for node in [
            "create_map",
            "generalize_network",
            "visualize_generalization",
            "modify_generalization",
            "modify_map",
            "handle_query",
            "handle_confirmation",
        ]:
            workflow.add_conditional_edges(
                node,
                self._route_after_task,
                {"error": "handle_error", "response": "generate_response"},
            )
        workflow.add_edge("handle_error", "generate_response")
        
        # 设置结束点
        workflow.add_edge("generate_response", END)
        
        return workflow
    
    def _initialize_conversation_state(self, load_existing: bool = True) -> ConversationState:
        """初始化对话状态

        Args:
            load_existing: 是否尝试加载现有会话状态，默认True
        """
        # 只有在明确要求加载现有状态时才尝试加载
        map_state = None
        if load_existing and self.session_id:
            map_state = self.state_manager.load_state(self.session_id)

        return ConversationState(
            messages=[],
            current_map_state=map_state,
            session_id=self.session_id,
            user_intent="unknown",
            task_type=None,
            patch=None,
            tool_trace_id=None,
            render_result=None,
            error=None,
            requires_confirmation=False,
            clarification_questions=[],
            last_operation=None,
            conversation_history=[]
        )

    def _looks_like_new_map_request(self, user_input: str) -> bool:
        """Return True only for complete new-map creation requests.

        This is intentionally stricter than intent classification. It runs before
        LangGraph has classified the request, so it should only clear state when
        the user provides strong creation signals such as data files, a data
        directory, or a complete layer/style specification.
        """
        text = (user_input or "").lower()
        create_words = [
            "创建", "制作", "生成", "新建", "绘制", "出图", "成图", "制图",
            "create", "make", "generate", "draw",
        ]
        map_output_phrases = [
            "生成地图", "制作地图", "创建地图", "绘制地图", "专题地图", "交通网络图",
        ]
        style_spec_phrases = [
            "图层样式要求", "图层样式", "样式要求", "符号", "矢量图层",
        ]

        data_file_count = len(re.findall(r"\.(?:shp|geojson|json|gpkg)\b", text, flags=re.IGNORECASE))
        has_data_dir = bool(re.search(r"(?:data\d+|数据目录|目录中的数据|目录中)", text, flags=re.IGNORECASE))
        has_create_word = any(word in text for word in create_words)
        has_map_output = any(phrase in text for phrase in map_output_phrases)
        has_layer_style_spec = any(phrase in text for phrase in style_spec_phrases)

        if data_file_count >= 2:
            return True
        return (has_create_word or has_map_output) and (data_file_count > 0 or has_data_dir or has_layer_style_spec)
    
    def _classify_intent(self, state: ConversationState) -> ConversationState:
        """分类用户意图：优先使用 LLM，失败或返回异常时使用规则兜底。"""
        try:
            last_message = state["messages"][-1]
            user_input = last_message.content
            state["patch"] = None
            state["render_result"] = None
            state["error"] = None

            # 检查是否是确认回复
            if state.get("requires_confirmation", False):
                if any(word in user_input.lower() for word in ["是", "确定", "好的", "可以", "yes"]):
                    state["user_intent"] = "confirmation"
                    state["task_type"] = "confirmation"
                    state["requires_confirmation"] = False
                    return state
                elif any(word in user_input.lower() for word in ["否", "不", "取消", "no"]):
                    state["user_intent"] = "cancel"
                    state["task_type"] = "cancel"
                    state["requires_confirmation"] = False
                    return state

            has_map_state = state.get("current_map_state") is not None

            # 构建系统提示
            system_prompt = f"""你是一个GIS制图系统的意图分类器。你需要判断用户的请求是以下哪种类型：

                                1. **create** - 创建新地图
                                - 用户想要创建一个全新的地图
                                - 包含完整的制图要求（数据目录、多个数据文件、图层样式、地图标题、背景色等）
                                - 即使当前已有地图，只要用户是在描述一张新地图的完整数据和样式要求，也应判断为 create
                                - 图层颜色、符号、透明度、线宽等样式要求可以是新建地图的一部分，不要仅因为出现这些词就判断为 modify
                                - 例如："使用data5目录中的数据生成地图：Wuhan.shp、Skating Rink.shp，并设置图层样式"
                                - 例如："请创建广东省地图"、"使用以下数据文件制作地图：...地图标题：...背景色：..."

                                2. **modify** - 修改现有地图
                                - 用户想要修改、调整、删除、添加现有地图的元素
                                - 通常会引用"当前地图"、"已有图层"、"刚才的图"、"删除/隐藏某个图层"、"把某个图层改成..."等
                                - 例如："删除Railway图层"、"把Highway颜色改成红色"、"隐藏当前地图中的Racecourse"
                                - 如果用户只是补充一句"添加一个图层到当前地图"，而不是描述一张新地图，判断为 modify

                                3. **query** - 查询信息
                                - 用户想要查看地图状态、图层信息等
                                - 例如："显示当前地图状态"、"查看图层列表"

                                当前状态：
                                - 是否已有地图：{"是" if has_map_state else "否"}
                                {f"- 当前图层数：{len(state['current_map_state'].layers)}" if has_map_state else ""}

                                判断规则：
                                1. 如果用户明确说"创建"、"制作"、"生成"新地图，或提供了数据目录/多个数据文件/完整图层样式要求，判断为 create
                                2. 如果已有地图，且用户明确针对现有地图做删除、隐藏、修改、局部添加，判断为 modify
                                3. 如果请求同时包含"生成地图"和"图层样式要求"，优先判断为 create
                                4. 如果用户说"查看"、"显示"、"列出"等，判断为query

                                请只返回以下之一：create、modify、query"""

            # 调用大模型
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=f"用户输入：{user_input}\n\n请判断意图类型（只返回：create、modify或query）：")
            ]

            response = self.llm.invoke(messages)
            intent = response.content.strip().lower()

            # 验证返回的意图
            if intent in ["create", "modify", "query"]:
                state["user_intent"] = intent
                state["task_type"] = intent
                self.logger.info(f"大模型意图分类: {intent}")
            else:
                # 如果大模型返回了其他内容，使用默认规则作为后备
                self.logger.warning(f"大模型返回了意外的意图: {intent}，使用后备规则")
                state["user_intent"] = self._fallback_intent_classification(user_input, has_map_state)
                state["task_type"] = state["user_intent"]

            return state

        except Exception as e:
            self.logger.error(f"意图分类失败: {e}，使用后备规则")
            # 使用简单规则作为后备
            has_map_state = state.get("current_map_state") is not None
            state["user_intent"] = self._fallback_intent_classification(last_message.content, has_map_state)
            state["task_type"] = state["user_intent"]
            state["error"] = str(e)
            return state

    def _rule_intent_classification(self, user_input: str, has_map_state: bool) -> Optional[str]:
        """规则兜底分类；LLM 不可用或返回异常时使用。"""
        text = user_input.lower()

        query_words = [
            "查看", "显示", "列出", "查询", "状态", "信息", "图层列表", "当前地图",
            "show", "list", "query", "status", "info",
        ]
        create_words = [
            "创建", "制作", "生成", "新建", "绘制", "出图", "成图",
            "create", "make", "generate", "draw",
        ]
        modify_words = [
            "修改", "改变", "调整", "更新", "删除", "移除", "添加", "隐藏", "显示图层",
            "颜色", "线宽", "透明度", "标题", "比例", "retention_ratio", "target_scale",
            "modify", "change", "update", "delete", "remove", "add", "hide", "style",
        ]
        existing_map_markers = [
            "当前地图", "现有地图", "已有地图", "当前图", "这张图", "刚才", "上一张",
            "当前图层", "已有图层", "现有图层", "结果图",
        ]
        local_modify_words = [
            "删除", "移除", "去掉", "隐藏", "显示图层", "撤销", "回退",
            "修改", "改变", "更新", "把", "将",
            "delete", "remove", "hide", "modify", "change", "update",
        ]

        data_file_count = len(re.findall(r"\.(?:shp|geojson|json|gpkg)\b", text, flags=re.IGNORECASE))
        has_create_word = any(word in text for word in create_words)
        complete_create_request = self._looks_like_new_map_request(user_input)
        explicit_existing_modify = has_map_state and any(word in text for word in existing_map_markers) and any(word in text for word in local_modify_words)

        if any(word in text for word in query_words):
            return "query"
        if complete_create_request:
            return "create"
        if explicit_existing_modify:
            return "modify"
        if any(word in text for word in create_words):
            return "create"
        if has_map_state and any(word in text for word in modify_words):
            return "modify"
        return None

    def _fallback_intent_classification(self, user_input: str, has_map_state: bool) -> str:
        """后备的简单意图分类"""
        intent = self._rule_intent_classification(user_input, has_map_state)
        if intent:
            return intent
        # 默认：有地图状态则为修改，否则为创建
        return "modify" if has_map_state else "create"

    def _mark_graph_step(self, state: ConversationState, task_type: str, operation: Optional[str] = None) -> None:
        """Record lightweight graph-level execution metadata."""
        state["task_type"] = task_type
        if operation:
            state["last_operation"] = operation
        state["tool_trace_id"] = f"{self.session_id}:{operation or task_type}"
    
    def _route_by_intent(self, state: ConversationState) -> str:
        """根据意图路由"""
        intent = state.get("user_intent", "response")
        last_message = state["messages"][-1] if state.get("messages") else None
        user_input = last_message.content.lower() if last_message and hasattr(last_message, "content") else ""
        current_map_state = state.get("current_map_state")

        if intent == "query" and current_map_state and getattr(current_map_state, "is_generalization_task", False):
            if any(word in user_input for word in ["对比图", "可视化", "查看结果", "重新可视化", "结果图"]):
                state["task_type"] = "visualize_generalization"
                return "visualize_generalization"
        if intent == "modify" and current_map_state and getattr(current_map_state, "is_generalization_task", False):
            state["task_type"] = "modify_generalization"
            return "modify_generalization"
        if intent == "create" and any(word in user_input for word in ["路网综合", "缩编", "generalization", "综合参数"]):
            state["task_type"] = "generalization"
            return "generalization"
        
        if intent in ["create"]:
            return "create"
        elif intent in ["modify"]:
            return "modify"
        elif intent in ["query"]:
            return "query"
        elif intent in ["confirmation", "cancel"]:
            return "confirmation"
        else:
            return "response"

    def _route_after_task(self, state: ConversationState) -> str:
        render_result = state.get("render_result")
        if state.get("error") or (render_result and not render_result.get("success", False)):
            return "error"
        return "response"

    def _handle_error(self, state: ConversationState) -> ConversationState:
        self._mark_graph_step(state, state.get("task_type") or "error", "handle_error")
        error = state.get("error") or (state.get("render_result") or {}).get("error") or "unknown error"

        if self._is_data_path_error(error):
            state["requires_confirmation"] = False
            state["clarification_questions"] = ["请确认数据文件路径是否存在，并重新提供有效的 Shapefile/GeoJSON 路径。"]
            state["messages"].append(AIMessage(content=f"数据路径不可用：{error}\n\n请重新提供有效的数据文件路径。"))
            return state

        render_result = state.get("render_result")
        if render_result and not render_result.get("success", False):
            current_map_state = state.get("current_map_state")
            if current_map_state:
                retry_result = self.map_renderer.render_map(current_map_state)
                state["render_result"] = retry_result
                if retry_result.get("success"):
                    state["error"] = None
                    state["messages"].append(AIMessage(content="地图状态已保存，渲染失败后已自动重试并成功生成输出。"))
                    return state

            reason = render_result.get("error") or render_result.get("message") or error
            state["messages"].append(AIMessage(content=f"地图状态已保存，但渲染失败：{reason}"))
            return state

        state["messages"].append(AIMessage(content=f"任务执行失败：{error}"))
        return state

    @staticmethod
    def _is_data_path_error(error: str) -> bool:
        text = str(error).lower()
        return any(token in text for token in ["no such file", "not found", "路径", "文件", "不存在", ".shp", "shapefile", "geojson", "data_path"])

    def _generalize_network(self, state: ConversationState) -> ConversationState:
        """路网综合入口，复用现有创建链路。"""
        self._mark_graph_step(state, "generalization", "generalize_network")
        result = self._create_map(state)
        if result.get("current_map_state") and getattr(result["current_map_state"], "is_generalization_task", False):
            result["last_operation"] = "generalize_network"
            result["tool_trace_id"] = f"{self.session_id}:generalize_network"
        return result

    def _visualize_generalization(self, state: ConversationState) -> ConversationState:
        """可视化路网综合结果。"""
        try:
            self._mark_graph_step(state, "visualize_generalization", "visualize_generalization")
            current_map_state = state.get("current_map_state")
            if not current_map_state or not getattr(current_map_state, "is_generalization_task", False):
                state["messages"].append(AIMessage(content="当前没有可视化的路网综合结果。"))
                return state

            tool = self.tools.get("visualize_generalization")
            if tool is None:
                state["messages"].append(AIMessage(content="未找到 visualize_generalization 工具。"))
                return state

            result = tool.invoke({"session_id": self.session_id})
            state["render_result"] = {"success": True, "result": str(result)[:500]}
            session_context = get_generalization_context(self.session_id)
            updated_state = session_context.map_state if session_context and session_context.map_state else current_map_state
            state["current_map_state"] = updated_state
            state["messages"].append(AIMessage(content=result if isinstance(result, str) else str(result)))
            return state
        except Exception as e:
            self.logger.error(f"可视化路网综合结果失败: {e}")
            state["error"] = str(e)
            state["render_result"] = {"success": False, "error": str(e)}
            state["messages"].append(AIMessage(content=f"可视化路网综合结果时出现错误：{str(e)}"))
            return state

    def _modify_generalization(self, state: ConversationState) -> ConversationState:
        """路网综合修改入口。"""
        current_map_state = state.get("current_map_state")
        if not current_map_state:
            state["messages"].append(AIMessage(content="没有可修改的路网综合任务。"))
            return state
        last_message = state["messages"][-1]
        return self._modify_generalization_task(state, last_message.content, current_map_state)

    def _build_map_spec(self, user_request: str, state: ConversationState) -> MapSpec:
        current_map_state = state.get("current_map_state")
        if not current_map_state:
            return MapSpec()
        config = getattr(current_map_state, "config", None)
        return MapSpec(
            title=getattr(config, "title", None),
            extent=getattr(config, "extent", None),
            crs=getattr(config, "crs", None),
            background_color=getattr(config, "background_color", "white"),
            data_files=[layer.name for layer in getattr(current_map_state, "layers", [])],
        )

    def _build_generalization_spec(self, state: ConversationState) -> Optional[GeneralizationSpec]:
        current_map_state = state.get("current_map_state")
        if not current_map_state or not getattr(current_map_state, "generalization_params", None):
            return None
        params = current_map_state.generalization_params
        return GeneralizationSpec(
            data_file=params.get("data_file", ""),
            data_directory=params.get("data_directory"),
            algorithm=params.get("algorithm", "stroke"),
            source_scale=params.get("source_scale", 500),
            target_scale=params.get("target_scale", 2000),
            keep_ratio=params.get("keep_ratio"),
            input_path=getattr(current_map_state, "generalization_input_path", None),
            output_path=getattr(current_map_state, "generalization_output_path", None),
            params=dict(params),
        )

    def _create_map(self, state: ConversationState) -> ConversationState:
        """创建新地图"""
        try:
            last_message = state["messages"][-1]
            user_request = last_message.content
            previous_map_state = state.get("current_map_state")
            is_generalization_create = state.get("task_type") == "generalization"
            is_new_map_create = state.get("user_intent") == "create" and not is_generalization_create
            if is_new_map_create:
                state["current_map_state"] = None

            # 保留外部传入的会话ID（如 web_session_{request_id}），避免创建后修改时读不到状态。
            # 本地连续创建新地图时仍开新会话，维持原有隔离行为。
            import uuid
            old_session_id = self.session_id
            external_session = bool(getattr(self, "_last_chat_session_id_explicit", False))
            requested_session_id = state.get("session_id") if external_session else None
            if requested_session_id:
                self.session_id = requested_session_id
            elif state.get("current_map_state") is not None or not self.session_id:
                self.session_id = str(uuid.uuid4())
            state["session_id"] = self.session_id
            self._mark_graph_step(state, state.get("task_type") or "create", "create_map")

            if state.get("current_map_state") is not None:
                if old_session_id and old_session_id != self.session_id:
                    self.logger.info(f"检测到创建新地图请求，从会话 {old_session_id[:8]}... 切换到会话: {self.session_id[:8]}...")
                else:
                    self.logger.info(f"检测到创建新地图请求，复用会话: {self.session_id[:8]}...")
            else:
                self.logger.info(f"开始新会话: {self.session_id[:8]}...")

            # ✅ 清除全局的UnifiedMappingTools实例，避免状态污染
            from gis_mapping_agent.tools.unified_mapping_tools.singleton import reset_unified_tools
            reset_unified_tools()
            # self.logger.info("已重置全局统一工具实例（singleton）")

            # ✅ 清除ThinkingGISMappingAgent的当前地图状态
            self.creation_agent.current_map_state = None
            # self.logger.info("已清除ThinkingAgent的当前地图状态")

            if is_new_map_create:
                clear_session_context(self.session_id)
            elif old_session_id and old_session_id != self.session_id:
                clear_session_context(old_session_id)

            # 使用传统制图Agent创建地图
            self.creation_agent.session_id = self.session_id
            map_spec = MapSpec() if is_new_map_create else self._build_map_spec(user_request, state)
            create_request = user_request
            spec_payload = map_spec.model_dump(exclude_none=True, exclude_defaults=True)
            if spec_payload:
                create_request = "\n\n".join([
                    f"MapSpec: {spec_payload}",
                    user_request,
                ])
            result = self.creation_agent.create_map(create_request)

            if result["success"]:
                # 获取创建的地图状态
                map_state = self.creation_agent.current_map_state

                if not map_state and is_new_map_create:
                    try:
                        from ..tools.unified_mapping_tools import get_unified_tools

                        unified_tools = get_unified_tools()
                        if unified_tools.current_map_state and unified_tools.current_map_state.layers:
                            map_state = unified_tools.current_map_state
                            self.creation_agent.current_map_state = map_state
                            self.logger.info("从统一制图工具获取到本次创建的地图状态")
                    except Exception as e:
                        self.logger.error(f"从统一制图工具获取地图状态失败: {e}")

                # 优先使用本次创建结果，不允许新建地图失败后回退到旧会话状态。
                if not map_state and result.get("map_state"):
                    try:
                        from ..models.schemas import MapState
                        map_state = MapState.model_validate(result["map_state"])
                    except Exception as e:
                        self.logger.error(f"从结果中恢复地图状态失败: {e}")

                allow_existing_state_fallback = not is_new_map_create
                if allow_existing_state_fallback:
                    session_context = get_generalization_context(self.session_id)
                    if not map_state and session_context and session_context.map_state is not None:
                        map_state = session_context.map_state
                        self.logger.info("从SessionContext获取到地图状态")

                    if not map_state:
                        map_state = get_map_state_context(self.session_id)
                        if map_state:
                            self.logger.info("从持久化状态获取到地图状态")

                if map_state:
                    # 检查是否已经有会话信息（路网综合任务已经设置了）
                    if not hasattr(map_state.session_info, 'session_id') or not map_state.session_info.session_id:
                        # 创建新的MapState实例，包含会话信息
                        from ..models.schemas import SessionInfo, MapVersion

                        # 设置会话信息
                        session_info = SessionInfo(
                            session_id=self.session_id,
                            session_name=f"地图会话_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                        )

                        # 设置版本信息
                        version_info = MapVersion(
                            version=1,
                            description="初始地图创建"
                        )

                        # 更新地图状态
                        map_state.session_info = session_info
                        map_state.version_info = version_info
                        map_state.modification_history = []

                    # 确保会话ID一致
                    map_state.session_info.session_id = self.session_id
                    if map_state.is_generalization_task:
                        save_generalization_context(
                            self.session_id,
                            map_state=map_state,
                            generalization_result=map_state.generalization_result,
                            generalization_params=map_state.generalization_params,
                        )
                    else:
                        save_map_state_context(self.session_id, map_state)

                    render_result = None
                    if not map_state.is_generalization_task and not map_state.output_path:
                        render_result = self.map_renderer.render_map(map_state)
                        state["render_result"] = render_result
                        if render_result.get("success"):
                            map_state.output_path = render_result.get("file_path")
                            save_map_state_context(self.session_id, map_state)
                            self.logger.info(f"创建地图后已强制保存渲染结果: {map_state.output_path}")
                        else:
                            state["error"] = render_result.get("error") or render_result.get("message") or "地图保存失败"
                            response = f"❌ 地图创建失败：{state['error']}"
                            state["messages"].append(AIMessage(content=response))
                            return state

                    # 保存状态（检查是否已经保存过，避免重复保存）
                    # 对于路网综合任务，可视化工具已经保存过了
                    if not map_state.is_generalization_task:
                        self.state_manager.save_state(map_state)
                    # else:
                        # 路网综合任务已在可视化工具中保存，这里只需要确保状态同步
                        # self.logger.info(f"路网综合任务状态已在可视化工具中保存，跳过重复保存")

                    # 更新对话状态
                    state["current_map_state"] = map_state
                    state["last_operation"] = "create_map"

                    # 根据任务类型生成不同的响应
                    if map_state.is_generalization_task:
                        # 路网综合任务
                        params = map_state.generalization_params
                        response = f"✅ 路网综合任务创建成功！\n\n📊 综合信息：\n- 算法：{params.get('algorithm', '未知')}\n- 比例尺：1:{params.get('source_scale')} → 1:{params.get('target_scale')}\n- 会话ID：{self.session_id[:8]}...\n- 版本：v{map_state.get_current_version()}\n\n您现在可以对综合结果进行调整，比如：\n- 修改综合算法\n- 调整目标比例尺\n- 修改保留比例"
                    else:
                        # 传统制图任务
                        response = f"✅ 地图创建成功！\n\n📊 地图信息：\n- 图层数量：{len(map_state.layers)}\n- 版本：v{map_state.get_current_version()}\n\n您现在可以对地图进行修改，比如：\n- 修改图层颜色\n- 添加或删除图层\n- 调整地图标题\n- 添加注记说明"
                else:
                    state["error"] = "创建流程没有生成新的地图状态，未保存旧地图为新结果。"
                    response = f"❌ 地图创建失败：{state['error']}"
            else:
                state["error"] = result.get("message", "未知错误")
                response = f"❌ 地图创建失败：{state['error']}"
            
            state["messages"].append(AIMessage(content=response))
            return state
            
        except Exception as e:
            self.logger.error(f"创建地图失败: {e}")
            state["error"] = str(e)
            state["messages"].append(AIMessage(content=f"创建地图时出现错误：{str(e)}"))
            return state

    def _modify_map(self, state: ConversationState) -> ConversationState:
        """修改地图"""
        try:
            if not state.get("current_map_state"):
                state["messages"].append(AIMessage(content="没有可修改的地图，请先创建地图。"))
                return state

            self._mark_graph_step(state, state.get("task_type") or "modify", "modify_map")
            last_message = state["messages"][-1]
            user_request = last_message.content
            current_map_state = state["current_map_state"]

            # 检查是否为路网综合任务
            if current_map_state.is_generalization_task:
                # 路网综合任务的修改逻辑
                return self._modify_generalization_task(state, user_request, current_map_state)

            # 传统制图任务的修改逻辑
            # 分析修改请求
            analysis = self.modification_engine.analyze_modification_request(
                user_request,
                state["current_map_state"]
            )

            # ✅ 修改：移除确认逻辑，所有修改操作直接执行
            # 强制跳过确认
            analysis.requires_confirmation = False

            # 检查是否需要澄清
            if analysis.clarification_questions:
                questions = analysis.clarification_questions
                response = f"❓ 需要澄清以下信息：\n" + "\n".join(f"- {q}" for q in questions)
                state["messages"].append(AIMessage(content=response))
                return state

            # 生成修改计划
            patch = self.modification_engine.generate_modification_plan(analysis)
            state["patch"] = patch.model_dump()

            if not patch.operations:
                response = f"❌ 无法理解修改请求：{user_request}\n\n请提供更具体的描述，例如：\n- 修改Highway图层颜色为红色\n- 删除Railway图层\n- 添加注记'这是广东省地图'"
                state["messages"].append(AIMessage(content=response))
                return state

            self.state_manager.save_state(state["current_map_state"])
            before_state = state["current_map_state"]

            # 应用修改
            modification_result = self.modification_engine.apply_modifications(
                before_state,
                patch,
                user_request
            )
            new_state, records = modification_result

            # 保存新状态
            self.state_manager.save_state(new_state)
            save_map_state_context(self.session_id, new_state)

            # 渲染新地图
            render_result = self.map_renderer.render_map(new_state)
            state["render_result"] = render_result
            if render_result.get("success"):
                modification_result.diff = self.modification_engine.diff_states(before_state, new_state)
                self.state_manager.save_state(new_state)

            # 更新对话状态
            state["current_map_state"] = new_state
            state["last_operation"] = "modify_map"

            # 生成响应
            modifications_summary = "\n".join(f"- {record.description}" for record in records)
            response = f"✅ 修改应用成功！\n\n执行的修改：\n{modifications_summary}\n\n"

            if render_result.get("success"):
                # 显示相对路径而不是绝对路径
                file_path = render_result.get('file_path', '输出目录')
                if file_path != '输出目录':
                    from pathlib import Path
                    from ..utils.config import Config
                    try:
                        rel_path = Path(file_path).relative_to(Config.PROJECT_ROOT)
                        display_path = str(rel_path)
                    except (ValueError, Exception):
                        display_path = file_path
                else:
                    display_path = file_path
                # response += f"📁 地图已更新并保存到：{display_path}"
            else:
                response += "⚠️ 地图渲染失败，但修改已保存"

            state["messages"].append(AIMessage(content=response))
            return state

        except Exception as e:
            self.logger.error(f"修改地图失败: {e}")
            state["error"] = str(e)
            state["messages"].append(AIMessage(content=f"修改地图时出现错误：{str(e)}"))
            return state

    def _modify_generalization_task(self, state: ConversationState, user_request: str, current_map_state) -> ConversationState:
        """Modify road generalization task."""
        try:
            self._mark_graph_step(state, "modify_generalization", "modify_generalization")
            self.logger.info("开始处理路网综合调整请求")

            save_generalization_context(
                self.session_id,
                map_state=current_map_state,
                generalization_result=current_map_state.generalization_result,
                generalization_params=current_map_state.generalization_params,
            )

            generalization_spec = self._build_generalization_spec(state)
            if generalization_spec is None:
                state["messages"].append(AIMessage(content="未找到可复用的路网综合参数，请先执行一次路网综合。"))
                return state

            self.creation_agent.session_id = self.session_id
            enhanced_request = "\n\n".join([
                f"GeneralizationSpec: {generalization_spec.model_dump(exclude_none=True)}",
                user_request,
            ])
            result = self.creation_agent.create_map(enhanced_request)

            if result["success"]:
                session_context = get_generalization_context(self.session_id)
                updated_state = session_context.map_state if session_context and session_context.map_state else None

                if updated_state:
                    updated_state.session_info.session_id = self.session_id
                    save_generalization_context(
                        self.session_id,
                        map_state=updated_state,
                        generalization_result=updated_state.generalization_result,
                        generalization_params=updated_state.generalization_params,
                    )
                    state["current_map_state"] = updated_state
                    state["last_operation"] = "modify_generalization"

                    params = updated_state.generalization_params or {}
                    response = (
                        "路网综合结果已更新。\n\n"
                        f"- 算法：{params.get('algorithm', '未知')}\n"
                        f"- 比例尺：1:{params.get('source_scale')} 到 1:{params.get('target_scale')}\n"
                        f"- 版本：v{updated_state.get_current_version()}\n\n"
                        f"{result.get('output', '')}"
                    )
                else:
                    response = "调整已执行，但未能读取更新后的地图状态。"
            else:
                state["error"] = result.get("message", "未知错误")
                response = f"调整失败：{state['error']}"

            state["messages"].append(AIMessage(content=response))
            return state

        except Exception as e:
            self.logger.error(f"路网综合调整失败: {e}")
            import traceback
            traceback.print_exc()
            state["error"] = str(e)
            state["messages"].append(AIMessage(content=f"路网综合调整出错：{str(e)}"))
            return state

    def _handle_query(self, state: ConversationState) -> ConversationState:
        """处理查询请求"""
        try:
            self._mark_graph_step(state, state.get("task_type") or "query", "handle_query")
            last_message = state["messages"][-1]
            user_input = last_message.content.lower()

            if "状态" in user_input or "信息" in user_input:
                if state.get("current_map_state"):
                    map_state = state["current_map_state"]
                    response = f"""📊 当前地图状态：

                        🆔 会话ID：{map_state.get_session_id()[:8]}...
                        📝 会话名称：{map_state.session_info.session_name or '未命名'}
                        🔢 当前版本：v{map_state.get_current_version()}
                        📅 最后修改：{map_state.updated_at or '未知'}

                        📋 图层信息：
                        {chr(10).join(f"- {layer.name} ({layer.geometry_type.value})" for layer in map_state.layers)}

                        📝 注记数量：{len(map_state.annotations)}
                        📏 比例尺：{'已添加' if map_state.scalebar else '未添加'}
                        🧭 指北针：{'已添加' if map_state.compass else '未添加'}"""
                else:
                    response = "当前没有活动的地图会话。"

            elif "历史" in user_input or "版本" in user_input:
                if state.get("current_map_state"):
                    session_id = state["current_map_state"].get_session_id()
                    versions = self.state_manager.list_versions(session_id)

                    if versions:
                        version_list = "\n".join(
                            f"- v{v['version']}: {v.get('description', '无描述')} ({v.get('created_at', '未知时间')})"
                            for v in versions
                        )
                        response = f"📚 版本历史：\n{version_list}"
                    else:
                        response = "没有找到版本历史。"
                else:
                    response = "当前没有活动的地图会话。"

            else:
                response = """❓ 我可以帮您查询以下信息：

                            - 地图状态和信息
                            - 版本历史
                            - 会话列表

                            请告诉我您想了解什么？"""

            state["messages"].append(AIMessage(content=response))
            return state

        except Exception as e:
            self.logger.error(f"处理查询失败: {e}")
            state["error"] = str(e)
            state["messages"].append(AIMessage(content=f"查询时出现错误：{str(e)}"))
            return state

    def _handle_confirmation(self, state: ConversationState) -> ConversationState:
        """处理确认回复"""
        try:
            self._mark_graph_step(state, state.get("task_type") or "confirmation", "handle_confirmation")
            last_message = state["messages"][-1]
            user_input = last_message.content.lower()

            if state.get("user_intent") == "confirmation":
                # 用户确认，执行之前被阻止的操作
                self.logger.debug("用户确认，继续执行修改操作")
                response = "✅ 已确认，正在执行操作..."
                state["messages"].append(AIMessage(content=response))

                # 重新执行修改操作
                # 获取之前的用户请求（倒数第三条消息应该是原始请求）
                original_request = None
                for msg in reversed(state["messages"][:-2]):  # 排除当前确认消息和系统确认询问
                    if hasattr(msg, 'content') and isinstance(msg, HumanMessage):
                        original_request = msg.content
                        break

                if original_request and state.get("current_map_state"):
                    # 重新分析并执行修改
                    analysis = self.modification_engine.analyze_modification_request(
                        original_request,
                        state["current_map_state"]
                    )

                    # 强制跳过确认（因为用户已经确认了）
                    analysis.requires_confirmation = False

                    # 生成修改计划
                    patch = self.modification_engine.generate_modification_plan(analysis)
                    state["patch"] = patch.model_dump()

                    if patch.operations:
                        self.state_manager.save_state(state["current_map_state"])
                        before_state = state["current_map_state"]
                        # 应用修改
                        modification_result = self.modification_engine.apply_modifications(
                            before_state,
                            patch,
                            original_request
                        )
                        new_state, records = modification_result

                        # 保存新状态
                        self.state_manager.save_state(new_state)
                        save_map_state_context(self.session_id, new_state)

                        # 渲染新地图
                        render_result = self.map_renderer.render_map(new_state)
                        state["render_result"] = render_result
                        if render_result.get("success"):
                            modification_result.diff = self.modification_engine.diff_states(before_state, new_state)
                            self.state_manager.save_state(new_state)

                        # 更新对话状态
                        state["current_map_state"] = new_state
                        state["last_operation"] = "confirmed_modify"

                        # 生成成功响应
                        modifications_summary = "\n".join(f"- {record.description}" for record in records)
                        success_response = f"✅ 修改执行成功！"

                        if render_result.get("success"):
                            # 显示相对路径而不是绝对路径
                            file_path = render_result.get('file_path', '输出目录')
                            if file_path != '输出目录':
                                from pathlib import Path
                                from ..utils.config import Config
                                try:
                                    rel_path = Path(file_path).relative_to(Config.PROJECT_ROOT)
                                    display_path = str(rel_path)
                                except (ValueError, Exception):
                                    display_path = file_path
                            else:
                                display_path = file_path
                            # success_response += f"📁 地图已更新并保存到：{display_path}"
                        else:
                            success_response += "⚠️ 地图渲染失败，但修改已保存"

                        state["messages"].append(AIMessage(content=success_response))
                    else:
                        state["messages"].append(AIMessage(content="❌ 无法生成修改计划"))
                else:
                    state["messages"].append(AIMessage(content="❌ 无法找到原始请求或地图状态"))
            else:
                # 用户取消
                self.logger.debug("用户取消修改操作")
                response = "❌ 操作已取消。"
                state["messages"].append(AIMessage(content=response))

            return state

        except Exception as e:
            self.logger.error(f"处理确认失败: {e}")
            state["error"] = str(e)
            error_response = f"处理确认时出现错误：{str(e)}"
            state["messages"].append(AIMessage(content=error_response))
            return state

    def _generate_response(self, state: ConversationState) -> ConversationState:
        """生成最终响应"""
        # 如果已经有响应消息，直接返回
        if state["messages"] and isinstance(state["messages"][-1], AIMessage):
            return state

        # 否则生成默认响应
        response = "我理解了您的请求。有什么其他需要帮助的吗？"
        state["messages"].append(AIMessage(content=response))
        return state
