"""数据模型定义"""

from typing import Any, Dict, List, Optional, Union, Literal
from pydantic import BaseModel, Field, field_validator, model_validator
from enum import Enum
import geopandas as gpd
import uuid
from datetime import datetime
from config.hyperparameters import HyperParameters


class GeometryType(str, Enum):
    """几何类型枚举"""
    POINT = "point"
    LINE = "line"
    POLYGON = "polygon"
    MULTIPOINT = "multipoint"
    MULTILINE = "multiline"
    MULTIPOLYGON = "multipolygon"


class CoordinateSystem(str, Enum):
    """坐标系统枚举"""
    WGS84 = "EPSG:4326"
    WEB_MERCATOR = "EPSG:3857"
    UTM_ZONE_49N = "EPSG:32649"  # 中国常用UTM投影
    CHINA_2000 = "EPSG:4490"     # 中国2000坐标系


class MapConfig(BaseModel):
    """地图配置模型"""

    map_id: str = Field(description="地图唯一标识符")
    title: Optional[str] = Field(default=None, description="地图标题")
    extent: List[float] = Field(description="地图范围 [min_lon, min_lat, max_lon, max_lat]")
    crs: CoordinateSystem = Field(default=CoordinateSystem.WGS84, description="坐标参考系统")
    background_color: str = Field(default="white", description="背景颜色")
    figsize: tuple = Field(default=HyperParameters.DEFAULT_FIGSIZE, description="图像尺寸 (width, height)")
    dpi: int = Field(default=HyperParameters.DEFAULT_DPI, description="分辨率")

    # 新增：控制纵横比与尺寸自适应的配置
    maintain_data_aspect: bool = Field(
        default=False, description="是否保持经纬度在图中等比例显示（避免拉伸）"
    )
    fit_figsize_to_extent: bool = Field(
        default=False, description="是否根据数据范围的纵横比自动调整图幅尺寸，减少空白"
    )

    # 图例控制配置
    auto_legend: bool = Field(
        default=True, description="是否自动为添加的图层创建图例项"
    )

    # 地图元素控制配置
    auto_scalebar: bool = Field(
        default=True, description="是否自动添加比例尺"
    )
    auto_compass: bool = Field(
        default=True, description="是否自动添加指北针"
    )

    @field_validator('extent')
    @classmethod
    def validate_extent(cls, v: List[float]) -> List[float]:
        if len(v) != 4:
            raise ValueError("extent必须包含4个值: [min_lon, min_lat, max_lon, max_lat]")
        min_lon, min_lat, max_lon, max_lat = v
        if min_lon >= max_lon or min_lat >= max_lat:
            raise ValueError("extent值无效: min值必须小于max值")
        return v


class LayerStyle(BaseModel):
    """图层样式配置模型"""

    color: str = Field(default="blue", description="颜色")
    alpha: float = Field(default=1.0, ge=0.0, le=1.0, description="透明度")
    linewidth: float = Field(default=1.0, ge=0.0, description="线宽")
    linestyle: str = Field(default="-", description="线型")
    marker: str = Field(default='o', description="标记符号")
    size: float = Field(default=50.0, ge=0.0, description="标记大小")
    edgecolor: Optional[str] = Field(default=None, description="边框颜色")
    facecolor: Optional[str] = Field(default=None, description="填充颜色")
    hatch: Optional[str] = Field(default=None, description="填充图案")
    attribute_column: Optional[str] = Field(default=None, description="用于分级设色的属性列名")
    label_column: Optional[str] = Field(default=None, description="用于标注的属性列名")


