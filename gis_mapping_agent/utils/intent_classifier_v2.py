"""意图识别器 V2 - 使用 Function Calling 替代复杂 Prompt"""

from typing import Dict, List, Optional, Any, Literal, Set
import json
from pathlib import Path
import re
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from pydantic import BaseModel, Field

from ..models.schemas import MapState, ModificationAction
from ..utils.config import Config
from ..utils.logger import get_logger
from ..utils.singleton import singleton


# ==================== Function Calling 参数定义 ====================

class BatchOperation(BaseModel):
    """批量操作中的单个操作"""
    type: str = Field(description="操作类型，如 remove_layer, add_layer, style_layer, remove_scalebar 等")
    layer_name: Optional[str] = Field(None, description="图层名称（如果适用）")
    source: Optional[str] = Field(None, description="数据源路径（添加图层时使用）")
    color: Optional[str] = Field(None, description="颜色")
    line_width: Optional[float] = Field(None, description="线宽")
    line_style: Optional[str] = Field(None, description="线型：solid, dashed, dotted")
    face_color: Optional[str] = Field(None, description="填充色（面图层）")
    edge_color: Optional[str] = Field(None, description="边框色（面图层）")
    marker_size: Optional[float] = Field(None, description="点大小")
    alpha: Optional[float] = Field(None, description="透明度 (0-1)")
    title: Optional[str] = Field(None, description="地图标题")
    background_color: Optional[str] = Field(None, description="背景色")
    text: Optional[str] = Field(None, description="注记文本")
    font_size: Optional[float] = Field(None, description="字体大小")
    position: Optional[List[float]] = Field(None, description="位置坐标 [x, y]")
    algorithm: Optional[str] = Field(None, description="路网综合算法")
    source_scale: Optional[float] = Field(None, description="源比例尺")
    target_scale: Optional[float] = Field(None, description="目标比例尺")
    retention_ratio: Optional[float] = Field(None, description="道路保留比例")
    keep_ratio: Optional[float] = Field(None, description="道路保留比例")


class IntentAnalysisV2(BaseModel):
    """意图分析结果（Function Calling 版本）"""
    request: str = Field(default="", description="用户原始请求")
    intent: Literal[
        "add_layer", "remove_layer", "style_layer", "reorder_layers",
        "update_map_config", "add_annotation", "remove_annotation", "update_annotation",
        "add_scalebar", "update_scalebar", "remove_scalebar",
        "add_compass", "update_compass", "remove_compass",
        "update_legend", "update_title", "update_extent", "update_generalization_params", "undo", "unknown"
    ] = Field(description="""识别的意图类型。

    重要：对于批量操作或顺序操作，请选择第一个主要操作作为 intent，
    然后将所有操作放入 batch_operations 列表中。

    例如：
    - "删除图层A，然后删除比例尺" → intent="remove_layer", batch_operations=[...]
    - "先删除图层，然后重新添加" → intent="remove_layer", batch_operations=[...]
    - "同时修改A和B图层" → intent="style_layer", batch_operations=[...]
    """)
    
    confidence: float = Field(default=0.8, description="置信度 (0-1)", ge=0.0, le=1.0)
    
    target: Optional[str] = Field(
        None,
        description="操作目标。单个操作时为图层名称等；批量操作时为 'multiple'"
    )
    
    # 单个操作的参数
    layer_name: Optional[str] = Field(None, description="图层名称")
    source: Optional[str] = Field(None, description="数据源路径")
    color: Optional[str] = Field(None, description="颜色")
    line_width: Optional[float] = Field(None, description="线宽")
    line_style: Optional[str] = Field(None, description="线型")
    face_color: Optional[str] = Field(None, description="填充色")
    edge_color: Optional[str] = Field(None, description="边框色")
    marker_size: Optional[float] = Field(None, description="点大小")
    alpha: Optional[float] = Field(None, description="透明度")
    title: Optional[str] = Field(None, description="地图标题")
    background_color: Optional[str] = Field(None, description="背景色")
    text: Optional[str] = Field(None, description="注记文本")
    font_size: Optional[float] = Field(None, description="字体大小")
    position: Optional[List[float]] = Field(None, description="位置坐标")
    algorithm: Optional[str] = Field(None, description="路网综合算法")
    source_scale: Optional[float] = Field(None, description="源比例尺")
    target_scale: Optional[float] = Field(None, description="目标比例尺")
    retention_ratio: Optional[float] = Field(None, description="道路保留比例")
    keep_ratio: Optional[float] = Field(None, description="道路保留比例")
    
    # 批量操作的参数
    batch_operations: Optional[List[BatchOperation]] = Field(
        None,
        description="批量操作列表。当用户请求包含多个操作时使用（如'同时修改A和B'、'先删除A然后添加B'）"
    )
    
    requires_confirmation: bool = Field(
        False,
        description="是否需要用户确认（删除操作通常需要确认）"
    )
    
    clarification_questions: List[str] = Field(
        default_factory=list,
        description="需要澄清的问题列表"
    )
    
    reasoning: str = Field(default="", description="推理过程说明")


