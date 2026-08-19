"""增量修改引擎 - 负责解析和执行地图修改操作"""

from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime
import copy
import json
import time

from ..models.schemas import (
    MapState, ModificationAction, ModificationRecord,
    LayerConfig, AnnotationConfig, MapConfig
)
from ..utils.logger import get_logger
from ..utils.intent_classifier_v2 import get_intent_classifier_v2, IntentAnalysisV2
from ..utils.singleton import singleton
from ..state import get_session_context
from ..state import record_tool_trace
from ..specs.adjustment_patch import AdjustmentPatch, PatchOperation


ACTION_LABELS = {
    "add_layer": "添加图层",
    "remove_layer": "删除图层",
    "style_layer": "修改图层样式",
    "reorder_layers": "调整图层顺序",
    "update_map_config": "更新地图配置",
    "add_annotation": "添加注记",
    "remove_annotation": "删除注记",
    "update_annotation": "修改注记",
    "add_scalebar": "添加比例尺",
    "update_scalebar": "更新比例尺",
    "add_compass": "添加指北针",
    "update_compass": "更新指北针",
    "update_legend": "更新图例",
    "remove_compass": "删除指北针",
    "remove_scalebar": "删除比例尺",
    "toggle_layer_visibility": "切换图层显示状态",
    "update_generalization_params": "更新路网综合参数",
}


def _action_label(action: Any) -> str:
    value = getattr(action, "value", action)
    return ACTION_LABELS.get(str(value), str(value))


class ModificationResult(tuple):
    def __new__(cls, state, records, patch=None, diff=None, before_version=None, after_version=None):
        obj = super().__new__(cls, (state, records))
        obj.state = state
        obj.records = records
        obj.patch = patch
        obj.diff = diff or {}
        obj.before_version = before_version
        obj.after_version = after_version
        return obj