class LayerConfig(BaseModel):
    """图层配置模型"""

    layer_id: str = Field(description="图层唯一标识符")
    name: str = Field(description="图层名称")
    geometry_type: GeometryType = Field(description="几何类型")
    data_source: Optional[str] = Field(default=None, description="数据源路径或URL")
    data: Optional[Dict[str, Any]] = Field(default=None, description="内联数据")
    style: LayerStyle = Field(default_factory=LayerStyle, description="图层样式")
    visible: bool = Field(default=True, description="是否可见")
    z_order: int = Field(default=0, description="绘制顺序")
    gdf: Optional[gpd.GeoDataFrame] = None

    class Config:
        arbitrary_types_allowed = True

    @model_validator(mode='after')
    def validate_data_source_or_data(self):
        # 确保data_source和data至少有一个被提供
        if self.data_source is None and self.data is None:
            raise ValueError("必须提供data_source或data中的一个")
        return self


class LegendConfig(BaseModel):
    """图例配置模型"""

    legend_id: str = Field(description="图例唯一标识符")
    title: Optional[str] = Field(default=None, description="图例标题")
    position: Literal["upper right", "upper left", "lower right", "lower left", "center"] = Field(
        default="lower right", description="图例位置"  
    )
    items: List[Dict[str, Any]] = Field(default_factory=list, description="图例项目")
    font_size: float = Field(default=7.0, description="字体大小")  # 从8.0缩小到7.0
    background_color: str = Field(default="white", description="背景颜色")
    border: bool = Field(default=True, description="是否显示边框")


class AnnotationConfig(BaseModel):
    """注记配置模型"""

    annotation_id: str = Field(description="注记唯一标识符")
    text: str = Field(description="注记文本")
    position: List[float] = Field(description="位置坐标 [x, y]")
    font_size: float = Field(default=12.0, description="字体大小")
    font_family: str = Field(default="Arial", description="字体族")
    color: str = Field(default="black", description="文字颜色")
    background_color: Optional[str] = Field(default=None, description="背景颜色")
    rotation: float = Field(default=0.0, description="旋转角度")
    alignment: Literal["left", "center", "right"] = Field(default="center", description="对齐方式")


class ExportConfig(BaseModel):
    """导出配置模型"""

    format: Literal["png", "svg", "pdf", "jpg"] = Field(default="png", description="输出格式")
    filename: str = Field(description="文件名")
    output_dir: Optional[str] = Field(default=None, description="输出目录")
    dpi: Optional[int] = Field(default=None, description="分辨率")
    transparent: bool = Field(default=False, description="是否透明背景")
    bbox_inches: Literal["tight", None] = Field(default="tight", description="边界框设置")


class LegendItem(BaseModel):
    """图例项模型 - 用于自动生成图例"""
    label: str = Field(description="图例项标签")
    type: str = Field(description="图例项类型 ('line' or 'patch')")
    style: Dict[str, Any] = Field(description="图例项样式")


class ModificationAction(str, Enum):
    """修改动作类型枚举"""
    ADD_LAYER = "add_layer"
    REMOVE_LAYER = "remove_layer"
    STYLE_LAYER = "style_layer"
    REORDER_LAYERS = "reorder_layers"
    UPDATE_MAP_CONFIG = "update_map_config"
    ADD_ANNOTATION = "add_annotation"
    REMOVE_ANNOTATION = "remove_annotation"
    UPDATE_ANNOTATION = "update_annotation"  # 新增：修改注记内容
    ADD_SCALEBAR = "add_scalebar"
    UPDATE_SCALEBAR = "update_scalebar"
    ADD_COMPASS = "add_compass"
    UPDATE_COMPASS = "update_compass"
    UPDATE_LEGEND = "update_legend"
    # 新增删除操作
    REMOVE_COMPASS = "remove_compass"
    REMOVE_SCALEBAR = "remove_scalebar"
    TOGGLE_LAYER_VISIBILITY = "toggle_layer_visibility"
    UPDATE_GENERALIZATION_PARAMS = "update_generalization_params"


class ModificationRecord(BaseModel):
    """修改记录模型"""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="修改记录ID")
    action: ModificationAction = Field(description="修改动作类型")
    target: str = Field(description="修改目标（如图层名称）")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="修改参数")
    timestamp: datetime = Field(default_factory=datetime.now, description="修改时间")
    user_request: Optional[str] = Field(default=None, description="用户原始请求")
    description: str = Field(description="修改描述")


