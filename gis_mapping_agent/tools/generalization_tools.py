"""Road generalization LangChain tools."""

import time
from typing import Optional, Type

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from ..specs import GeneralizationSpec
from ..state import get_generalization_state, get_session_context, record_tool_trace, save_generalization_context
from ..utils.config import Config


def _get_generalization_state(session_id: Optional[str] = None):
    return get_generalization_state(session_id)


def _save_generalization_state(session_id: Optional[str], map_state, result=None) -> None:
    if result is not None:
        map_state.generalization_result = result
    save_generalization_context(
        session_id or map_state.get_session_id(),
        map_state=map_state,
        generalization_result=map_state.generalization_result,
        generalization_params=map_state.generalization_params,
    )


class GeneralizeRoadNetworkInput(BaseModel):
    """路网综合工具输入"""
    session_id: Optional[str] = Field(default=None, description="会话ID")
    data_file: str = Field(description="数据文件名，如 '综合前.shp'")
    data_directory: Optional[str] = Field(default=None, description="数据目录，如 'data1' 或 'data6'")
    source_scale: int = Field(default=500, description="源尺度，如 500 表示 1:500（stroke/mesh_density/hierarchy算法使用，gcnn算法不使用）")
    target_scale: int = Field(default=2000, description="目标尺度，如 2000 表示 1:2000（stroke/mesh_density/hierarchy算法使用，gcnn算法不使用）")
    algorithm: str = Field(
        default="stroke",
        description="综合算法：'stroke'（Stroke构建，使用尺度参数）, 'mesh_density'（网眼密度，使用尺度参数）, 'hierarchy'（层次选取，使用尺度参数）, 'gcnn'（图卷积神经网络，只使用保留比例参数）"
    )
    keep_ratio: Optional[float] = Field(
        default=None,
        description="保留比例（0-1之间）。gcnn算法必须指定此参数；其他算法如果不指定，则根据source_scale和target_scale自动计算"
    )


    hierarchy_method: Optional[str] = Field(
        default=None,
        description="层次选取方法。可选 length、attribute、stroke_importance、percentile。按道路等级字段选取时使用 attribute。"
    )
    hierarchy_attribute: Optional[str] = Field(
        default=None,
        description="层次选取使用的属性字段名，例如 road_class、fclass、ClassZn2。字段不存在时会自动做别名或相似字段匹配。"
    )


