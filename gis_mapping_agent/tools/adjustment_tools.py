"""Lightweight map adjustment LangChain tools."""

from typing import Optional, Type

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from .unified_mapping_tools import get_unified_tools


class RemoveLayerInput(BaseModel):
    """移除图层输入"""
    layer_name: str = Field(description="要移除的图层名称")


class RemoveLayerTool(BaseTool):
    """移除图层工具"""
    name: str = "remove_layer"
    description: str = "移除指定的图层，隐藏其在地图上的显示并从图例中移除。"
    args_schema: Type[BaseModel] = RemoveLayerInput
    
    def _run(self, layer_name: str) -> str:
        """执行移除图层"""
        tools = get_unified_tools()
        result = tools.remove_layer({"layer_name": layer_name})
        
        if result["success"]:
            return f"✅ {result['message']}"
        else:
            return f"❌ {result['message']}"


class UpdateMapTitleInput(BaseModel):
    """更新地图标题输入"""
    title: str = Field(description="新的地图标题")


class UpdateMapTitleTool(BaseTool):
    """更新地图标题工具"""
    name: str = "update_map_title"
    description: str = "修改地图的标题文字。"
    args_schema: Type[BaseModel] = UpdateMapTitleInput
    
    def _run(self, title: str) -> str:
        """执行更新标题"""
        tools = get_unified_tools()
        result = tools.update_map_title({"title": title})
        
        if result["success"]:
            return f"✅ {result['message']}"
        else:
            return f"❌ {result['message']}"


class ToggleLayerVisibilityInput(BaseModel):
    """切换图层可见性输入"""
    layer_name: str = Field(description="图层名称")
    visible: Optional[bool] = Field(default=None, description="可见性，不提供则自动切换")


class ToggleLayerVisibilityTool(BaseTool):
    """切换图层可见性工具"""
    name: str = "toggle_layer_visibility"
    description: str = "切换图层的显示/隐藏状态。"
    args_schema: Type[BaseModel] = ToggleLayerVisibilityInput
    
    def _run(self, layer_name: str, visible: Optional[bool] = None) -> str:
        """执行切换图层可见性"""
        tools = get_unified_tools()
        params = {"layer_name": layer_name}
        if visible is not None:
            params["visible"] = visible
        
        result = tools.toggle_layer_visibility(params)
        
        if result["success"]:
            return f"✅ {result['message']}"
        else:
            return f"❌ {result['message']}"



class ClearAnnotationsInput(BaseModel):
    """清除注记输入"""
    pass  # 不需要参数


class ClearAnnotationsTool(BaseTool):
    """清除所有注记工具"""
    name: str = "clear_annotations"
    description: str = "清除地图上的所有文字注记。"
    args_schema: Type[BaseModel] = ClearAnnotationsInput

    def _run(self) -> str:
        """执行清除注记"""
        tools = get_unified_tools()
        result = tools.clear_annotations()

        if result["success"]:
            return f"✅ {result['message']}"
        else:
            return f"❌ {result['message']}"


# ==================== 路网综合工具 ====================


__all__ = [
    "RemoveLayerInput", "RemoveLayerTool",
    "UpdateMapTitleInput", "UpdateMapTitleTool",
    "ToggleLayerVisibilityInput", "ToggleLayerVisibilityTool",
    "ClearAnnotationsInput", "ClearAnnotationsTool",
]
