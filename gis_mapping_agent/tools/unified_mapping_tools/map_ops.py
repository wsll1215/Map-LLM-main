"""Map initialization, layer loading, and styling operations."""

from typing import Any, Dict
import gc
from pathlib import Path

import geopandas as gpd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from ...models.schemas import GeometryType, LayerConfig, LayerStyle, LegendItem, MapConfig, MapState
from ...utils.config import Config
from ...utils.helpers import generate_unique_id, parse_color


def _geometry_type_label(geometry_type: GeometryType) -> str:
    """Return a user-facing Chinese label for a geometry type."""
    if geometry_type == GeometryType.POINT:
        return "点图层"
    if geometry_type == GeometryType.LINE:
        return "线图层"
    return "面图层"


class MapOperationsMixin:
    def init_map(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """初始化地图范围、坐标系和背景色

        Args:
            params: 地图初始化参数
                - title: 地图标题
                - extent: 地图范围 [min_lon, min_lat, max_lon, max_lat]
                - crs: 坐标参考系统，默认 'EPSG:4326'
                - background_color: 背景颜色，默认 'white'
                - figsize: 图像尺寸 (width, height)，默认 (12, 8)
                - dpi: 分辨率，默认 300

        Returns:
            Dict: 操作结果
        """
        try:
            self.logger.info("开始初始化地图")

            # 解析参数
            title = params.get('title')
            # extent参数处理：如果没有提供extent，使用默认的全球范围
            # 注意：在智能体模式下，extent会通过_execute_tool自动注入
            extent = params.get('extent')
            if extent is None:
                extent = [-180, -90, 180, 90]
                self.logger.info("未提供extent参数，使用默认全球范围")
        
            crs = params.get('crs', 'EPSG:4326')
            background_color = params.get('background_color', 'white')
            figsize = params.get('figsize', (12, 8))
            dpi = params.get('dpi', Config.HYPERPARAMETERS.INIT_MAP_DPI)
            map_scale = params.get('map_scale', Config.HYPERPARAMETERS.MAP_SCALE)  # 地图缩放比例，1.0为原始大小
            margin_ratio = params.get('margin_ratio', Config.HYPERPARAMETERS.MAP_MARGIN_RATIO)  # 边距比例，0.0为无边距（因为auto_extent_calculator已经添加了边距）
            auto_legend = params.get('auto_legend', True)  # 是否自动添加图例
            auto_scalebar = params.get('auto_scalebar', True)  # 是否自动添加比例尺
            auto_compass = params.get('auto_compass', True)  # 是否自动添加指北针

            # 验证范围
            if len(extent) != 4:
                raise ValueError("extent必须包含4个值: [min_lon, min_lat, max_lon, max_lat]")

            min_lon, min_lat, max_lon, max_lat = extent
            if min_lon >= max_lon or min_lat >= max_lat:
                raise ValueError("地图范围无效：最小值必须小于最大值")

            # 应用地图缩放和边距
            adjusted_extent = self._apply_map_scaling(extent, map_scale, margin_ratio)

            # 清理之前的图形对象，释放内存
            if self.figure:
                plt.close(self.figure)
                self.figure = None
                self.ax = None

            # 强制垃圾回收
            gc.collect()

            # 创建matplotlib图形，为框外文字留出适当空间
            plt.ioff()  # 关闭交互模式
            self.figure = plt.figure(figsize=figsize, dpi=dpi)

            # 调整布局，为框外标题和注释留出空间
            # left, bottom, width, height (相对于整个图形的比例)
            self.ax = self.figure.add_subplot(111)
            self.figure.subplots_adjust(left=0.08, right=0.95, top=0.92, bottom=0.15)

            # 使用调整后的范围设置坐标轴
            adj_min_lon, adj_min_lat, adj_max_lon, adj_max_lat = adjusted_extent
            self.ax.set_xlim(adj_min_lon, adj_max_lon)
            self.ax.set_ylim(adj_min_lat, adj_max_lat)

            # 强制设定地理坐标系的宽高比为相等，这是解决bbox_inches='tight'问题的关键
            self.ax.set_aspect('equal')

            # 设置背景色
            self.ax.set_facecolor(background_color)

            # 设置等比例显示，保持地图的正确纵横比
            self.ax.set_aspect('equal', adjustable='box')

            # 设置合适的坐标轴刻度（这会同时设置网格）
            self._setup_axis_ticks(adj_min_lon, adj_max_lon, adj_min_lat, adj_max_lat)

            if title:
                title_props = {'fontsize': 14, 'fontweight': 'bold'}
                if self.chinese_font:
                    title_props['fontfamily'] = self.chinese_font
                # 将标题放在图表顶部
                self.figure.suptitle(title, **title_props)

            # 创建地图配置
            map_config = MapConfig(
                map_id=generate_unique_id(),
                title=title,
                extent=extent,
                crs=crs,
                background_color=background_color,
                figsize=figsize,
                dpi=dpi,
                auto_legend=auto_legend,
                auto_scalebar=auto_scalebar,
                auto_compass=auto_compass
            )

            # 创建地图状态
            self.current_map_state = MapState(
                config=map_config,
                layers=[],
                legends=[],
                annotations=[],
                legend_items=[]  # 初始化自动图例项列表
            )

            self.logger.debug(
                f"创建新地图状态，ID: {id(self.current_map_state)}, 图层数: {len(self.current_map_state.layers)}"
            )

            # 根据配置决定是否自动添加比例尺和指北针
            if auto_scalebar and self.current_map_state.scalebar is None:
                self.current_map_state.scalebar = {
                    "length": Config.HYPERPARAMETERS.SCALEBAR_LENGTH,
                    "position": Config.HYPERPARAMETERS.SCALEBAR_POSITION,
                    "units": Config.HYPERPARAMETERS.SCALEBAR_UNITS,
                }
            if auto_compass and self.current_map_state.compass is None:
                self.current_map_state.compass = {
                    "position": Config.HYPERPARAMETERS.COMPASS_POSITION,
                    "size": Config.HYPERPARAMETERS.COMPASS_SIZE,
                }

            message = f"地图初始化成功！范围: [{min_lon:.2f}, {min_lat:.2f}, {max_lon:.2f}, {max_lat:.2f}]"
            if title:
                message += f", 标题: {title}"

            self.logger.info(message)
            return {
                "success": True,
                "message": message,
                "map_id": map_config.map_id
            }

        except Exception as e:
            error_msg = f"地图初始化失败: {str(e)}"
            self.logger.error(error_msg)
            return {
                "success": False,
                "message": error_msg,
                "error": str(e)
            }

    def add_layer(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """添加矢量图层（支持点/线/面）

        Args:
            params: 图层参数
                - name: 图层名称
                - data_path: 数据文件路径（支持shapefile）
                - geometry_type: 几何类型 ('point', 'line', 'polygon')
                - visible: 是否可见，默认True

        Returns:
            Dict: 操作结果
        """
        try:
            if not self.current_map_state:
                raise ValueError("请先初始化地图")

            self.logger.info("开始添加图层")

            # 解析参数
            name = params.get('name', 'unnamed_layer')
            data_path = params.get('data_path')
            geometry_type = params.get('geometry_type', None)  # 改为None，稍后自动检测
            visible = params.get('visible', True)
            add_legend = params.get('add_legend', None)  # None表示使用地图的全局设置
            style = params.get('style', None)  # 样式参数

            if not data_path:
                raise ValueError("必须提供data_path参数")

            # 智能路径处理
            # 如果data_path已经是绝对路径，直接使用
            if Path(data_path).is_absolute():
                file_path = Path(data_path)
            # 如果以"data\"或"data/"开头（如"data\data1\..."或"data/data1/..."），说明是相对于PROJECT_ROOT的路径
            elif data_path.startswith("data\\") or data_path.startswith("data/"):
                file_path = Config.PROJECT_ROOT / data_path
            else:
                # 其他情况：可能是相对路径或只是文件名
                # 首先尝试作为相对于PROJECT_ROOT的路径
                potential_path = Config.PROJECT_ROOT / data_path
                if potential_path.exists():
                    file_path = potential_path
                else:
                    # 如果不存在，尝试拼接基础数据目录
                    base_data_dir = Config.DATA_DIRECTORY_BASE
                    file_path = base_data_dir / data_path

                    # 如果文件仍不存在，尝试在data1目录中查找（针对广东数据的默认行为）
                    if not file_path.exists():
                        # 检查是否只是文件名（不包含路径分隔符）
                        if '\\' not in data_path and '/' not in data_path:
                            # 尝试在data1目录中查找
                            data1_path = base_data_dir / "data1" / data_path
                            if data1_path.exists():
                                self.logger.info(f"在data1目录中找到文件: {data_path}")
                                file_path = data1_path

            # 如果路径仍然不存在，则报错
            if not file_path.exists():
                raise FileNotFoundError(f"数据路径不存在: {file_path}")

            # 将绝对路径转换为相对路径（相对于PROJECT_ROOT）
            try:
                rel_path = file_path.relative_to(Config.PROJECT_ROOT)
                data_source_to_save = str(rel_path).replace('\\', '/')
                self.logger.debug(f"数据路径转换为相对路径: {data_source_to_save}")
            except ValueError:
                # 如果无法转换为相对路径，保持绝对路径
                data_source_to_save = str(file_path)
                self.logger.warning(f"无法将路径转换为相对路径，使用绝对路径: {data_source_to_save}")

            # 使用绝对路径读取文件
            gdf = gpd.read_file(str(file_path))

            if gdf.empty:
                # raise ValueError(f"数据文件为空: {data_path}")
                raise ValueError(f"数据文件为空")

            # 确保坐标系一致
            target_crs = self.current_map_state.config.crs
            # 如果target_crs是CoordinateSystem枚举，转换为字符串
            if hasattr(target_crs, 'value'):
                target_crs = target_crs.value

            if gdf.crs != target_crs:
                gdf = gdf.to_crs(target_crs)

            # 自动检测几何类型（如果未指定）
            if geometry_type is None:
                # 获取数据中最常见的几何类型
                geom_types = gdf.geometry.geom_type.value_counts()
                most_common_geom = geom_types.index[0]

                # 映射到我们的几何类型枚举
                if most_common_geom in ['Point', 'MultiPoint']:
                    geometry_type = GeometryType.POINT
                elif most_common_geom in ['LineString', 'MultiLineString']:
                    geometry_type = GeometryType.LINE
                elif most_common_geom in ['Polygon', 'MultiPolygon']:
                    geometry_type = GeometryType.POLYGON
                else:
                    geometry_type = GeometryType.POLYGON  # 默认为多边形

                self.logger.info(f"自动识别为{_geometry_type_label(geometry_type)}")
            else:
                # 如果是字符串，转换为枚举
                if isinstance(geometry_type, str):
                    geometry_type = GeometryType(geometry_type.lower())

            # 不在此处绘制图层，仅加载数据。所有绘制操作由 _redraw_map 处理。

            # 自动设置z_order以确保点在面上
            z_order = 1  # 默认为面
            if geometry_type == GeometryType.LINE:
                z_order = 2
            elif geometry_type == GeometryType.POINT:
                z_order = 3

            # 创建图层配置（使用相对路径保存）
            layer_config = LayerConfig(
                layer_id=generate_unique_id(),
                name=name,
                geometry_type=geometry_type,
                data_source=data_source_to_save,
                visible=visible,
                gdf=gdf,
                z_order=z_order
            )

            # 处理样式：如果提供了样式参数，使用它；否则自动分配颜色
            if style and isinstance(style, dict):
                # 使用提供的样式
                for key, value in style.items():
                    if hasattr(layer_config.style, key) and value is not None:
                        # 如果是颜色相关的参数，使用parse_color处理
                        if key in ['color', 'edgecolor', 'facecolor'] and isinstance(value, str):
                            value = parse_color(value)
                        setattr(layer_config.style, key, value)
                self.logger.info(f"已应用图层 '{name}' 的样式设置")
            else:
                # 智能颜色分配：为新图层自动分配不同颜色
                color_index = self.current_map_state.color_index
                new_color = self.COLOR_PALETTE[color_index % len(self.COLOR_PALETTE)]
                layer_config.style.color = new_color
                self.current_map_state.color_index += 1
                self.logger.info(f"已为图层 '{name}' 自动设置显示样式")

            # 为点图层优化显示效果（只在没有提供样式时）
            if geometry_type == GeometryType.POINT and not (style and isinstance(style, dict)):
                layer_config.style.size = 100.0  # 增大点的大小，使其更明显
                layer_config.style.marker = 'o'  # 使用圆形标记
                layer_config.style.edgecolor = 'white'  # 添加白色边框增强对比度
                layer_config.style.linewidth = 1.5  # 设置边框宽度
                self.logger.debug(
                    f"为点图层 '{name}' 优化显示效果: 大小=100, marker={layer_config.style.marker}, 边框={layer_config.style.edgecolor}"
                )
                # ✅ 调试：验证样式是否正确设置
                self.logger.debug(f"点图层样式详情: {layer_config.style.model_dump()}")

            # 添加到地图状态
            # self.logger.info(f"添加图层前，地图状态ID: {id(self.current_map_state)}, 图层数: {len(self.current_map_state.layers)}")
            self.current_map_state.layers.append(layer_config)
            # self.logger.info(f"添加图层后，地图状态ID: {id(self.current_map_state)}, 图层数: {len(self.current_map_state.layers)}")

            # 决定是否添加图例项
            should_add_legend = add_legend if add_legend is not None else self.current_map_state.config.auto_legend

            legend_message = ""
            if should_add_legend:
                # 自动添加图例项，使用中文名称
                chinese_name = self.LAYER_NAME_MAPPING.get(name, name)
                # 根据几何类型设置正确的图例项类型
                if geometry_type == GeometryType.LINE:
                    legend_type = 'line'
                elif geometry_type == GeometryType.POINT:
                    legend_type = 'point'
                else:  # POLYGON, MULTIPOLYGON
                    legend_type = 'patch'

                # ✅ 调试：记录图例项的样式
                style_dict = layer_config.style.model_dump()
                self.logger.debug(f"创建图例项 '{chinese_name}' (type={legend_type}), 样式: {style_dict}")

                legend_item = LegendItem(
                    label=chinese_name,
                    type=legend_type,
                    style=style_dict
                )
                self.current_map_state.legend_items.append(legend_item)
                legend_message = "，并自动添加图例项"

            message = f"成功添加图层: {name} ({_geometry_type_label(geometry_type)}，{len(gdf)} 个要素){legend_message}"
            self.logger.info(message)

            return {
                "success": True,
                "message": message,
                "layer_id": layer_config.layer_id,
                "feature_count": len(gdf)
            }

        except Exception as e:
            error_msg = f"添加图层失败: {str(e)}"
            self.logger.error(error_msg)
            return {
                "success": False,
                "message": error_msg,
                "error": str(e)
            }

    def style_layer(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """设置图层样式并立即重绘地图"""
        try:
            if not self.current_map_state:
                raise ValueError("请先初始化地图")
            layer_name = params.get('layer_name')
            if not layer_name:
                raise ValueError("必须提供layer_name参数")

            target_layer = next((l for l in self.current_map_state.layers if l.name == layer_name), None)
            if not target_layer:
                raise ValueError(f"未找到图层: {layer_name}")

            # 更新样式配置，并根据几何类型过滤无效参数
            style_params = target_layer.style.model_dump()
            valid_params = {k: v for k, v in params.items() if v is not None and k != 'layer_name'}

            if target_layer.geometry_type == GeometryType.POINT:
                allowed_keys = {'color', 'alpha', 'marker', 'size', 'attribute_column', 'label_column', 'edgecolor'}
            elif target_layer.geometry_type == GeometryType.LINE:
                allowed_keys = {'color', 'alpha', 'linewidth', 'linestyle', 'attribute_column', 'label_column'}
            else: # Polygon
                allowed_keys = {'color', 'alpha', 'edgecolor', 'facecolor', 'hatch', 'linewidth', 'attribute_column', 'label_column'}

            filtered_params = {k: v for k, v in valid_params.items() if k in allowed_keys}

            # 处理颜色参数，使用parse_color转换中文颜色名称
            for key in ['color', 'edgecolor', 'facecolor']:
                if key in filtered_params and isinstance(filtered_params[key], str):
                    filtered_params[key] = parse_color(filtered_params[key])

            style_params.update(filtered_params)
            new_style = LayerStyle(**style_params)
            target_layer.style = new_style

            # 自动更新图例项
            chinese_name = self.LAYER_NAME_MAPPING.get(layer_name, layer_name)
            for item in self.current_map_state.legend_items:
                if item.label == chinese_name:
                    item.style = new_style.model_dump()
                    self.logger.info(f"自动更新图层 '{layer_name}' 的图例项")
                    break

            # 重新绘制地图以应用最新样式
            self._redraw_map()

            message = f"成功更新图层样式: {layer_name}"
            self.logger.info(message)
            return {"success": True, "message": message, "layer_id": target_layer.layer_id}

        except Exception as e:
            error_msg = f"设置图层样式失败: {str(e)}"
            self.logger.error(error_msg)
            return {"success": False, "message": error_msg, "error": str(e)}