class ModificationEngine:
    """增量修改引擎
    
    负责解析用户的修改请求，生成修改计划，并执行增量修改
    """
    
    def __init__(self):
        self.logger = get_logger("ModificationEngine")
    
    def analyze_modification_request(self, request: str, current_state: MapState) -> IntentAnalysisV2:
        """分析修改请求（使用AI意图识别）

        Args:
            request: 用户的修改请求
            current_state: 当前地图状态

        Returns:
            Dict: 分析结果，包含修改意图和参数
        """
        try:
            # 使用 V2 意图识别器
            intent_classifier = get_intent_classifier_v2()
            analysis_result = intent_classifier.classify_intent(request, current_state)

            # 验证意图与状态的兼容性
            validated_result = intent_classifier.validate_intent_with_state(analysis_result, current_state)

            validated_result.request = request

            return validated_result

        except Exception as e:
            self.logger.error(f"AI意图识别失败，使用备用方法: {e}")
            # 如果AI识别失败，使用备用的规则方法
            return self._fallback_analyze_request(request, current_state)
    
    def generate_modification_plan(self, analysis: IntentAnalysisV2) -> AdjustmentPatch:
        """Generate the standard dynamic adjustment patch from IntentAnalysisV2."""
        operations: List[PatchOperation] = []
        intent = analysis.intent

        parameter_fields = [
            "layer_name", "source", "color", "line_width", "line_style",
            "face_color", "edge_color", "marker_size", "alpha",
            "title", "background_color", "text", "font_size", "position",
            "algorithm", "source_scale", "target_scale", "retention_ratio", "keep_ratio",
        ]

        def action_value(action: Any) -> str:
            return action.value if hasattr(action, "value") else str(action)

        def add_operation(action: Any, target: str, params: Optional[Dict[str, Any]] = None, description: str = "") -> None:
            operations.append(
                PatchOperation(
                    action=action_value(action),
                    target=str(target or ""),
                    parameters=dict(params or {}),
                    description=description,
                )
            )

        def compact_model(model: Any, excluded: Optional[List[str]] = None) -> Dict[str, Any]:
            excluded_set = set(excluded or [])
            if hasattr(model, "model_dump"):
                raw = model.model_dump()
            else:
                raw = dict(model or {})
            return {k: v for k, v in raw.items() if k not in excluded_set and v is not None}

        def single_parameters() -> Dict[str, Any]:
            return {field: getattr(analysis, field) for field in parameter_fields if getattr(analysis, field, None) is not None}

        batch_operations = analysis.batch_operations or []
        parameters = single_parameters()
        target = analysis.target or ""

        if intent == "add_layer":
            if batch_operations:
                for operation in batch_operations:
                    operation_type = operation.type or ""
                    if operation_type == "add_layer":
                        add_operation(
                            ModificationAction.ADD_LAYER,
                            operation.layer_name or "",
                            compact_model(operation, ["type", "layer_name"]),
                        )
                    elif operation_type == "style_layer":
                        add_operation(
                            ModificationAction.STYLE_LAYER,
                            operation.layer_name or "",
                            compact_model(operation, ["type", "layer_name"]),
                        )
            else:
                add_operation(ModificationAction.ADD_LAYER, target or "new_layer", parameters)

        elif intent == "remove_layer":
            if batch_operations:
                for operation in batch_operations:
                    operation_type = operation.type or ""
                    if operation_type == "remove_layer":
                        add_operation(ModificationAction.REMOVE_LAYER, operation.layer_name or "")
                    elif operation_type == "remove_scalebar":
                        add_operation(ModificationAction.REMOVE_SCALEBAR, "scalebar")
                    elif operation_type == "remove_compass":
                        add_operation(ModificationAction.REMOVE_COMPASS, "compass")
                    elif operation_type == "add_layer":
                        add_operation(
                            ModificationAction.ADD_LAYER,
                            operation.layer_name or "",
                            compact_model(operation, ["type", "layer_name"]),
                        )
            else:
                add_operation(ModificationAction.REMOVE_LAYER, target, parameters)

        elif intent == "style_layer":
            if batch_operations:
                for operation in batch_operations:
                    operation_type = operation.type or ""
                    if operation_type == "update_map_config":
                        add_operation(
                            ModificationAction.UPDATE_MAP_CONFIG,
                            "background",
                            {"background_color": operation.background_color or "white"},
                        )
                    elif operation_type == "style_layer":
                        add_operation(
                            ModificationAction.STYLE_LAYER,
                            operation.layer_name or "",
                            compact_model(operation, ["type", "layer_name"]),
                        )
                    else:
                        layer_name = operation.layer_name or ""
                        if layer_name == "background":
                            add_operation(
                                ModificationAction.UPDATE_MAP_CONFIG,
                                "background",
                                {"background_color": operation.background_color or "white"},
                            )
                        else:
                            add_operation(
                                ModificationAction.STYLE_LAYER,
                                layer_name,
                                compact_model(operation, ["layer_name"]),
                            )
            else:
                add_operation(ModificationAction.STYLE_LAYER, target, parameters)

        elif intent == "add_annotation":
            add_operation(ModificationAction.ADD_ANNOTATION, "annotation", parameters)

        elif intent == "remove_annotation":
            add_operation(ModificationAction.REMOVE_ANNOTATION, target, parameters)

        elif intent in {"update_annotation", "modify_annotation"}:
            add_operation(ModificationAction.UPDATE_ANNOTATION, target, parameters)

        elif intent == "add_compass":
            if batch_operations:
                for operation in batch_operations:
                    operation_type = operation.type or ""
                    if operation_type == "add_compass":
                        add_operation(ModificationAction.ADD_COMPASS, "compass", compact_model(operation, ["type"]))
                    elif operation_type == "add_scalebar":
                        add_operation(ModificationAction.ADD_SCALEBAR, "scalebar", compact_model(operation, ["type"]))
            else:
                add_operation(ModificationAction.ADD_COMPASS, "compass", parameters)

        elif intent == "add_scalebar":
            if batch_operations:
                for operation in batch_operations:
                    operation_type = operation.type or ""
                    if operation_type == "add_compass":
                        add_operation(ModificationAction.ADD_COMPASS, "compass", compact_model(operation, ["type"]))
                    elif operation_type == "add_scalebar":
                        add_operation(ModificationAction.ADD_SCALEBAR, "scalebar", compact_model(operation, ["type"]))
            else:
                add_operation(ModificationAction.ADD_SCALEBAR, "scalebar", parameters)

        elif intent == "update_title":
            add_operation(ModificationAction.UPDATE_MAP_CONFIG, "title", parameters)

        elif intent == "update_extent":
            add_operation(ModificationAction.UPDATE_MAP_CONFIG, "extent", parameters)

        elif intent == "update_map_config":
            if batch_operations:
                for operation in batch_operations:
                    operation_type = operation.type or ""
                    operation_params = compact_model(operation, ["type", "target"])
                    if operation.title is not None:
                        add_operation(ModificationAction.UPDATE_MAP_CONFIG, "title", {"title": operation.title})
                    elif operation.background_color is not None:
                        add_operation(ModificationAction.UPDATE_MAP_CONFIG, "background", {"background_color": operation.background_color})
                    elif operation_type == "style_layer":
                        add_operation(
                            ModificationAction.STYLE_LAYER,
                            operation.layer_name or "",
                            compact_model(operation, ["type", "layer_name"]),
                        )
                    else:
                        add_operation(ModificationAction.UPDATE_MAP_CONFIG, "config", operation_params)
            else:
                config_target = target or "config"
                if "title" in parameters:
                    config_target = "title"
                add_operation(ModificationAction.UPDATE_MAP_CONFIG, config_target, parameters)

        elif intent == "remove_compass":
            if batch_operations:
                for operation in batch_operations:
                    operation_type = operation.type or ""
                    if operation_type == "remove_compass":
                        add_operation(ModificationAction.REMOVE_COMPASS, "compass")
                    elif operation_type == "remove_scalebar":
                        add_operation(ModificationAction.REMOVE_SCALEBAR, "scalebar")
            else:
                add_operation(ModificationAction.REMOVE_COMPASS, "compass", parameters)

        elif intent == "remove_scalebar":
            if batch_operations:
                for operation in batch_operations:
                    operation_type = operation.type or ""
                    if operation_type == "remove_compass":
                        add_operation(ModificationAction.REMOVE_COMPASS, "compass")
                    elif operation_type == "remove_scalebar":
                        add_operation(ModificationAction.REMOVE_SCALEBAR, "scalebar")
            else:
                add_operation(ModificationAction.REMOVE_SCALEBAR, "scalebar", parameters)

        elif intent == "update_generalization_params":
            add_operation(ModificationAction.UPDATE_GENERALIZATION_PARAMS, "generalization", parameters)

        patch = AdjustmentPatch(
            operations=operations,
            reason=getattr(analysis, "request", "") or None,
        ).normalized()

        self.logger.info(f"已生成修改计划，共 {len(patch.operations)} 个步骤")
        for i, operation in enumerate(patch.operations):
            self.logger.debug(f"步骤 {i + 1}: {_action_label(operation.action)} -> {operation.target}")
        return patch

    def apply_modifications(self, map_state: MapState, patch: AdjustmentPatch,
                          user_request: str) -> Tuple[MapState, List[ModificationRecord]]:
        """Apply a standard AdjustmentPatch to a MapState."""
        start_time = time.time()
        context = get_session_context(map_state.get_session_id(), create=False)
        if not isinstance(patch, AdjustmentPatch):
            raise TypeError("apply_modifications() requires an AdjustmentPatch instance")

        patch = patch.normalized()
        operations = patch.operations
        before_state = copy.deepcopy(map_state)
        before_version = map_state.get_current_version()
        self.logger.info(f"开始应用修改计划，共 {len(operations)} 个步骤")
        self.logger.debug(f"修改计划详情: {patch.model_dump()}")
        for i, operation in enumerate(operations):
            self.logger.debug(f"步骤 {i + 1}: {_action_label(operation.action)} -> {operation.target}")

        new_state = copy.deepcopy(map_state)
        modification_records = []

        for i, operation in enumerate(operations):
            try:
                self.logger.info(f"执行修改步骤 {i + 1}/{len(operations)}: {_action_label(operation.action)}")
                record = self._apply_single_modification(new_state, operation, user_request)
                if record:
                    modification_records.append(record)
                    new_state.add_modification_record(record)
                    self.logger.info(f"修改步骤完成: {record.description}")
                else:
                    self.logger.warning(f"修改步骤 {i + 1} 未生成修改记录")

            except Exception as e:
                self.logger.error(f"修改步骤 {i + 1} 执行失败: {e}")
                record_tool_trace(
                    session_id=map_state.get_session_id(),
                    task_id=getattr(context, "task_id", None),
                    tool_name="apply_modifications",
                    args={"user_request": user_request, "patch": patch.model_dump()},
                    result_summary={"failed_operation": i + 1},
                    success=False,
                    error=str(e),
                    duration_ms=int((time.time() - start_time) * 1000),
                )
                raise

        if modification_records:
            main_record = modification_records[0]
            diff = self.diff_states(before_state, new_state)
            description = json.dumps({
                "user_request": user_request,
                "patch": patch.model_dump(),
                "diff": diff,
                "before_version": before_version,
                "output_path": new_state.output_path or new_state.generalization_output_path,
            }, ensure_ascii=False, default=str)
            new_state.create_new_version(main_record, description)
            self.logger.info(f"已创建地图新版本: v{new_state.get_current_version()}")
        else:
            diff = self.diff_states(before_state, new_state)

        self.logger.info(f"修改计划执行完成，共完成 {len(modification_records)} 项修改")
        record_tool_trace(
            session_id=map_state.get_session_id(),
            task_id=getattr(context, "task_id", None),
            tool_name="apply_modifications",
            args={"user_request": user_request, "patch": patch.model_dump()},
            result_summary={
                "operation_count": len(patch.operations),
                "record_count": len(modification_records),
                "before_version": before_version,
                "after_version": new_state.get_current_version(),
                "diff": diff,
            },
            success=True,
            duration_ms=int((time.time() - start_time) * 1000),
        )
        return ModificationResult(
            new_state,
            modification_records,
            patch=patch,
            diff=diff,
            before_version=before_version,
            after_version=new_state.get_current_version(),
        )

    def diff_states(self, before: MapState, after: MapState) -> Dict[str, Any]:
        before_layers = {layer.name: layer for layer in before.layers}
        after_layers = {layer.name: layer for layer in after.layers}
        style_changes = {}
        visibility_changes = {}
        for name in sorted(before_layers.keys() & after_layers.keys()):
            before_layer = before_layers[name]
            after_layer = after_layers[name]
            before_style = before_layer.style.model_dump() if before_layer.style else {}
            after_style = after_layer.style.model_dump() if after_layer.style else {}
            changed_style = {
                key: {"before": before_style.get(key), "after": after_style.get(key)}
                for key in sorted(set(before_style) | set(after_style))
                if before_style.get(key) != after_style.get(key)
            }
            if changed_style:
                style_changes[name] = changed_style
            if before_layer.visible != after_layer.visible:
                visibility_changes[name] = {"before": before_layer.visible, "after": after_layer.visible}
        return {
            "layers": {
                "added": sorted(after_layers.keys() - before_layers.keys()),
                "removed": sorted(before_layers.keys() - after_layers.keys()),
                "visibility": visibility_changes,
            },
            "styles": style_changes,
            "title": {"before": before.config.title, "after": after.config.title}
            if before.config.title != after.config.title else None,
            "generalization_params": {
                key: {"before": (before.generalization_params or {}).get(key), "after": (after.generalization_params or {}).get(key)}
                for key in sorted(set(before.generalization_params or {}) | set(after.generalization_params or {}))
                if (before.generalization_params or {}).get(key) != (after.generalization_params or {}).get(key)
            },
            "output_path": {"before": before.output_path or before.generalization_output_path, "after": after.output_path or after.generalization_output_path}
            if (before.output_path or before.generalization_output_path) != (after.output_path or after.generalization_output_path) else None,
        }

    def _fallback_analyze_request(self, request: str, current_state: MapState) -> IntentAnalysisV2:
        """Rule-based fallback when LLM intent recognition fails."""
        intent = "unknown"
        confidence = 0.0

        request_lower = request.lower()

        if any(keyword in request_lower for keyword in ["\u6dfb\u52a0", "\u52a0\u5165", "\u65b0\u589e"]):
            if "\u56fe\u5c42" in request_lower:
                intent = "add_layer"
            elif any(keyword in request_lower for keyword in ["\u6ce8\u8bb0", "\u6587\u5b57", "\u8bf4\u660e", "\u6807\u6ce8"]):
                intent = "add_annotation"
            confidence = 0.6

        elif any(keyword in request_lower for keyword in ["\u5220\u9664", "\u79fb\u9664", "\u53bb\u6389"]):
            if "\u56fe\u5c42" in request_lower:
                intent = "remove_layer"
            elif any(keyword in request_lower for keyword in ["\u6ce8\u8bb0", "\u6587\u5b57", "\u8bf4\u660e"]):
                intent = "remove_annotation"
            confidence = 0.6

        elif any(keyword in request_lower for keyword in ["\u4fee\u6539", "\u6539\u53d8", "\u8c03\u6574", "\u66f4\u65b0"]):
            if any(keyword in request_lower for keyword in ["\u989c\u8272", "\u6837\u5f0f", "\u7b26\u53f7"]):
                intent = "style_layer"
            elif "\u6807\u9898" in request_lower:
                intent = "update_title"
            elif any(keyword in request_lower for keyword in ["\u8303\u56f4", "\u7f29\u653e", "\u663e\u793a\u533a\u57df"]):
                intent = "update_extent"
            elif any(keyword in request_lower for keyword in ["\u6ce8\u8bb0", "\u6587\u5b57", "\u8bf4\u660e", "\u6807\u6ce8"]):
                intent = "update_annotation"
            elif any(keyword in request_lower for keyword in ["\u4fdd\u7559\u6bd4\u4f8b", "\u7efc\u5408\u53c2\u6570", "\u76ee\u6807\u6bd4\u4f8b\u5c3a", "\u6e90\u6bd4\u4f8b\u5c3a", "\u7b97\u6cd5"]):
                intent = "update_generalization_params"
            confidence = 0.5

        elif any(keyword in request_lower for keyword in ["\u64a4\u9500", "\u56de\u9000", "\u6062\u590d"]):
            intent = "undo"
            confidence = 0.8

        target, params = self._extract_modification_parameters(request, intent, current_state)
        analysis = IntentAnalysisV2(
            request=request,
            intent=intent,
            confidence=confidence,
            target=target,
            requires_confirmation=False,
            reasoning="Rule-based fallback intent analysis",
            **params,
        )
        self.logger.debug(f"备用意图识别完成: {analysis.intent}")
        return analysis

    def undo_last_modification(self, map_state: MapState) -> Optional[MapState]:
        """撤销最后一次修改
        
        Args:
            map_state: 当前地图状态
            
        Returns:
            MapState: 撤销后的状态，失败时返回None
        """
        try:
            current_version = map_state.get_current_version()
            
            if current_version <= 1:
                self.logger.warning("已经是初始版本，无法撤销")
                return None
            
            # 这里需要从状态管理器加载上一个版本
            # 暂时返回None，在集成状态管理器后完善
            self.logger.info("撤销功能需要配合状态管理器实现")
            return None
            
        except Exception as e:
            self.logger.error(f"撤销修改失败: {e}")
            return None
    
    def _extract_modification_parameters(
        self,
        request: str,
        intent: str,
        current_state: MapState,
    ) -> Tuple[Optional[str], Dict[str, Any]]:
        """Extract basic parameters for rule-based fallback intent analysis."""
        request_lower = request.lower()
        params: Dict[str, Any] = {}
        target = None

        layer_names = [layer.name for layer in current_state.layers]
        for layer_name in layer_names:
            if layer_name.lower() in request_lower:
                target = layer_name
                break

        colors = ["\u7ea2\u8272", "\u84dd\u8272", "\u7eff\u8272", "\u9ec4\u8272", "\u6a59\u8272", "\u7d2b\u8272", "\u9ed1\u8272", "\u767d\u8272", "\u7070\u8272"]
        for color in colors:
            if color in request:
                params["color"] = color
                break

        import re
        line_width_match = re.search(r"\u7ebf\u5bbd\s*(\d+(?:\.\d+)?)", request)
        if line_width_match:
            params["line_width"] = float(line_width_match.group(1))

        transparency_match = re.search(r"\u900f\u660e\u5ea6\s*(\d+(?:\.\d+)?)", request)
        if transparency_match:
            params["alpha"] = float(transparency_match.group(1))

        retention_match = re.search(r"(?:\u4fdd\u7559\u6bd4\u4f8b|retention_ratio|keep_ratio)\s*(\d+(?:\.\d+)?)", request, re.IGNORECASE)
        if retention_match:
            params["retention_ratio"] = float(retention_match.group(1))

        target_scale_match = re.search(r"(?:\u76ee\u6807\u6bd4\u4f8b\u5c3a|target_scale)\s*(\d+(?:\.\d+)?)", request, re.IGNORECASE)
        if target_scale_match:
            params["target_scale"] = float(target_scale_match.group(1))

        source_scale_match = re.search(r"(?:\u6e90\u6bd4\u4f8b\u5c3a|source_scale)\s*(\d+(?:\.\d+)?)", request, re.IGNORECASE)
        if source_scale_match:
            params["source_scale"] = float(source_scale_match.group(1))

        for algorithm in ["stroke", "mesh", "density", "hierarchy", "gcnn"]:
            if algorithm in request_lower:
                params["algorithm"] = algorithm
                break

        if intent == "add_annotation":
            text_patterns = [
                r'\u6dfb\u52a0.*?["\u201c](.*?)["\u201d]',
                r'\u6ce8\u8bb0.*?["\u201c](.*?)["\u201d]',
                r'\u8bf4\u660e.*?["\u201c](.*?)["\u201d]',
                r'\u6587\u5b57.*?["\u201c](.*?)["\u201d]',
                r'\u5185\u5bb9.*?["\u201c](.*?)["\u201d]',
                r'\u6dfb\u52a0.*?[:\uff1a]\s*(.+?)(?:\n|$|\u3002|\uff1b)',
                r'\u6ce8\u8bb0.*?[:\uff1a]\s*(.+?)(?:\n|$|\u3002|\uff1b)',
                r'\u8bf4\u660e.*?[:\uff1a]\s*(.+?)(?:\n|$|\u3002|\uff1b)',
                r'\u6587\u5b57.*?[:\uff1a]\s*(.+?)(?:\n|$|\u3002|\uff1b)',
                r'\u5185\u5bb9.*?[:\uff1a]\s*(.+?)(?:\n|$|\u3002|\uff1b)',
                r'\u6dfb\u52a0(?:\u6ce8\u8bb0|\u6587\u5b57|\u8bf4\u660e)?\s*(.{10,}?)(?:\n|$|\u3002)',
                r'\u6ce8\u8bb0\s*(.{10,}?)(?:\n|$|\u3002)',
                r'GDP.*?\u53d1\u5c55.*?\u60c5\u51b5[\uff1a:]?\s*(.+?)(?:\n|$|\u3002)',
                r'\u4ecb\u7ecd.*?GDP.*?[:\uff1a]?\s*(.+?)(?:\n|$|\u3002)',
                r'([^\u3002\uff1b\uff0c\n]{20,}?)(?:\n|$|\u3002|\uff1b|\u8bf7\u5c06|\u5b57\u4f53|\u4f4d\u7f6e)',
            ]
            for pattern in text_patterns:
                match = re.search(pattern, request, re.DOTALL)
                if match:
                    extracted_text = match.group(1).strip()
                    if len(extracted_text) >= 10 and not any(
                        keyword in extracted_text for keyword in ["\u8bf7", "\u8bbe\u7f6e", "\u5b57\u4f53", "\u989c\u8272", "\u4f4d\u7f6e", "\u5927\u5c0f"]
                    ):
                        params["text"] = extracted_text
                        break
            params.setdefault("text", "\u9ed8\u8ba4\u6ce8\u8bb0\u6587\u672c")

        return target, params

    def _apply_single_modification(self, map_state: MapState, operation: PatchOperation,
                                 user_request: str) -> Optional[ModificationRecord]:
        """应用单个修改步骤"""
        action = operation.action
        if not isinstance(action, ModificationAction):
            action = ModificationAction(action)
        target = operation.target
        parameters = operation.parameters

        # 添加显式日志
        self.logger.debug(f"开始执行修改步骤: {_action_label(action)} -> {target}")
        self.logger.debug(f"参数: {parameters}")

        record = ModificationRecord(
            action=action,
            target=target,
            parameters=parameters,
            user_request=user_request,
            description=f"执行 {action.value} 操作"
        )

        try:
            if action == ModificationAction.STYLE_LAYER:
                self._modify_layer_style(map_state, target, parameters)
                record.description = f"修改图层 '{target}' 的样式"

            elif action == ModificationAction.ADD_ANNOTATION:
                self._add_annotation(map_state, parameters)
                record.description = f"添加注记: {parameters.get('text', '')}"

            elif action == ModificationAction.REMOVE_ANNOTATION:
                self._remove_annotation(map_state, target)
                record.description = f"删除注记: {target}"

            elif action == ModificationAction.UPDATE_ANNOTATION:
                self._update_annotation(map_state, target, parameters)
                record.description = f"修改注记: {target}"

            elif action == ModificationAction.ADD_LAYER:
                self._add_layer(map_state, target, parameters)
                record.description = f"添加图层 '{target}'"

            elif action == ModificationAction.REMOVE_LAYER:
                self._remove_layer(map_state, target)
                record.description = f"删除图层 '{target}'"

            elif action == ModificationAction.TOGGLE_LAYER_VISIBILITY:
                self._toggle_layer_visibility(map_state, target, parameters)
                record.description = f"设置图层 '{target}' 可见性"

            elif action == ModificationAction.UPDATE_MAP_CONFIG:
                self._update_map_config(map_state, target, parameters)
                record.description = f"更新地图配置: {target}"

            elif action == ModificationAction.UPDATE_GENERALIZATION_PARAMS:
                self._update_generalization_params(map_state, parameters)
                record.description = "更新路网综合参数"

            # 新增：添加指北针
            elif action == ModificationAction.ADD_COMPASS:
                self._add_compass(map_state, parameters)
                record.description = f"添加指北针"

            # 新增：添加比例尺
            elif action == ModificationAction.ADD_SCALEBAR:
                self._add_scalebar(map_state, parameters)
                record.description = f"添加比例尺"

            # 新增：删除指北针
            elif action == ModificationAction.REMOVE_COMPASS:
                self._remove_compass(map_state)
                record.description = f"删除指北针"

            # 新增：删除比例尺
            elif action == ModificationAction.REMOVE_SCALEBAR:
                self._remove_scalebar(map_state)
                record.description = f"删除比例尺"

            else:
                raise ValueError(f"不支持的修改动作: {action}")

            self.logger.info(f"修改步骤执行成功: {record.description}")
            return record

        except Exception as e:
            self.logger.error(f"执行修改步骤失败: {_action_label(action)}，错误: {e}")
            # 不要吞掉异常，重新抛出让上层处理
            raise e
    
    def _modify_layer_style(self, map_state: MapState, layer_name: str, parameters: Dict[str, Any]) -> None:
        """修改图层样式"""
        from ..utils.helpers import parse_color

        for layer in map_state.layers:
            if layer.name == layer_name:
                # 参数名称映射（支持多种命名方式）
                param_mapping = {
                    "line_width": "linewidth",
                    "line_style": "linestyle",
                    "edge_color": "edgecolor",
                    "face_color": "facecolor",
                    "marker_size": "size"
                }

                # 标准化参数名称
                normalized_params = {}
                for key, value in parameters.items():
                    normalized_key = param_mapping.get(key, key)
                    normalized_params[normalized_key] = value

                # 更新样式参数
                if "color" in normalized_params:
                    layer.style.color = parse_color(normalized_params["color"])
                if "linewidth" in normalized_params:
                    layer.style.linewidth = float(normalized_params["linewidth"])
                if "linestyle" in normalized_params:
                    layer.style.linestyle = normalized_params["linestyle"]
                if "marker" in normalized_params:
                    layer.style.marker = normalized_params["marker"]
                if "size" in normalized_params:
                    layer.style.size = float(normalized_params["size"])
                if "edgecolor" in normalized_params:
                    layer.style.edgecolor = parse_color(normalized_params["edgecolor"])
                if "facecolor" in normalized_params:
                    layer.style.facecolor = parse_color(normalized_params["facecolor"])
                if "alpha" in normalized_params:
                    layer.style.alpha = float(normalized_params["alpha"])
                break
    
    def _add_annotation(self, map_state: MapState, parameters: Dict[str, Any]) -> None:
        """添加注记"""
        from ..utils.helpers import generate_unique_id, parse_color

        # 验证必需的text参数
        text = parameters.get("text", "").strip()
        if not text:
            raise ValueError("必须提供text参数。请在请求中明确指定要添加的注记文本内容。")

        # 处理参数，确保None值被替换为默认值
        position = parameters.get("position") or [0.5, 0.1]
        font_size = parameters.get("font_size") or 12.0
        font_family = parameters.get("font_family") or "Arial"
        color = parse_color(parameters.get("color") or "black")  # 使用parse_color处理颜色
        background_color = parse_color(parameters.get("background_color")) if parameters.get("background_color") else None
        rotation = parameters.get("rotation") or 0.0
        alignment = parameters.get("alignment") or "center"

        annotation_config = AnnotationConfig(
            annotation_id=generate_unique_id(),
            text=text,
            position=position,
            font_size=font_size,
            font_family=font_family,
            color=color,
            background_color=background_color,
            rotation=rotation,
            alignment=alignment
        )
        map_state.annotations.append(annotation_config)
        self.logger.info(f"添加注记成功: {text[:50]}...")
    
    def _remove_annotation(self, map_state: MapState, annotation_identifier: str) -> None:
        """删除注记"""
        original_count = len(map_state.annotations)

        # 如果没有指定具体的注记标识符，或者找不到指定的注记，则删除所有注记
        if not annotation_identifier or annotation_identifier.strip() == "" or annotation_identifier == "注记":
            # 直接清除所有注记
            map_state.annotations.clear()
            self.logger.info(f"删除了所有 {original_count} 个注记")
            return

        # 根据注记ID或文本内容删除特定注记
        map_state.annotations = [
            annotation for annotation in map_state.annotations
            if annotation.annotation_id != annotation_identifier and
               annotation.text != annotation_identifier
        ]

        # 如果没有找到指定的注记，则删除所有注记作为备选方案
        if len(map_state.annotations) == original_count:
            self.logger.warning(f"未找到指定注记: {annotation_identifier}，删除所有注记")
            map_state.annotations.clear()

    def _update_annotation(self, map_state: MapState, annotation_identifier: str, parameters: Dict[str, Any]) -> None:
        """修改注记内容或样式"""
        from ..utils.helpers import parse_color

        target_annotation = None

        # 查找目标注记 - 支持多种匹配方式
        for annotation in map_state.annotations:
            # 1. 完全匹配注记ID
            if annotation.annotation_id == annotation_identifier:
                target_annotation = annotation
                break
            # 2. 完全匹配注记文本
            if annotation.text == annotation_identifier:
                target_annotation = annotation
                break
            # 3. 部分匹配注记文本（包含关键词）
            if annotation_identifier in annotation.text or annotation.text in annotation_identifier:
                target_annotation = annotation
                break
            # 4. 模糊匹配关键词（如"GDP"匹配包含"GDP"的注记）
            keywords = annotation_identifier.split()
            if any(keyword in annotation.text for keyword in keywords if len(keyword) > 1):
                target_annotation = annotation
                break

        if not target_annotation:
            # 如果只有一个注记，直接使用它
            if len(map_state.annotations) == 1:
                target_annotation = map_state.annotations[0]
                self.logger.info(f"只有一个注记，直接使用它进行修改")
            else:
                raise ValueError(f"未找到注记: {annotation_identifier}，当前有 {len(map_state.annotations)} 个注记")

        # 更新注记属性
        for key, value in parameters.items():
            if hasattr(target_annotation, key):
                # 处理颜色参数
                if key in ['color', 'background_color'] and value:
                    value = parse_color(value)
                setattr(target_annotation, key, value)
                self.logger.info(f"更新注记属性: {key} = {value}")

    def _add_layer(self, map_state: MapState, layer_name: str, parameters: Dict[str, Any]) -> None:
        """添加图层"""
        from ..models.schemas import LayerConfig, GeometryType
        from pathlib import Path
        import geopandas as gpd

        # 从参数中获取数据源
        source = parameters.get("source", "")
        style = parameters.get("style", {})

        # 解析数据源路径
        if not source:
            raise ValueError(f"添加图层需要指定数据源")

        # 处理数据源路径
        from ..utils.data_path_resolver import extract_data_info_from_request, resolve_data_path

        # 尝试从source中提取数据目录和文件
        data_dir, data_files = extract_data_info_from_request(source)

        # 如果没有提取到，尝试直接使用layer_name作为文件名
        if not data_files:
            data_files = [f"{layer_name}.shp"]

        # 解析完整路径
        if data_dir:
            data_path = resolve_data_path(data_dir) / data_files[0]
        else:
            # 尝试在各个data目录中查找
            from ..utils.config import Config
            base_path = Config.DATA_DIRECTORY_BASE
            if not base_path.is_absolute():
                base_path = Config.PROJECT_ROOT / base_path

            # 尝试在data1-data5中查找
            data_path = None
            for i in range(1, 6):
                test_path = base_path / f"data{i}" / data_files[0]
                if test_path.exists():
                    data_path = test_path
                    break

            if not data_path:
                raise FileNotFoundError(f"找不到数据文件: {data_files[0]}")

        if not data_path.exists():
            raise FileNotFoundError(f"数据文件不存在: {data_path}")

        # 读取数据以获取几何类型
        gdf = gpd.read_file(data_path)
        geom_type_str = gdf.geometry.geom_type.iloc[0]

        # 映射几何类型
        geom_type_map = {
            "Point": GeometryType.POINT,
            "MultiPoint": GeometryType.POINT,
            "LineString": GeometryType.LINE,
            "MultiLineString": GeometryType.LINE,
            "Polygon": GeometryType.POLYGON,
            "MultiPolygon": GeometryType.POLYGON
        }
        geometry_type = geom_type_map.get(geom_type_str, GeometryType.POLYGON)

        # 创建图层配置
        from ..utils.helpers import generate_unique_id, parse_color
        from ..utils.config import Config

        # 将绝对路径转换为相对于PROJECT_ROOT的相对路径
        try:
            relative_path = data_path.relative_to(Config.PROJECT_ROOT)
            data_source_str = str(relative_path).replace('\\', '/')
        except ValueError:
            # 如果无法转换为相对路径，使用绝对路径
            data_source_str = str(data_path)

        # 处理样式参数：参数名称映射和颜色解析
        processed_style = {}
        if style:
            # 参数名称映射
            param_mapping = {
                "line_width": "linewidth",
                "line_style": "linestyle",
                "edge_color": "edgecolor",
                "face_color": "facecolor",
                "marker_size": "size"
            }

            for key, value in style.items():
                # 标准化参数名称
                normalized_key = param_mapping.get(key, key)

                # 处理颜色参数
                if normalized_key in ['color', 'edgecolor', 'facecolor'] and isinstance(value, str):
                    processed_style[normalized_key] = parse_color(value)
                else:
                    processed_style[normalized_key] = value

        layer_config = LayerConfig(
            layer_id=generate_unique_id(),
            name=layer_name,
            data_source=data_source_str,
            geometry_type=geometry_type,
            style=processed_style if processed_style else style,
            visible=True
        )

        # 添加到地图状态
        map_state.layers.append(layer_config)
        self.logger.info(f"成功添加图层: {layer_name}")
        self.logger.debug(f"图层数据源: {data_source_str}，样式: {processed_style}")

    def _remove_layer(self, map_state: MapState, layer_name: str) -> None:
        """删除图层"""
        existing_names = [layer.name for layer in map_state.layers]
        if layer_name not in existing_names:
            raise ValueError(f"未找到图层: {layer_name}。可用图层: {', '.join(existing_names)}")

        original_count = len(map_state.layers)
        map_state.layers = [layer for layer in map_state.layers if layer.name != layer_name]
        if len(map_state.layers) == original_count:
            raise ValueError(f"删除图层失败: {layer_name}")

    def _toggle_layer_visibility(self, map_state: MapState, layer_name: str, parameters: Dict[str, Any]) -> None:
        for layer in map_state.layers:
            if layer.name == layer_name:
                layer.visible = bool(parameters.get("visible", not layer.visible))
                return
        raise ValueError(f"未找到图层: {layer_name}")

    def _update_generalization_params(self, map_state: MapState, parameters: Dict[str, Any]) -> None:
        map_state.generalization_params = map_state.generalization_params or {}
        if "retention_ratio" in parameters and "keep_ratio" not in parameters:
            parameters = {**parameters, "keep_ratio": parameters["retention_ratio"]}
        for key in ("keep_ratio", "target_scale", "source_scale", "algorithm"):
            if key in parameters:
                map_state.generalization_params[key] = parameters[key]
        map_state.generalization_algorithm = map_state.generalization_params.get("algorithm", map_state.generalization_algorithm)

    def _update_map_config(self, map_state: MapState, target: str, parameters: Dict[str, Any]) -> None:
        """更新地图配置"""
        from ..utils.helpers import parse_color

        if target == "title" and "title" in parameters:
            map_state.config.title = parameters["title"]
            self.logger.info(f"更新地图标题: {parameters['title']}")
        elif target == "extent" and "extent" in parameters:
            map_state.config.extent = parameters["extent"]
            self.logger.info(f"更新地图范围: {parameters['extent']}")
        elif target == "background" and "background_color" in parameters:
            # 处理背景色修改
            background_color = parameters["background_color"]
            if isinstance(background_color, str):
                background_color = parse_color(background_color)
            map_state.config.background_color = background_color
            self.logger.info(f"更新地图背景色: {background_color}")
        elif target == "title" or "title" in parameters:
            map_state.config.title = parameters.get("title", target)
        elif "background_color" in parameters:
            # 如果参数中包含background_color，无论target是什么都处理
            background_color = parameters["background_color"]
            if isinstance(background_color, str):
                background_color = parse_color(background_color)
            map_state.config.background_color = background_color
            self.logger.info(f"更新地图背景色: {background_color}")

    def _add_compass(self, map_state: MapState, parameters: Dict[str, Any]) -> None:
        """添加指北针"""
        compass_config = {
            "position": parameters.get("position", [0.9, 0.9]),
            "size": parameters.get("size", 0.05),
            "style": parameters.get("style", "arrow")
        }
        map_state.compass = compass_config
        self.logger.info("已添加指北针")
        self.logger.debug(f"指北针配置: {compass_config}")

    def _add_scalebar(self, map_state: MapState, parameters: Dict[str, Any]) -> None:
        """添加比例尺"""
        scalebar_config = {
            "position": parameters.get("position", [0.01, 0.01]),  # 与初始化时保持一致
            "length": parameters.get("length", 100),
            "units": parameters.get("units", "km"),
            "style": parameters.get("style", "simple")
        }
        map_state.scalebar = scalebar_config
        self.logger.info("已添加比例尺")
        self.logger.debug(f"比例尺配置: {scalebar_config}")

    def _remove_compass(self, map_state: MapState) -> None:
        """删除指北针"""
        if map_state.compass is None:
            raise ValueError("地图中没有指北针，无法删除")

        self.logger.info("删除指北针...")
        map_state.compass = None
        # 关键修复：同时禁用自动指北针
        map_state.config.auto_compass = False
        self.logger.info("指北针删除成功，已禁用自动指北针")

    def _remove_scalebar(self, map_state: MapState) -> None:
        """删除比例尺"""
        if map_state.scalebar is None:
            raise ValueError("地图中没有比例尺，无法删除")

        self.logger.info("删除比例尺...")
        map_state.scalebar = None
        # 关键修复：同时禁用自动比例尺
        map_state.config.auto_scalebar = False
        self.logger.info("比例尺删除成功，已禁用自动比例尺")


# 使用单例装饰器创建全局修改引擎
@singleton
class _ModificationEngineSingleton:
    """修改引擎单例包装器"""
    def __init__(self):
        self.engine = ModificationEngine()

def get_modification_engine() -> ModificationEngine:
    """获取全局修改引擎实例

    Returns:
        ModificationEngine: 全局唯一的修改引擎实例

    Note:
        使用单例模式确保整个应用只有一个修改引擎实例
    """
    return _ModificationEngineSingleton().engine