class SessionInfo(BaseModel):
    """会话信息模型"""

    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="会话ID")
    session_name: Optional[str] = Field(default=None, description="会话名称")
    created_at: datetime = Field(default_factory=datetime.now, description="会话创建时间")
    last_accessed: datetime = Field(default_factory=datetime.now, description="最后访问时间")
    user_id: Optional[str] = Field(default=None, description="用户ID")


class MapVersion(BaseModel):
    """地图版本信息模型"""

    version: int = Field(default=1, description="版本号")
    parent_version: Optional[int] = Field(default=None, description="父版本号")
    created_at: datetime = Field(default_factory=datetime.now, description="版本创建时间")
    modification_record: Optional[ModificationRecord] = Field(default=None, description="本版本的修改记录")
    description: str = Field(default="", description="版本描述")
    is_current: bool = Field(default=True, description="是否为当前版本")


class MapState(BaseModel):
    """地图状态模型 - 用于跟踪当前地图的完整状态"""

    # 原有字段
    config: MapConfig = Field(description="地图配置")
    layers: List[LayerConfig] = Field(default_factory=list, description="图层列表")
    legends: List[LegendConfig] = Field(default_factory=list, description="图例列表")
    annotations: List[AnnotationConfig] = Field(default_factory=list, description="注记列表")
    scalebar: Optional[Dict[str, Any]] = Field(default=None, description="比例尺配置")
    color_index: int = 0  # 用于自动为图层分配颜色的索引
    compass: Optional[Dict[str, Any]] = Field(default=None, description="指北针配置")
    legend_items: List[LegendItem] = Field(default_factory=list, description="自动图例项列表")
    created_at: Optional[str] = Field(default=None, description="创建时间")
    updated_at: Optional[str] = Field(default=None, description="更新时间")
    output_path: Optional[str] = Field(default=None, description="地图输出路径")

    # 新增：会话和版本管理字段
    session_info: SessionInfo = Field(default_factory=SessionInfo, description="会话信息")
    version_info: MapVersion = Field(default_factory=MapVersion, description="版本信息")
    modification_history: List[ModificationRecord] = Field(default_factory=list, description="修改历史记录")

    # 新增：路网综合相关字段
    is_generalization_task: bool = Field(default=False, description="是否为路网综合任务")
    generalization_algorithm: Optional[str] = Field(default=None, description="路网综合算法")
    generalization_params: Optional[Dict[str, Any]] = Field(default=None, description="路网综合参数")
    generalization_result: Optional[Dict[str, Any]] = Field(default=None, description="路网综合结果")
    generalization_input_path: Optional[str] = Field(default=None, description="路网综合输入路径")
    generalization_output_path: Optional[str] = Field(default=None, description="路网综合输出路径")
    generalization_metrics: Optional[Dict[str, Any]] = Field(default=None, description="路网综合指标")
    generalization_result_meta: Optional[Dict[str, Any]] = Field(default=None, description="路网综合结果元信息")

    def get_session_id(self) -> str:
        """获取会话ID"""
        return self.session_info.session_id

    def get_current_version(self) -> int:
        """获取当前版本号"""
        return self.version_info.version

    def add_modification_record(self, record: ModificationRecord) -> None:
        """添加修改记录"""
        self.modification_history.append(record)
        self.updated_at = datetime.now().isoformat()
        self.session_info.last_accessed = datetime.now()

    def create_new_version(self, modification_record: Optional[ModificationRecord] = None, description: str = "") -> None:
        """创建新版本"""
        # 将当前版本标记为非当前版本
        self.version_info.is_current = False

        # 创建新版本
        new_version = MapVersion(
            version=self.version_info.version + 1,
            parent_version=self.version_info.version,
            modification_record=modification_record,
            description=description,
            is_current=True
        )
        self.version_info = new_version

        if modification_record:
            self.add_modification_record(modification_record)