class IntentClassifierV2:
    """意图识别器 V2 - 使用 Function Calling
    
    优势：
    1. 结构化输出，不需要复杂的 prompt 示例
    2. 参数类型自动验证
    3. 更容易维护和扩展
    4. 减少 token 消耗
    """
    
    def __init__(self, model_name: Optional[str] = None):
        """初始化意图识别器
        
        Args:
            model_name: 模型名称，默认使用配置中的模型
        """
        self.logger = get_logger("IntentClassifierV2")
        
        if model_name is None:
            model_name = Config.OPENAI_MODEL
        
        self.llm = ChatOpenAI(
            model=model_name,
            temperature=Config.HYPERPARAMETERS.INTENT_LLM_TEMPERATURE,
            openai_api_key=Config.OPENAI_API_KEY,
            openai_api_base=Config.OPENAI_BASE_URL,
            request_timeout=Config.HYPERPARAMETERS.INTENT_REQUEST_TIMEOUT_SECONDS
        )
        
        self.logger.info(f"意图识别器 V2 初始化完成，使用模型: {model_name}")
    
    def classify_intent(self, user_input: str, current_state: MapState) -> IntentAnalysisV2:
        """识别用户意图（使用 Function Calling）
        
        Args:
            user_input: 用户输入
            current_state: 当前地图状态
            
        Returns:
            IntentAnalysisV2: 意图分析结果
        """
        try:
            # 构建简洁的系统提示
            system_prompt = self._build_system_prompt(current_state)
            
            # 构建用户消息
            user_message = f"请分析以下用户请求，识别修改意图并提取参数：\n\n{user_input}"
            
            # 使用 Function Calling
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_message)
            ]
            
            # 绑定函数
            llm_with_tools = self.llm.bind_tools(
                [IntentAnalysisV2],
                tool_choice={"type": "function", "function": {"name": "IntentAnalysisV2"}}
            )

            self.logger.info("正在调用LLM进行意图识别...")
            try:
                response = llm_with_tools.invoke(messages)
                self.logger.info("LLM调用成功")
            except Exception as llm_error:
                self.logger.error(f"LLM调用失败: {llm_error}")
                raise
            
            # 解析 Function Calling 结果
            if response.tool_calls:
                tool_call = response.tool_calls[0]
                args = tool_call["args"]
                
                # 转换为 IntentAnalysisV2 对象
                result = IntentAnalysisV2(**args)
                result.request = user_input

                self.logger.info(f"意图识别完成: {result.intent}")
                return result
            else:
                # 如果没有 tool_calls，尝试从 content 解析
                self.logger.warning("未收到 tool_calls，尝试从 content 解析")
                return self._fallback_parse(response.content, user_input)
                
        except Exception as e:
            self.logger.error(f"意图识别失败: {e}")
            return IntentAnalysisV2(
                intent="unknown",
                confidence=0.0,
                requires_confirmation=False,
                clarification_questions=["系统错误，请重试"],
                reasoning=f"系统错误: {str(e)}"
            )
    
    def _build_system_prompt(self, current_state: MapState) -> str:
        """构建简洁的系统提示"""
        
        layer_info = "\n".join([f"  - {layer.name} ({layer.geometry_type.value})"
                               for layer in current_state.layers])
        
        return f"""你是 GIS 地图修改意图识别专家。分析用户请求，识别修改意图并提取参数。

                    当前地图状态：
                    - 标题: {current_state.config.title or '未设置'}
                    - 图层数量: {len(current_state.layers)}
                    - 现有图层:{layer_info}
                    - 比例尺: {'有' if current_state.scalebar else '无'}
                    - 指北针: {'有' if current_state.compass else '无'}

                    关键规则：
                    1. **批量操作**: 如果用户请求包含多个操作（"同时"、"一起"、"都"），使用 batch_operations
                    - intent 设置为第一个操作的类型
                    - target 设置为 "multiple"
                    - 所有操作放入 batch_operations 列表

                    2. **顺序操作**: 如果用户使用"先...然后..."、"然后"，也使用 batch_operations
                    - intent 设置为第一个操作的类型（如"先删除然后添加" → intent="remove_layer"）
                    - target 设置为 "multiple"
                    - 按顺序将所有操作放入 batch_operations 列表

                    示例：
                    - "先删除Highway图层，然后重新添加Highway.shp" →
                        intent="remove_layer", target="multiple",
                        batch_operations=[
                        {{type: "remove_layer", layer_name: "Highway"}},
                        {{type: "add_layer", layer_name: "Highway", source: "data1/Highway.shp", ...}}
                        ]

                    3. **背景色**: "地图背景色" → intent="update_map_config"
                    4. **图层样式**: "图层颜色" → intent="style_layer"
                    5. **确认策略**: 所有操作都不需要确认，requires_confirmation=false
                       - 删除图层(remove_layer): requires_confirmation=false
                       - 删除注记(remove_annotation): requires_confirmation=false
                       - 删除比例尺(remove_scalebar): requires_confirmation=false
                       - 删除指北针(remove_compass): requires_confirmation=false
                       - 其他所有操作: requires_confirmation=false
                    6. **参数提取**:
                    - Polygon图层: face_color(填充色), edge_color(边框色), line_width(边框宽)
                    - Line图层: color(颜色), line_width(线宽), line_style(线型)
                    - Point图层: color(颜色), marker_size(大小)
                    7. **数据源**: 从"使用XXX目录中的YYY.shp"提取 source="XXX/YYY.shp"

                    请使用 IntentAnalysisV2 函数返回结构化结果。"""

    @staticmethod
    def _normalize_layer_reference(value: Optional[str]) -> str:
        """标准化图层引用，兼容图层名、文件名、别名和空格符号差异。"""
        if not value:
            return ""
        text = str(value).strip()
        text = re.sub(r"\.(shp|geojson|json|gpkg)$", "", text, flags=re.IGNORECASE)
        text = re.sub(r"(图层|数据层|矢量层|layer)$", "", text, flags=re.IGNORECASE)
        return re.sub(r"[\s_\-./\\'\"“”‘’（）()【】\[\]{}:：,，;；。]+", "", text).lower()

    @staticmethod
    def _clean_layer_reference(value: str) -> str:
        """清理用户原文中包裹在图层名称周围的动作词。"""
        text = value.strip()
        text = re.sub(r"^(请|帮我|把|将|对|给|为|删除|移除|去掉|隐藏|显示|修改|调整|设置|更改|改变)+", "", text)
        text = re.sub(r"(图层|数据层|矢量层|layer)$", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\.(shp|geojson|json|gpkg)$", "", text, flags=re.IGNORECASE)
        return text.strip(" \t\r\n'\"“”‘’（）()【】[]{}:：,，;；。")

    def _build_layer_alias_index(self, current_state: MapState) -> Dict[str, str]:
        """基于当前地图状态构建 图层引用 -> 真实图层名 的索引。"""
        alias_index: Dict[str, str] = {}

        try:
            from ..tools.unified_mapping_tools.constants import LAYER_NAME_MAPPING
        except Exception:
            LAYER_NAME_MAPPING = {}

        def add_alias(alias: Optional[str], canonical_name: str) -> None:
            normalized = self._normalize_layer_reference(alias)
            if normalized:
                alias_index[normalized] = canonical_name

        for layer in current_state.layers:
            canonical_name = layer.name
            aliases: Set[str] = {canonical_name}

            if layer.data_source:
                try:
                    source_stem = Path(str(layer.data_source)).stem
                    if source_stem:
                        aliases.add(source_stem)
                except Exception:
                    pass

            normalized_aliases = {self._normalize_layer_reference(alias) for alias in aliases}
            for english_name, chinese_name in LAYER_NAME_MAPPING.items():
                normalized_english = self._normalize_layer_reference(english_name)
                normalized_chinese = self._normalize_layer_reference(chinese_name)
                if normalized_english in normalized_aliases or normalized_chinese in normalized_aliases:
                    aliases.add(english_name)
                    aliases.add(chinese_name)

            for alias in aliases:
                add_alias(alias, canonical_name)

        return alias_index

    def _extract_layer_references(self, request: str, alias_index: Dict[str, str]) -> List[str]:
        """从用户原文中抽取显式图层引用，不绑定具体业务名。"""
        references: List[str] = []

        def add_reference(value: str) -> None:
            cleaned = self._clean_layer_reference(value)
            normalized = self._normalize_layer_reference(cleaned)
            if cleaned and normalized and cleaned not in references:
                references.append(cleaned)

        file_pattern = r"([A-Za-z0-9_\- \u4e00-\u9fff]+?\.(?:shp|geojson|json|gpkg))"
        for match in re.findall(file_pattern, request, flags=re.IGNORECASE):
            add_reference(match)

        layer_patterns = [
            r"(?:请|帮我|把|将|对|给|为|删除|移除|去掉|隐藏|显示|修改|调整|设置|更改|改变)?\s*([A-Za-z0-9_\- \u4e00-\u9fff.]+?)\s*(?:图层|数据层|矢量层|layer)",
            r"(?:删除|移除|去掉|隐藏|显示|修改|调整|设置|更改|改变)\s+([A-Za-z0-9_\- \u4e00-\u9fff.]+?)(?:\s|$|颜色|线宽|透明度|样式)",
        ]
        for pattern in layer_patterns:
            for match in re.findall(pattern, request, flags=re.IGNORECASE):
                add_reference(match)

        normalized_request = self._normalize_layer_reference(request)
        for alias, canonical_name in alias_index.items():
            if len(alias) >= 2 and alias in normalized_request:
                add_reference(canonical_name)

        return references

    def _resolve_layer_reference(self, reference: Optional[str], alias_index: Dict[str, str]) -> Optional[str]:
        """将用户或 LLM 的图层引用解析为当前状态中的真实图层名。"""
        normalized = self._normalize_layer_reference(reference)
        if not normalized:
            return None
        return alias_index.get(normalized)

    def _validate_layer_targets_against_request(
        self,
        analysis: IntentAnalysisV2,
        current_state: MapState,
        layer_names: List[str],
    ) -> None:
        """校验用户原文目标与结构化目标一致，防止 LLM 把不存在图层替换成其他图层。"""
        alias_index = self._build_layer_alias_index(current_state)
        explicit_refs = self._extract_layer_references(analysis.request or "", alias_index)
        resolved_explicit_refs = [
            resolved for resolved in (self._resolve_layer_reference(ref, alias_index) for ref in explicit_refs)
            if resolved
        ]
        resolved_explicit_refs = list(dict.fromkeys(resolved_explicit_refs))
        layer_action_types = {
            "remove_layer", "style_layer", "toggle_layer_visibility",
            "hide_layer", "show_layer", "set_layer_visibility",
        }

        def add_missing_reference_question(reference: str) -> None:
            question = f"图层 '{reference}' 不存在。可用图层: {', '.join(layer_names)}"
            if question not in analysis.clarification_questions:
                analysis.clarification_questions.append(question)

        if explicit_refs and not resolved_explicit_refs:
            for reference in explicit_refs:
                add_missing_reference_question(reference)
            analysis.confidence *= 0.4
            return

        if analysis.target and analysis.target != "multiple":
            resolved_target = self._resolve_layer_reference(analysis.target, alias_index)
            if resolved_target:
                if resolved_explicit_refs and resolved_target not in resolved_explicit_refs:
                    analysis.clarification_questions.append(
                        f"请求中提到的图层为 {', '.join(explicit_refs)}，但解析目标为 '{analysis.target}'。请确认要修改的图层。"
                    )
                    analysis.confidence *= 0.4
                else:
                    analysis.target = resolved_target
            elif analysis.target not in layer_names:
                add_missing_reference_question(analysis.target)
                analysis.confidence *= 0.5
        elif analysis.target != "multiple" and len(resolved_explicit_refs) == 1:
            analysis.target = resolved_explicit_refs[0]

        if analysis.batch_operations:
            for operation in analysis.batch_operations:
                operation_type = operation.type or ""
                if operation_type not in layer_action_types or not operation.layer_name:
                    continue

                resolved_layer = self._resolve_layer_reference(operation.layer_name, alias_index)
                if resolved_layer:
                    if resolved_explicit_refs and resolved_layer not in resolved_explicit_refs:
                        analysis.clarification_questions.append(
                            f"请求中提到的图层为 {', '.join(explicit_refs)}，但批量操作包含额外目标 '{operation.layer_name}'。请确认要修改的图层。"
                        )
                        analysis.confidence *= 0.4
                        continue
                    operation.layer_name = resolved_layer
                    continue

                add_missing_reference_question(operation.layer_name)
                analysis.confidence *= 0.8
    
    def _fallback_parse(self, content: str, user_input: str) -> IntentAnalysisV2:
        """备用解析方法"""
        try:
            # 尝试从 content 中解析 JSON
            import json
            data = json.loads(content)
            result = IntentAnalysisV2(**data)
            result.request = user_input
            return result
        except:
            # 返回默认结果
            return IntentAnalysisV2(
                intent="unknown",
                confidence=0.0,
                requires_confirmation=False,
                clarification_questions=["无法理解您的请求，请提供更具体的描述"],
                reasoning="解析失败"
            )
    
    def validate_intent_with_state(
        self,
        analysis: IntentAnalysisV2,
        current_state: MapState
    ) -> IntentAnalysisV2:
        """验证意图与当前状态的兼容性
        
        Args:
            analysis: 意图分析结果
            current_state: 当前地图状态
            
        Returns:
            IntentAnalysisV2: 验证后的分析结果
        """
        try:
            # 验证目标图层是否存在
            if analysis.intent in ["remove_layer", "style_layer"]:
                layer_names = [layer.name for layer in current_state.layers]
                self._validate_layer_targets_against_request(analysis, current_state, layer_names)
            
            # ✅ 修改：移除删除操作的确认逻辑
            # 所有操作都不需要确认，直接执行
            if analysis.intent == "remove_layer":
                # 不再设置 requires_confirmation = True
                # 只在删除最后一个图层时添加提示信息（但不阻止执行）
                if len(current_state.layers) <= 1:
                    # 移除确认问题，改为日志记录
                    self.logger.warning("正在删除最后一个图层，地图将为空")
            
            return analysis
            
        except Exception as e:
            self.logger.error(f"验证意图失败: {e}")
            return analysis

@singleton
class _IntentClassifierV2Singleton:
    """意图识别器 V2 单例包装器"""
    def __init__(self):
        self.classifier = IntentClassifierV2()

def get_intent_classifier_v2() -> IntentClassifierV2:
    """获取意图识别器 V2 的全局单例

    Returns:
        IntentClassifierV2: 全局唯一的意图识别器实例

    Note:
        使用单例模式确保整个应用只有一个意图识别器实例
    """
    return _IntentClassifierV2Singleton().classifier