class GeneralizeRoadNetworkTool(BaseTool):
    """路网综合工具"""
    name: str = "generalize_road_network"
    description: str = """
    执行路网综合处理，从大尺度到小尺度的自动缩编。

    参数说明：
    - data_file: 必需，数据文件名（如 '综合前.shp'）
    - data_directory: 可选，数据目录（如 'data1' 或 'data6'）
    - source_scale: 源尺度（默认500，表示1:500）
        * stroke/mesh_density/hierarchy算法使用此参数
        * gcnn算法不使用此参数
    - target_scale: 目标尺度（默认2000，表示1:2000）
        * stroke/mesh_density/hierarchy算法使用此参数
        * gcnn算法不使用此参数
    - algorithm: 综合算法
        * 'stroke': Stroke构建算法（推荐，使用source_scale和target_scale）
        * 'mesh_density': 网眼密度算法（使用source_scale和target_scale）
        * 'hierarchy': 层次选取算法（使用source_scale和target_scale）
        * 'gcnn': 图卷积神经网络算法（只使用keep_ratio参数，基于深度学习自动选取）
    - keep_ratio: 保留比例（0-1之间）
        * gcnn算法：必须明确指定此参数（如0.3表示保留30%的路网）
        * 其他算法：可选，如果不指定则根据source_scale和target_scale自动计算

    示例1（使用Stroke算法，基于尺度要求）：
    {
        "data_file": "综合前.shp",
        "data_directory": "data6",
        "source_scale": 500,
        "target_scale": 20000,
        "algorithm": "stroke"
    }

    示例2（使用GCNN算法，基于保留比例）：
    {
        "data_file": "综合前.shp",
        "data_directory": "data6",
        "algorithm": "gcnn",
        "keep_ratio": 0.3
    }

    返回：综合结果的统计信息
    """
    args_schema: Type[BaseModel] = GeneralizeRoadNetworkInput

    def _run(
        self,
        data_file: str,
        data_directory: Optional[str] = None,
        source_scale: int = 500,
        target_scale: int = 2000,
        algorithm: str = "stroke",
        keep_ratio: Optional[float] = None,
        hierarchy_method: Optional[str] = None,
        hierarchy_attribute: Optional[str] = None,
        session_id: Optional[str] = None
    ) -> str:
        """执行路网综合"""
        start_time = time.time()
        try:
            from ..generalization import RoadNetworkGeneralizationEngine
            from ..utils.data_path_resolver import resolve_data_path
            from ..models.schemas import MapState, MapConfig, SessionInfo
            from datetime import datetime
            import geopandas as gpd

            spec = GeneralizationSpec.from_legacy_dict({
                "data_file": data_file,
                "data_directory": data_directory,
                "source_scale": source_scale,
                "target_scale": target_scale,
                "algorithm": algorithm,
                "keep_ratio": keep_ratio,
                "hierarchy_method": hierarchy_method,
                "hierarchy_attribute": hierarchy_attribute,
            })
            data_file = spec.data_file
            data_directory = spec.data_directory
            source_scale = spec.source_scale
            target_scale = spec.target_scale
            algorithm = spec.algorithm
            keep_ratio = spec.keep_ratio
            hierarchy_method = spec.hierarchy_method
            hierarchy_attribute = spec.hierarchy_attribute

            # 解析数据路径
            data_path = resolve_data_path(data_directory)
            file_path = data_path / data_file

            if not file_path.exists():
                return f"❌ 数据文件不存在: {file_path}"

            # 读取数据
            gdf = gpd.read_file(file_path)

            # 创建综合引擎
            engine = RoadNetworkGeneralizationEngine(verbose=True)

            # 执行综合
            # 对于GCNN算法，需要传递data_directory参数
            if algorithm == 'gcnn':
                result = engine.generalize(
                    input_gdf=gdf,
                    source_scale=source_scale,
                    target_scale=target_scale,
                    algorithm=algorithm,
                    keep_ratio=keep_ratio,
                    data_dir=str(data_path),  # GCNN需要数据目录
                    input_path=str(file_path),
                    hierarchy_method=hierarchy_method,
                    hierarchy_attribute=hierarchy_attribute,
                )
            else:
                result = engine.generalize(
                    input_gdf=gdf,
                    source_scale=source_scale,
                    target_scale=target_scale,
                    algorithm=algorithm,
                    keep_ratio=keep_ratio,
                    input_path=str(file_path),
                    hierarchy_method=hierarchy_method,
                    hierarchy_attribute=hierarchy_attribute,
                )

            active_session_id, existing_state, _ = _get_generalization_state(session_id)

            # 检查是否已有状态（用于参数修改场景）
            if existing_state is None:
                # 创建新的 MapState
                import uuid

                session_info = SessionInfo(
                    session_id=active_session_id,
                    session_name=f"路网综合_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                )

                # 创建简单的地图配置（路网综合不需要完整的地图配置）
                map_config = MapConfig(
                    map_id=str(uuid.uuid4()),  # 生成唯一ID
                    title=f"路网综合 ({algorithm}算法)",
                    extent=[0, 0, 1, 1],  # 占位符
                    figsize=(16, 8)
                )

                map_state = MapState(
                    config=map_config,
                    session_info=session_info,
                    is_generalization_task=True,
                    generalization_algorithm=algorithm,
                    generalization_params={
                        "data_file": data_file,
                        "data_directory": data_directory,
                        "source_scale": source_scale,
                        "target_scale": target_scale,
                        "algorithm": algorithm,
                        "keep_ratio": keep_ratio,
                        "hierarchy_method": result.get("hierarchy_method") or hierarchy_method,
                        "hierarchy_attribute": result.get("hierarchy_attribute") or hierarchy_attribute
                    },
                    generalization_input_path=str(file_path),
                    generalization_output_path=str(result.get("filepath")) if result.get("filepath") else None,
                    generalization_metrics=result.get("statistics"),
                    generalization_result_meta={
                        "algorithm": algorithm,
                        "keep_ratio": result.get("keep_ratio"),
                        "stroke_count": result.get("stroke_count"),
                        "hierarchy_method": result.get("hierarchy_method"),
                        "hierarchy_attribute": result.get("hierarchy_attribute"),
                    },
                    generalization_result=result
                )

            else:
                # 更新现有状态（参数修改）
                map_state = existing_state
                map_state.generalization_params.update({
                    "source_scale": source_scale,
                    "target_scale": target_scale,
                    "algorithm": algorithm,
                    "keep_ratio": keep_ratio,
                    "hierarchy_method": result.get("hierarchy_method") or hierarchy_method,
                    "hierarchy_attribute": result.get("hierarchy_attribute") or hierarchy_attribute
                })
                map_state.generalization_algorithm = algorithm
                map_state.generalization_input_path = str(file_path)
                map_state.generalization_output_path = str(result.get("filepath")) if result.get("filepath") else map_state.generalization_output_path
                map_state.generalization_metrics = result.get("statistics")
                map_state.generalization_result_meta = {
                    "algorithm": algorithm,
                    "keep_ratio": result.get("keep_ratio"),
                    "stroke_count": result.get("stroke_count"),
                    "hierarchy_method": result.get("hierarchy_method"),
                    "hierarchy_attribute": result.get("hierarchy_attribute"),
                }
                map_state.generalization_result = result
                map_state.version_info.version += 1
                map_state.updated_at = datetime.now().isoformat()

            _save_generalization_state(active_session_id, map_state, result)

            # 注意：不在这里保存状态，等到可视化工具中保存
            # 避免重复保存导致 UNIQUE constraint 错误
            # state_manager.save_state(map_state)

            stats = result['statistics']

            record_tool_trace(
                session_id=map_state.get_session_id(),
                task_id=getattr(get_session_context(map_state.get_session_id(), create=False), "task_id", None),
                tool_name="generalize_road_network",
                args={
                    "session_id": map_state.get_session_id(),
                    "data_file": data_file,
                    "data_directory": data_directory,
                    "source_scale": source_scale,
                    "target_scale": target_scale,
                    "algorithm": algorithm,
                    "keep_ratio": keep_ratio,
                    "hierarchy_method": hierarchy_method,
                    "hierarchy_attribute": hierarchy_attribute,
                },
                result_summary={
                    "algorithm": algorithm,
                    "input_count": stats.get("input_count"),
                    "output_count": stats.get("output_count"),
                    "keep_ratio": result.get("keep_ratio"),
                    "hierarchy_method": result.get("hierarchy_method"),
                    "hierarchy_attribute": result.get("hierarchy_attribute"),
                },
                success=True,
                duration_ms=int((time.time() - start_time) * 1000),
            )

            return f"""✅ 路网综合完成！

                算法: {algorithm}
                尺度: 1:{source_scale} → 1:{target_scale}
                保留比例: {result['keep_ratio']:.2%}

                统计信息:
                - 输入路段数: {stats['input_count']}
                - 输出路段数: {stats['output_count']}
                - 削减率: {stats['reduction_rate']:.2%}
                - 总长度保留率: {stats['length_retention_rate']:.2%}

                会话ID: {map_state.get_session_id()[:8]}...
                版本: v{map_state.get_current_version()}

                综合结果已保存，可以使用 visualize_generalization 工具生成对比图。
                """

        except Exception as e:
            import traceback
            traceback.print_exc()
            record_tool_trace(
                session_id=session_id,
                task_id=getattr(get_session_context(session_id, create=False), "task_id", None),
                tool_name="generalize_road_network",
                args={
                    "data_file": data_file,
                    "data_directory": data_directory,
                    "source_scale": source_scale,
                    "target_scale": target_scale,
                    "algorithm": algorithm,
                    "keep_ratio": keep_ratio,
                    "session_id": session_id,
                },
                result_summary=None,
                success=False,
                error=str(e),
                duration_ms=int((time.time() - start_time) * 1000),
            )
            return f"❌ 路网综合失败: {str(e)}"


class VisualizeGeneralizationInput(BaseModel):
    """可视化综合结果输入"""
    session_id: Optional[str] = Field(default=None, description="会话ID")
    figsize_width: int = Field(default=Config.HYPERPARAMETERS.GENERALIZATION_FIGSIZE[0], description="图片宽度")
    figsize_height: int = Field(default=Config.HYPERPARAMETERS.GENERALIZATION_FIGSIZE[1], description="图片高度")
    dpi: int = Field(default=Config.HYPERPARAMETERS.DEFAULT_DPI, description="分辨率")
    add_scalebar: Optional[bool] = Field(default=None, description="是否添加比例尺。如果为None，则继承上一次的设置")
    add_compass: Optional[bool] = Field(default=None, description="是否添加指北针。如果为None，则继承上一次的设置")


class VisualizeGeneralizationTool(BaseTool):
    """可视化路网综合结果工具"""
    name: str = "visualize_generalization"
    description: str = """
    生成路网综合前后的对比可视化图。这是路网综合任务的最后一步，调用后任务即完成。

    必须先调用 generalize_road_network 工具执行综合，然后才能调用此工具。

    参数说明：
    - figsize_width: 图片宽度（默认16）
    - figsize_height: 图片高度（默认8）
    - dpi: 分辨率（默认300）
    - add_scalebar: 是否添加比例尺（默认None，继承上一次的设置）
    - add_compass: 是否添加指北针（默认None，继承上一次的设置）

    返回：生成的图片文件路径

    重要提示：
    1. 此工具会自动保存对比图到outputs目录，调用成功后路网综合可视化任务即完成，无需再调用其他工具。
    2. **不要使用此工具来添加或删除比例尺/指北针**！应该使用专门的工具：
       - 添加比例尺：调用 add_scalebar 工具
       - 添加指北针：调用 add_compass 工具
       - 删除比例尺：调用 remove_scalebar 工具
       - 删除指北针：调用 remove_compass 工具
    3. 此工具的 add_scalebar 和 add_compass 参数仅用于内部调用，不应该由LLM直接设置。
    """
    args_schema: Type[BaseModel] = VisualizeGeneralizationInput

    def _run(
        self,
        figsize_width: int = Config.HYPERPARAMETERS.GENERALIZATION_FIGSIZE[0],
        figsize_height: int = Config.HYPERPARAMETERS.GENERALIZATION_FIGSIZE[1],
        dpi: int = Config.HYPERPARAMETERS.GENERALIZATION_DPI,
        add_scalebar: Optional[bool] = None,
        add_compass: Optional[bool] = None,
        session_id: Optional[str] = None
    ) -> str:
        """执行可视化"""
        start_time = time.time()
        try:
            active_session_id, map_state, generalization_result = _get_generalization_state(session_id)

            if generalization_result is None:
                record_tool_trace(
                    session_id=active_session_id,
                    task_id=getattr(get_session_context(active_session_id, create=False), "task_id", None),
                    tool_name="visualize_generalization",
                    args={
                        "figsize_width": figsize_width,
                        "figsize_height": figsize_height,
                        "dpi": dpi,
                        "add_scalebar": add_scalebar,
                        "add_compass": add_compass,
                        "session_id": session_id,
                    },
                    result_summary=None,
                    success=False,
                    error="missing generalization result",
                    duration_ms=int((time.time() - start_time) * 1000),
                )
                return "❌ 请先调用 generalize_road_network 工具执行路网综合"

            from ..generalization import RoadNetworkGeneralizationEngine
            from ..state import get_state_manager
            from ..models.schemas import ModificationRecord, ModificationAction

            engine = RoadNetworkGeneralizationEngine(verbose=True)

            is_revisualization = False
            is_first_visualization = False

            if map_state is not None:
                # 检查是否是重新可视化
                if (map_state.generalization_result and
                    'visualization' in map_state.generalization_result):
                    is_revisualization = True
                else:
                    # 首次可视化
                    is_first_visualization = True

            # 确定是否添加比例尺和指北针
            if add_scalebar is None:
                if is_first_visualization:
                    # 首次可视化，默认添加比例尺
                    add_scalebar = True
                elif map_state is not None and hasattr(map_state, 'scalebar'):
                    # 重新可视化，继承上一次的设置
                    add_scalebar = map_state.scalebar is not None
                else:
                    # 默认添加
                    add_scalebar = True

            if add_compass is None:
                if is_first_visualization:
                    # 首次可视化，默认添加指北针
                    add_compass = True
                elif map_state is not None and hasattr(map_state, 'compass'):
                    # 重新可视化，继承上一次的设置
                    add_compass = map_state.compass is not None
                else:
                    # 默认添加
                    add_compass = True

            result = engine.visualize_comparison(
                generalization_result=generalization_result,
                figsize=(figsize_width, figsize_height),
                dpi=dpi,
                add_scalebar=add_scalebar,
                add_compass=add_compass
            )

            if result['success']:
                # 更新状态中的可视化信息
                if map_state is not None:
                    if map_state.generalization_result is None:
                        map_state.generalization_result = {}

                    map_state.generalization_result['visualization'] = {
                        'filepath': result['filepath'],
                        'filename': result['filename'],
                        'figsize': (figsize_width, figsize_height),
                        'dpi': dpi,
                        'add_scalebar': add_scalebar,
                        'add_compass': add_compass
                    }
                    map_state.generalization_output_path = str(result['filepath'])
                    result_meta = map_state.generalization_result_meta or {}
                    result_meta["visualization"] = {
                        "filepath": result['filepath'],
                        "filename": result['filename'],
                        "dpi": dpi,
                    }
                    map_state.generalization_result_meta = result_meta

                    # 首次可视化时，保存比例尺和指北针的配置到状态中
                    if is_first_visualization:
                        if add_scalebar:
                            map_state.scalebar = {
                                "position": Config.HYPERPARAMETERS.SCALEBAR_POSITION,
                                "units": "km",
                                "length": Config.HYPERPARAMETERS.SCALEBAR_LENGTH
                            }
                        if add_compass:
                            map_state.compass = {
                                "position": Config.HYPERPARAMETERS.COMPASS_POSITION,
                                "size": Config.HYPERPARAMETERS.COMPASS_SIZE
                            }

                    # 如果是重新可视化，创建新版本
                    if is_revisualization:
                        # 创建修改记录
                        description_parts = []
                        if not add_scalebar:
                            description_parts.append("删除比例尺")
                        if not add_compass:
                            description_parts.append("删除指北针")

                        description = "、".join(description_parts) if description_parts else "重新可视化"

                        modification_record = ModificationRecord(
                            action=ModificationAction.UPDATE_MAP_CONFIG,
                            target="visualization",
                            description=description
                        )

                        map_state.create_new_version(
                            modification_record=modification_record,
                            description=description
                        )

                    # 保存更新后的状态
                    state_manager = get_state_manager()
                    state_manager.save_state(map_state)
                    _save_generalization_state(active_session_id, map_state)

                record_tool_trace(
                    session_id=active_session_id,
                    task_id=getattr(get_session_context(active_session_id, create=False), "task_id", None),
                    tool_name="visualize_generalization",
                    args={
                        "figsize_width": figsize_width,
                        "figsize_height": figsize_height,
                        "dpi": dpi,
                        "add_scalebar": add_scalebar,
                        "add_compass": add_compass,
                        "session_id": session_id,
                    },
                    result_summary={"filepath": result.get("filepath"), "filename": result.get("filename")},
                    success=True,
                    duration_ms=int((time.time() - start_time) * 1000),
                )

                session_info = ""
                if map_state:
                    session_info = f"\n会话ID: {map_state.get_session_id()[:8]}...\n版本: v{map_state.get_current_version()}"

                return f"✅ 路网综合可视化完成！对比图已保存: {result['filepath']}{session_info}\n\n任务已完成，对比图展示了综合前后的路网变化。"
            else:
                record_tool_trace(
                    session_id=session_id,
                    task_id=getattr(get_session_context(session_id, create=False), "task_id", None),
                    tool_name="visualize_generalization",
                    args={
                        "figsize_width": figsize_width,
                        "figsize_height": figsize_height,
                        "dpi": dpi,
                        "add_scalebar": add_scalebar,
                        "add_compass": add_compass,
                        "session_id": session_id,
                    },
                    result_summary=result,
                    success=False,
                    error="visualization failed",
                    duration_ms=int((time.time() - start_time) * 1000),
                )
                return f"❌ 可视化失败"

        except Exception as e:
            import traceback
            traceback.print_exc()
            record_tool_trace(
                session_id=session_id,
                task_id=getattr(get_session_context(session_id, create=False), "task_id", None),
                tool_name="visualize_generalization",
                args={
                    "figsize_width": figsize_width,
                    "figsize_height": figsize_height,
                    "dpi": dpi,
                    "add_scalebar": add_scalebar,
                    "add_compass": add_compass,
                    "session_id": session_id,
                },
                result_summary=None,
                success=False,
                error=str(e),
                duration_ms=int((time.time() - start_time) * 1000),
            )
            return f"❌ 可视化失败: {str(e)}"


class ModifyGeneralizationParamsInput(BaseModel):
    """修改路网综合参数输入"""
    session_id: Optional[str] = Field(default=None, description="会话ID")
    source_scale: Optional[int] = Field(default=None, description="源比例尺分母，如500表示1:500")
    target_scale: Optional[int] = Field(default=None, description="目标比例尺分母，如2000表示1:2000")
    algorithm: Optional[str] = Field(default=None, description="综合算法：stroke(Stroke构建)、mesh_density(网眼密度)、hierarchy(层次选取)、gcnn(图卷积神经网络)")
    keep_ratio: Optional[float] = Field(default=None, description="保留比例（0-1之间），优先级高于target_scale")


class ModifyGeneralizationParamsTool(BaseTool):
    """修改路网综合参数工具"""
    name: str = "modify_generalization_params"
    description: str = """
    修改路网综合参数并重新执行综合。用于调整已有的路网综合结果。

    使用场景：
    - 用户对当前综合结果不满意，想要调整参数
    - 用户想尝试不同的算法
    - 用户想调整比例尺或保留比例

    参数说明：
    - source_scale: 源比例尺分母（可选，不指定则使用原值）
    - target_scale: 目标比例尺分母（可选，不指定则使用原值）
    - algorithm: 综合算法（可选，不指定则使用原值）
    - keep_ratio: 保留比例（可选，不指定则使用原值）

    注意：修改参数后会自动重新执行综合，并创建新版本。
    """
    args_schema: Type[BaseModel] = ModifyGeneralizationParamsInput

    def _run(
        self,
        source_scale: Optional[int] = None,
        target_scale: Optional[int] = None,
        algorithm: Optional[str] = None,
        keep_ratio: Optional[float] = None,
        session_id: Optional[str] = None
    ) -> str:
        """执行参数修改"""
        start_time = time.time()
        try:
            active_session_id, map_state, _ = _get_generalization_state(session_id)

            if map_state is None:
                record_tool_trace(
                    session_id=active_session_id,
                    task_id=getattr(get_session_context(active_session_id, create=False), "task_id", None),
                    tool_name="modify_generalization_params",
                    args={
                        "session_id": session_id,
                        "source_scale": source_scale,
                        "target_scale": target_scale,
                        "algorithm": algorithm,
                        "keep_ratio": keep_ratio,
                    },
                    result_summary=None,
                    success=False,
                    error="missing generalization state",
                    duration_ms=int((time.time() - start_time) * 1000),
                )
                return "❌ 没有找到路网综合会话，请先调用 generalize_road_network 工具"

            # 获取当前参数
            current_params = map_state.generalization_params

            # 更新参数（只更新指定的参数）
            new_params = current_params.copy()
            if source_scale is not None:
                new_params['source_scale'] = source_scale
            if target_scale is not None:
                new_params['target_scale'] = target_scale
            if algorithm is not None:
                new_params['algorithm'] = algorithm
            if keep_ratio is not None:
                new_params['keep_ratio'] = keep_ratio

            # 调用 generalize_road_network 工具重新执行
            generalize_tool = GeneralizeRoadNetworkTool()
            result = generalize_tool._run(
                data_file=new_params['data_file'],
                data_directory=new_params['data_directory'],
                source_scale=new_params['source_scale'],
                target_scale=new_params['target_scale'],
                algorithm=new_params['algorithm'],
                keep_ratio=new_params.get('keep_ratio'),
                session_id=active_session_id
            )
            record_tool_trace(
                session_id=active_session_id,
                task_id=getattr(get_session_context(active_session_id, create=False), "task_id", None),
                tool_name="modify_generalization_params",
                args={
                    "session_id": active_session_id,
                    "source_scale": source_scale,
                    "target_scale": target_scale,
                    "algorithm": algorithm,
                    "keep_ratio": keep_ratio,
                },
                result_summary={"new_params": new_params},
                success=not result.startswith("❌"),
                error=result if result.startswith("❌") else None,
                duration_ms=int((time.time() - start_time) * 1000),
            )

            return f"✅ 参数已更新并重新执行综合\n\n{result}\n\n提示：请使用 visualize_generalization 工具查看新的对比图。"

        except Exception as e:
            import traceback
            traceback.print_exc()
            record_tool_trace(
                session_id=session_id,
                task_id=getattr(get_session_context(session_id, create=False), "task_id", None),
                tool_name="modify_generalization_params",
                args={
                    "session_id": session_id,
                    "source_scale": source_scale,
                    "target_scale": target_scale,
                    "algorithm": algorithm,
                    "keep_ratio": keep_ratio,
                },
                result_summary=None,
                success=False,
                error=str(e),
                duration_ms=int((time.time() - start_time) * 1000),
            )
            return f"❌ 修改参数失败: {str(e)}"


GENERALIZATION_TOOLS = [
    GeneralizeRoadNetworkTool(),
    VisualizeGeneralizationTool(),
    ModifyGeneralizationParamsTool(),
]

__all__ = [
    "GeneralizeRoadNetworkInput",
    "GeneralizeRoadNetworkTool",
    "VisualizeGeneralizationInput",
    "VisualizeGeneralizationTool",
    "ModifyGeneralizationParamsInput",
    "ModifyGeneralizationParamsTool",
    "GENERALIZATION_TOOLS",
]
