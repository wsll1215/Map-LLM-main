"""Map element LangChain tools."""

from typing import Optional, Type

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from ..state import get_generalization_state, save_generalization_context
from ..utils.config import Config
from .generalization_tools import VisualizeGeneralizationTool
from .unified_mapping_tools import get_unified_tools


def _get_generalization_state(session_id: Optional[str]):
    _, map_state, result = get_generalization_state(session_id)
    return map_state, result


def _save_generalization_state(session_id: Optional[str], map_state) -> None:
    save_generalization_context(
        session_id or map_state.get_session_id(),
        map_state=map_state,
        generalization_result=map_state.generalization_result,
        generalization_params=map_state.generalization_params,
    )


class AddScalebarInput(BaseModel):
    """添加比例尺输入"""
    session_id: Optional[str] = Field(default=None, description="会话ID")
    length: Optional[float] = Field(default=Config.HYPERPARAMETERS.SCALEBAR_LENGTH, description="比例尺长度")
    position: Optional[list] = Field(default=Config.HYPERPARAMETERS.SCALEBAR_POSITION, description="位置")
    units: Optional[str] = Field(default=Config.HYPERPARAMETERS.SCALEBAR_UNITS, description="单位")


class AddScalebarTool(BaseTool):
    """添加比例尺工具"""
    name: str = "add_scalebar"
    description: str = """添加比例尺，显示地图比例信息。

    注意：对于路网综合任务，此工具会自动触发重新可视化并保存地图，调用后任务即完成，无需再调用 visualize_generalization 工具。
    """
    args_schema: Type[BaseModel] = AddScalebarInput

    def _run(
        self,
        length: Optional[float] = Config.HYPERPARAMETERS.SCALEBAR_LENGTH,
        position: Optional[list] = None,
        units: Optional[str] = Config.HYPERPARAMETERS.SCALEBAR_UNITS,
        session_id: Optional[str] = None
    ) -> str:
        """执行添加比例尺"""
        tools = get_unified_tools()
        generalization_state, generalization_result = _get_generalization_state(session_id)

        if generalization_state is not None:
            scalebar_params = {
                "position": position or Config.HYPERPARAMETERS.SCALEBAR_POSITION,
                "units": units,
                "length": length
            }
            generalization_state.scalebar = scalebar_params
            _save_generalization_state(session_id, generalization_state)

            # 自动触发重新可视化
            if generalization_result is not None or generalization_state.generalization_result is not None:
                visualize_tool = VisualizeGeneralizationTool()
                result = visualize_tool._run(session_id=session_id)
                return f"✅ 成功添加比例尺到路网综合地图，已自动重新可视化并保存\n\n{result}\n\n任务已完成，无需再调用其他工具。"

            return f"✅ 成功添加比例尺到路网综合地图（需要调用 visualize_generalization 工具查看效果）"

        # 传统制图任务：使用 tools.add_scalebar
        params = {
            "length": length,
            "position": position or Config.HYPERPARAMETERS.SCALEBAR_POSITION,
            "units": units
        }

        result = tools.add_scalebar(params)

        if result["success"]:
            return f"✅ {result['message']}"
        else:
            return f"❌ {result['message']}"


class AddCompassInput(BaseModel):
    """添加指北针输入"""
    session_id: Optional[str] = Field(default=None, description="会话ID")
    position: Optional[list] = Field(default=Config.HYPERPARAMETERS.COMPASS_POSITION, description="位置")
    size: Optional[float] = Field(default=Config.HYPERPARAMETERS.COMPASS_SIZE, description="大小")


