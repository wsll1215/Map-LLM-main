"""Basic map LangChain tools."""

from typing import Optional, Type

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from ..utils.config import Config
from ..specs import MapSpec
from .unified_mapping_tools import get_unified_tools


class InitMapInput(BaseModel):
    """初始化地图输入"""
    title: Optional[str] = Field(default=None, description="地图标题")
    background_color: Optional[str] = Field(default="white", description="背景颜色")
    # crs: Optional[str] = Field(default="EPSG:4326", description="坐标参考系统")
    figsize_width: Optional[float] = Field(default=12.0, description="图像宽度")
    figsize_height: Optional[float] = Field(default=8.0, description="图像高度")
    dpi: Optional[int] = Field(default=300, description="分辨率")
    auto_legend: Optional[bool] = Field(default=True, description="是否自动为添加的图层创建图例项")
    auto_scalebar: Optional[bool] = Field(default=True, description="是否自动添加比例尺")
    auto_compass: Optional[bool] = Field(default=True, description="是否自动添加指北针")
    # 内部使用的extent参数，由系统自动注入，用户不需要指定
    extent: Optional[list] = Field(default=None, description="地图范围（系统自动计算，用户无需指定）")


class InitMapTool(BaseTool):
    """初始化地图工具"""
    name: str = "init_map"
    description: str = "初始化地图坐标系和背景色。地图范围由系统自动计算。这是制作地图的第一步，必须首先调用。"
    args_schema: Type[BaseModel] = InitMapInput
    
    def _run(
        self,
        title: Optional[str] = None,
        extent: Optional[list] = None,  # 接收自动注入的extent参数
        background_color: Optional[str] = "white",
        figsize_width: Optional[float] = Config.DEFAULT_FIGSIZE[0],
        figsize_height: Optional[float] = Config.DEFAULT_FIGSIZE[1],
        dpi: Optional[int] = Config.DEFAULT_DPI,
        auto_legend: Optional[bool] = True,
        auto_scalebar: Optional[bool] = True,
        auto_compass: Optional[bool] = True
    ) -> str:
        """执行地图初始化"""
        tools = get_unified_tools()
        map_spec = MapSpec.from_legacy_dict({
            "title": title,
            "crs": Config.DEFAULT_CRS,
            "background_color": background_color,
            "figsize": [figsize_width, figsize_height],
            "dpi": dpi,
            "auto_legend": auto_legend,
            "auto_scalebar": auto_scalebar,
            "auto_compass": auto_compass,
            "extent": extent,
        })

        params = {
            "title": map_spec.title,
            "crs": map_spec.crs or Config.DEFAULT_CRS,
            "background_color": map_spec.background_color,
            "figsize": tuple(map_spec.figsize or [figsize_width, figsize_height]),
            "dpi": map_spec.dpi,
            "auto_legend": map_spec.auto_legend,
            "auto_scalebar": map_spec.auto_scalebar,
            "auto_compass": map_spec.auto_compass
        }

        # 如果extent参数被自动注入，则添加到params中
        if map_spec.extent is not None:
            params["extent"] = map_spec.extent
        
        result = tools.init_map(params)
        
        if result["success"]:
            return f"✅ {result['message']}"
        else:
            return f"❌ {result['message']}"


class AddLayerInput(BaseModel):
    """添加图层输入"""
    name: str = Field(description="图层名称")
    data_path: str = Field(description="数据文件路径")
    geometry_type: Optional[str] = Field(default=None, description="几何类型（可选，不指定则自动检测）")
    visible: Optional[bool] = Field(default=True, description="是否可见")
    add_legend: Optional[bool] = Field(default=None, description="是否为此图层添加图例项，None表示使用地图的全局设置")


class AddLayerTool(BaseTool):
    """添加图层工具"""
    name: str = "add_layer"
    description: str = "添加矢量图层，支持点/线/面几何类型。可以从Shapefile加载数据。geometry_type参数可选，不指定则自动检测。"
    args_schema: Type[BaseModel] = AddLayerInput

    def _run(
        self,
        name: str,
        data_path: str,
        geometry_type: Optional[str] = None,
        visible: Optional[bool] = True,
        add_legend: Optional[bool] = None
    ) -> str:
        """执行添加图层"""
        tools = get_unified_tools()

        params = {
            "name": name,
            "data_path": data_path,
            "geometry_type": geometry_type,
            "visible": visible,
            "add_legend": add_legend
        }
        
        result = tools.add_layer(params)
        
        if result["success"]:
            return f"✅ {result['message']}"
        else:
            return f"❌ {result['message']}"


