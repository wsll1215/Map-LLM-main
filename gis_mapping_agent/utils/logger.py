"""日志配置模块"""

import sys
from loguru import logger


# 全局标志，确保 setup_logger 只执行一次
_logger_initialized = False


# 工具名称映射，将函数名映射为简洁的工具名
TOOL_NAME_MAP = {
    "init_map": "初始化地图工具",
    "add_layer": "添加图层工具",
    "style_layer": "图层样式工具",
    "add_annotation": "添加标注工具",
    "add_legend": "添加图例工具",
    "add_scalebar": "添加比例尺工具",
    "add_compass": "添加指北针工具",
    "map_save": "地图保存工具",
    "_draw_scalebar": "绘制比例尺工具",
    "_draw_compass": "绘制指北针工具",
    "_setup_axis_ticks": "初始化地图轴刻度工具",
    "setup_logger": "日志记录工具",
    "__init__": "系统初始化工具",
    "parse_data_directory_from_request": "从请求解析数据目录工具",
    "find_data_files_in_request": "在请求中查找数据文件工具",
    "_calculate_auto_extent": "自动计算范围工具",
    "_initialize_tools": "系统工具初始化器",
    "_execute_tool": "执行工具",
    "_draw_auto_legend": "自动绘制图例工具",
    "_redraw_map": "重新绘制地图工具",
    "_rebuild_map_from_state": "从状态重建地图工具",
    "_current_map_state": "当前地图状态工具",
    "_apply_single_modification": "应用单次修改工具",
    "_update_annotation": "更新标注工具",
    "classify_intent": "意图分类工具",
    "_create_map": "创建地图工具",
    "_get_final_map_state": "获取最终地图状态工具",
    "_execute_thinking_loop": "执行思考循环工具",
    # 对话式工具
    "chat": "对话工具",
    "_classify_intent": "意图分类工具",
    "_init_database": "数据库初始化工具",
    "save_state": "状态保存工具",
    "create_map": "创建地图工具",
    # 路网综合工具
    "generalize": "路网综合工具",
    "generalize_road_network": "路网综合",
    "build_strokes": "构建Stroke工具",
    "select_by_hierarchy": "层次选取工具",
    "_select_by_stroke_importance": "按Stroke重要性选取工具",
    "_select_by_length": "按长度选取工具",
    "_select_by_attribute": "按属性选取工具",
    "_select_by_percentile": "按百分位选取工具",
    "visualize_comparison": "可视化对比工具",
    "visualize_generalization": "可视化综合结果",
    # 路网综合修改工具
    "modify_generalization_params": "修改综合参数工具",
    "_modify_generalization_task": "修改路网综合任务",
    "calculate_mesh_density": "计算网眼密度",
    "MeshDensityCalculator": "网眼密度计算器",
    # GCNN路网选取工具
    "GCNNSelector": "GCNN路网选取工具",
    "Select_By_GcnnTool": "GCNN路网选取工具",
    "select_by_gcnn": "GCNN路网选取工具",
    "select_by_gcnn_with_shp": "GCNN路网选取工具",
    # 图层操作工具
    "remove_layer": "移除图层工具",
    "Remove_LayerTool": "移除图层工具",
    "remove_scalebar": "删除比例尺工具",
    "Remove_ScalebarTool": "删除比例尺工具",
    "remove_compass": "删除指北针工具",
    "Remove_CompassTool": "删除指北针工具",
    "toggle_layer_visibility": "切换图层可见性工具",
    "update_map_title": "更新地图标题工具",
    "clear_annotations": "清除注记工具",
    # 修改引擎工具
    "generate_modification_plan": "生成修改计划",
    "Generate_Modification_PlanTool": "生成修改计划工具",
    "apply_modifications": "应用修改",
    "Apply_ModificationsTool": "应用修改工具",
    "_update_map_config": "更新地图配置",
    "_Update_Map_ConfigTool": "更新地图配置工具",
    "_add_scalebar": "添加比例尺",
    "_Add_ScalebarTool": "添加比例尺工具",
    "_add_compass": "添加指北针",
    "_Add_CompassTool": "添加指北针工具",
    "_remove_scalebar": "删除比例尺",
    "_Remove_ScalebarTool": "删除比例尺工具",
    "_remove_compass": "删除指北针",
    "_Remove_CompassTool": "删除指北针工具"
}



def get_simple_tool_name(function_name: str) -> str:
    """获取简化的工具名称"""
    return TOOL_NAME_MAP.get(function_name, function_name.title() + "Tool")


def setup_logger(force_rebind: bool = False) -> None:
    """设置日志配置
    - 默认幂等，仅首次初始化
    - 当 force_rebind=True 时，强制移除已有sink并绑定到当前 sys.stdout（用于每次Web请求的捕获）
    """
    global _logger_initialized

    # 非强制时，首次之后直接返回
    if _logger_initialized and not force_rebind:
        return

    # 移除所有处理器（sink），避免重复输出或绑定到旧的 stdout
    logger.remove()

    # 绑定到当前的 sys.stdout（可被Django视图内的 StreamingOutputCapture 替换）
    logger.add(
        sys.stdout,
        level="INFO",
        format="<cyan>{extra[tool_name]}</cyan> | <level>{message}</level>",
        colorize=True,
        serialize=False,  # 避免序列化问题
        filter=lambda record: record["extra"].update(
            tool_name=get_simple_tool_name(record["function"])
        ) or True
    )

    # 标记为已初始化
    _logger_initialized = True

    # 仅在非强制重绑时输出一次初始化日志，避免每次请求都打印
    if not force_rebind:
        logger.info("日志系统初始化完成")


def get_logger(name: str):
    """获取指定名称的日志器"""
    return logger.bind(name=name)