class AddCompassTool(BaseTool):
    """添加指北针工具"""
    name: str = "add_compass"
    description: str = """添加指北针，显示地图方向。

    注意：对于路网综合任务，此工具会自动触发重新可视化并保存地图，调用后任务即完成，无需再调用 visualize_generalization 工具。
    """
    args_schema: Type[BaseModel] = AddCompassInput

    def _run(
        self,
        position: Optional[list] = None,
        size: Optional[float] = Config.HYPERPARAMETERS.COMPASS_SIZE,
        session_id: Optional[str] = None
    ) -> str:
        """执行添加指北针"""
        tools = get_unified_tools()
        generalization_state, generalization_result = _get_generalization_state(session_id)

        if generalization_state is not None:
            compass_params = {
                "position": position or Config.HYPERPARAMETERS.COMPASS_POSITION,
                "size": size
            }
            generalization_state.compass = compass_params
            _save_generalization_state(session_id, generalization_state)

            # 自动触发重新可视化
            if generalization_result is not None or generalization_state.generalization_result is not None:
                visualize_tool = VisualizeGeneralizationTool()
                result = visualize_tool._run(session_id=session_id)
                return f"✅ 成功添加指北针到路网综合地图，已自动重新可视化并保存\n\n{result}\n\n任务已完成，无需再调用其他工具。"

            return f"✅ 成功添加指北针到路网综合地图（需要调用 visualize_generalization 工具查看效果）"

        # 传统制图任务：使用 tools.add_compass
        params = {
            "position": position or Config.HYPERPARAMETERS.COMPASS_POSITION,
            "size": size
        }

        result = tools.add_compass(params)

        if result["success"]:
            return f"✅ {result['message']}"
        else:
            return f"❌ {result['message']}"



class RemoveScalebarInput(BaseModel):
    """删除比例尺输入"""
    session_id: Optional[str] = Field(default=None, description="会话ID")


class RemoveScalebarTool(BaseTool):
    """删除比例尺工具"""
    name: str = "remove_scalebar"
    description: str = """删除地图上的比例尺。

    注意：对于路网综合任务，此工具会自动触发重新可视化并保存地图，调用后任务即完成，无需再调用 visualize_generalization 工具。
    """
    args_schema: Type[BaseModel] = RemoveScalebarInput

    def _run(self, session_id: Optional[str] = None) -> str:
        """执行删除比例尺"""
        generalization_state, generalization_result = _get_generalization_state(session_id)

        if generalization_state is not None:
            if generalization_state.scalebar is None:
                return f"❌ 地图中没有比例尺"
            generalization_state.scalebar = None
            _save_generalization_state(session_id, generalization_state)

            # 自动触发重新可视化
            if generalization_result is not None or generalization_state.generalization_result is not None:
                visualize_tool = VisualizeGeneralizationTool()
                result = visualize_tool._run(session_id=session_id)
                return f"✅ 成功删除路网综合地图的比例尺，已自动重新可视化并保存\n\n{result}\n\n任务已完成，无需再调用其他工具。"

            return f"✅ 成功删除路网综合地图的比例尺（需要调用 visualize_generalization 工具查看效果）"

        # 传统制图任务：使用 tools.remove_scalebar
        tools = get_unified_tools()
        result = tools.remove_scalebar({})

        if result["success"]:
            return f"✅ {result['message']}"
        else:
            return f"❌ {result['message']}"


class RemoveCompassInput(BaseModel):
    """删除指北针输入"""
    session_id: Optional[str] = Field(default=None, description="会话ID")


class RemoveCompassTool(BaseTool):
    """删除指北针工具"""
    name: str = "remove_compass"
    description: str = """删除地图上的指北针。

    注意：对于路网综合任务，此工具会自动触发重新可视化并保存地图，调用后任务即完成，无需再调用 visualize_generalization 工具。
    """
    args_schema: Type[BaseModel] = RemoveCompassInput

    def _run(self, session_id: Optional[str] = None) -> str:
        """执行删除指北针"""
        generalization_state, generalization_result = _get_generalization_state(session_id)

        if generalization_state is not None:
            if generalization_state.compass is None:
                return f"❌ 地图中没有指北针"
            generalization_state.compass = None
            _save_generalization_state(session_id, generalization_state)

            # 自动触发重新可视化
            if generalization_result is not None or generalization_state.generalization_result is not None:
                visualize_tool = VisualizeGeneralizationTool()
                result = visualize_tool._run(session_id=session_id)
                return f"✅ 成功删除路网综合地图的指北针，已自动重新可视化并保存\n\n{result}\n\n任务已完成，无需再调用其他工具。"

            return f"✅ 成功删除路网综合地图的指北针（需要调用 visualize_generalization 工具查看效果）"

        # 传统制图任务：使用 tools.remove_compass
        tools = get_unified_tools()
        result = tools.remove_compass({})

        if result["success"]:
            return f"✅ {result['message']}"
        else:
            return f"❌ {result['message']}"



__all__ = [
    "AddScalebarInput", "AddScalebarTool",
    "AddCompassInput", "AddCompassTool",
    "RemoveScalebarInput", "RemoveScalebarTool",
    "RemoveCompassInput", "RemoveCompassTool",
]