class StyleLayerInput(BaseModel):
    """设置图层样式输入"""
    layer_name: str = Field(description="图层名称")
    color: Optional[str] = Field(default="blue", description="颜色")
    linewidth: Optional[float] = Field(default=1.0, description="线宽")
    alpha: Optional[float] = Field(default=0.7, description="透明度")
    linestyle: Optional[str] = Field(default="-", description="线型")
    attribute_column: Optional[str] = Field(default=None, description="用于分级设色的属性列名")
    label_column: Optional[str] = Field(default=None, description="用于标注的属性列名")


class StyleLayerTool(BaseTool):
    """设置图层样式工具"""
    name: str = "style_layer"
    description: str = "设置图层样式，包括颜色、线型、透明度等。支持基于属性的分级设色。"
    args_schema: Type[BaseModel] = StyleLayerInput
    
    def _run(
        self,
        layer_name: str,
        color: Optional[str] = "blue",
        linewidth: Optional[float] = 1.0,
        alpha: Optional[float] = 0.7,
        linestyle: Optional[str] = "-",
        attribute_column: Optional[str] = None,
        label_column: Optional[str] = None
    ) -> str:
        """执行样式设置"""
        tools = get_unified_tools()
        
        params = {
            "layer_name": layer_name,
            "color": color,
            "linewidth": linewidth,
            "alpha": alpha,
            "linestyle": linestyle,
            "attribute_column": attribute_column,
            "label_column": label_column
        }
        
        result = tools.style_layer(params)
        
        if result["success"]:
            return f"✅ {result['message']}"
        else:
            return f"❌ {result['message']}"






class AddAnnotationInput(BaseModel):
    """添加注记输入"""
    text: str = Field(description="文本内容")
    fontsize: Optional[int] = Field(default=12, description="字体大小")
    color: Optional[str] = Field(default="black", description="文字颜色")
    ha: Optional[str] = Field(default="center", description="水平对齐")
    va: Optional[str] = Field(default="top", description="垂直对齐")


class AddAnnotationTool(BaseTool):
    """添加注记工具"""
    name: str = "add_annotation"
    description: str = "添加标题和文本注记到地图上。注记将固定显示在横坐标轴下方的中央位置。"
    args_schema: Type[BaseModel] = AddAnnotationInput

    def _run(
        self,
        text: str,
        fontsize: Optional[int] = 12,
        color: Optional[str] = "black",
        ha: Optional[str] = "center",
        va: Optional[str] = "top"
    ) -> str:
        """执行添加注记"""
        tools = get_unified_tools()

        params = {
            "text": text,
            "fontsize": fontsize,
            "color": color,
            "ha": ha,
            "va": va
        }

        result = tools.add_annotation(params)

        if result["success"]:
            return f"✅ {result['message']}"
        else:
            return f"❌ {result['message']}"

class MapSaveInput(BaseModel):
    """保存地图输入"""
    dpi: Optional[int] = Field(default=300, description="分辨率")
    format: Optional[str] = Field(default="png", description="文件格式")
    # filename参数已移除，将由系统自动生成


class MapSaveTool(BaseTool):
    """保存地图工具"""
    name: str = "map_save"
    description: str = "保存最终地图为PNG文件。文件名会自动生成（格式：map_YYYYMMDD_HHMMSS）。这是制作地图的最后一步。"
    args_schema: Type[BaseModel] = MapSaveInput

    def _run(
        self,
        dpi: Optional[int] = Config.DEFAULT_DPI,
        format: Optional[str] = "png"
    ) -> str:
        """执行保存地图"""
        tools = get_unified_tools()

        # 自动生成文件名
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        auto_filename = f"map_{timestamp}"

        params = {
            "filename": auto_filename,
            "output_dir": Config.OUTPUT_DIR,  # 使用配置中的默认输出目录
            "dpi": dpi,
            "format": format
        }

        result = tools.map_save(params)

        if result["success"]:
            return f"✅ {result['message']}"
        else:
            return f"❌ {result['message']}"


# ==================== 新增：增量修改工具 ====================


__all__ = [
    "InitMapInput", "InitMapTool",
    "AddLayerInput", "AddLayerTool",
    "StyleLayerInput", "StyleLayerTool",
    "AddAnnotationInput", "AddAnnotationTool",
    "MapSaveInput", "MapSaveTool",
]
