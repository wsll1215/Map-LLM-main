"""Map initialization, layer loading, and styling operations."""

from typing import Any, Dict
import gc
import hashlib
from pathlib import Path

import geopandas as gpd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from ...models.schemas import GeometryType, LayerConfig, LayerStyle, LegendItem, MapConfig, MapState
from ...utils.config import Config
from ...utils.helpers import generate_unique_id, parse_color
from ...rendering.classification import build_render_spec
from ...data_sources.metadata import source_metadata_from_path


def _geometry_type_label(geometry_type: GeometryType) -> str:
    """Return a user-facing Chinese label for a geometry type."""
    if geometry_type == GeometryType.POINT:
        return "点图层"
    if geometry_type == GeometryType.LINE:
        return "线图层"
    return "面图层"


def _is_global_placeholder_extent(extent: Any) -> bool:
    """Return whether an extent is the init-map global fallback."""
    if not isinstance(extent, (list, tuple)) or len(extent) != 4:
        return False
    try:
        min_x, min_y, max_x, max_y = [float(value) for value in extent]
    except (TypeError, ValueError):
        return False
    return min_x <= -180 and min_y <= -90 and max_x >= 180 and max_y >= 90


def _load_layer_data(params: Dict[str, Any]):
    """Load runtime data from Dataset/PostGIS; files remain import-only input."""
    source_meta = params.get("data_source_meta") or {}
    dataset_id = source_meta.get("dataset_id")
    if not dataset_id:
        from mapping.dataset_reader import DatasetReadError

        raise DatasetReadError(
            "运行时图层必须使用已注册的 dataset_id；文件只能用于显式导入",
            code="dataset_not_registered",
        )
    from mapping.dataset_reader import read_dataset_features

    reader_kwargs = {}
    scope_geometry = source_meta.get("scope_geometry")
    if scope_geometry is not None:
        reader_kwargs["clip_geometry"] = scope_geometry
    return (
        read_dataset_features(str(dataset_id), **reader_kwargs),
        f"dataset://{dataset_id}",
    )


def _load_import_data(params: Dict[str, Any]):
    """Read an explicit file as an import step, never as a runtime dataset."""
    data_path = params.get("data_path")
    if not data_path:
        raise ValueError("显式导入必须提供 data_path")
    if Path(data_path).is_absolute():
        file_path = Path(data_path)
    elif str(data_path).startswith(("data\\", "data/")):
        file_path = Config.PROJECT_ROOT / data_path
    else:
        potential_path = Config.PROJECT_ROOT / data_path
        file_path = potential_path if potential_path.exists() else Config.DATA_DIRECTORY_BASE / data_path
        if not file_path.exists() and "\\" not in data_path and "/" not in data_path:
            file_path = Config.DATA_DIRECTORY_BASE / "data1" / data_path
    if not file_path.exists():
        raise FileNotFoundError(f"数据路径不存在: {file_path}")
    try:
        data_source = str(file_path.relative_to(Config.PROJECT_ROOT)).replace("\\", "/")
    except ValueError:
        data_source = str(file_path)
    return gpd.read_file(str(file_path)), data_source


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
            # 智能体必须先完成地点/数据源解析，再注入经过验证的范围。
            extent = params.get('extent')
            if extent is None:
                return {
                    "success": False,
                    "message": "缺少经过验证的地图范围，无法初始化地图",
                    "error_code": "clarification_required",
                    "recoverable": True,
                    "retryable": False,
                    "next_action": "provide_location",
                }
        
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
            source_meta = params.get("data_source_meta") or {}
            dataset_id = params.get("dataset_id") or source_meta.get("dataset_id")
            data_path = None if dataset_id else params.get('data_path')
            geometry_type = params.get('geometry_type', None)  # 改为None，稍后自动检测
            visible = params.get('visible', True)
            add_legend = params.get('add_legend', None)  # None表示使用地图的全局设置
            style = params.get('style', None)  # 样式参数

            if not dataset_id and not data_path:
                raise ValueError("必须提供 dataset_id 或显式 data_path 参数")

            if dataset_id:
                file_path = None
                data_source_to_save = f"dataset://{dataset_id}"
            else:
                # Explicit imports are the only path-based operation.
                if Path(data_path).is_absolute():
                    file_path = Path(data_path)
                elif data_path.startswith("data\\") or data_path.startswith("data/"):
                    file_path = Config.PROJECT_ROOT / data_path
                else:
                    potential_path = Config.PROJECT_ROOT / data_path
                    if potential_path.exists():
                        file_path = potential_path
                    else:
                        base_data_dir = Config.DATA_DIRECTORY_BASE
                        file_path = base_data_dir / data_path
                        if not file_path.exists():
                            if '\\' not in data_path and '/' not in data_path:
                                data1_path = base_data_dir / "data1" / data_path
                                if data1_path.exists():
                                    self.logger.info(f"在data1目录中找到文件: {data_path}")
                                    file_path = data1_path

                if not file_path.exists():
                    raise FileNotFoundError(f"数据路径不存在: {file_path}")

                try:
                    rel_path = file_path.relative_to(Config.PROJECT_ROOT)
                    data_source_to_save = str(rel_path).replace('\\', '/')
                    self.logger.debug(f"数据路径转换为相对路径: {data_source_to_save}")
                except ValueError:
                    # 如果无法转换为相对路径，保持绝对路径
                    data_source_to_save = str(file_path)
                    self.logger.warning(f"无法将路径转换为相对路径，使用绝对路径: {data_source_to_save}")

            if dataset_id:
                gdf = _load_layer_data(params)[0]
            else:
                # Reading a path is an import operation only. Normalize it
                # first, then read the authoritative DatasetFeature rows.
                imported_frame = gpd.read_file(str(file_path))
                from mapping.dataset_reader import register_geodataframe_dataset

                try:
                    relative_source = file_path.relative_to(Config.PROJECT_ROOT).as_posix()
                except ValueError:
                    relative_source = file_path.as_posix()
                role = str(
                    params.get("role")
                    or (params.get("data_source_meta") or {}).get("role")
                    or name
                )
                source_type = (params.get("data_source_meta") or {}).get(
                    "source_type",
                    "local" if file_path.is_relative_to(Config.DATA_DIRECTORY_BASE) else "upload",
                )
                dataset_id = "import-" + hashlib.sha1(
                    f"{source_type}:{relative_source}".encode("utf-8")
                ).hexdigest()[:24]
                register_geodataframe_dataset(
                    imported_frame,
                    dataset_id=dataset_id,
                    name=name,
                    role=role,
                    source_type=source_type,
                    local_path=relative_source,
                    provider=(params.get("data_source_meta") or {}).get("provider"),
                    source_url=(params.get("data_source_meta") or {}).get("source_url"),
                    attribution=(params.get("data_source_meta") or {}).get("attribution"),
                )
                gdf, data_source_to_save = _load_layer_data(
                    {"data_source_meta": {"dataset_id": dataset_id}}
                )

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

            # A plain request such as "绘制北京地图" may initialize the map
            # before the model resolves the shapefile. Replace the global
            # placeholder with the first layer's real bounds so the rendered
            # map is geographically meaningful instead of mostly blank.
            current_extent = self.current_map_state.config.extent
            if _is_global_placeholder_extent(current_extent):
                min_x, min_y, max_x, max_y = [float(value) for value in gdf.total_bounds]
                if min_x < max_x and min_y < max_y:
                    x_margin = (max_x - min_x) * 0.05
                    y_margin = (max_y - min_y) * 0.05
                    self.current_map_state.config.extent = [
                        min_x - x_margin,
                        min_y - y_margin,
                        max_x + x_margin,
                        max_y + y_margin,
                    ]
                    self.logger.info(
                        "地图范围未明确指定，已根据图层数据自动调整为: %s",
                        self.current_map_state.config.extent,
                    )

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
            supplied_source_meta = dict(params.get("data_source_meta") or {})
            source_meta_base = (
                {"dataset_id": dataset_id}
                if dataset_id
                else source_metadata_from_path(data_source_to_save)
            )
            layer_config = LayerConfig(
                layer_id=generate_unique_id(),
                name=name,
                geometry_type=geometry_type,
                data_source=data_source_to_save,
                visible=visible,
                gdf=gdf,
                z_order=z_order,
                feature_count=len(gdf),
                extent=[float(value) for value in gdf.total_bounds],
                data_source_meta={
                    **source_meta_base,
                    **supplied_source_meta,
                },
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

                if geometry_type in [GeometryType.POLYGON, GeometryType.MULTIPOLYGON]:
                    layer_config.style.facecolor = '#DDECCF'
                    layer_config.style.edgecolor = '#334155'
                    layer_config.style.linewidth = 1.1

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

            if layer_config.style.attribute_column:
                layer_config.render_spec = build_render_spec(
                    gdf,
                    layer_config.style.attribute_column,
                    layer_config.style.classification_method,
                    layer_config.style.classification_classes,
                    no_data_color=layer_config.style.no_data_color,
                )

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
                allowed_keys = {'color', 'alpha', 'marker', 'size', 'attribute_column', 'label_column', 'edgecolor', 'classification_method', 'classification_classes', 'no_data_color'}
            elif target_layer.geometry_type == GeometryType.LINE:
                allowed_keys = {'color', 'alpha', 'linewidth', 'linestyle', 'attribute_column', 'label_column', 'classification_method', 'classification_classes', 'no_data_color'}
            else: # Polygon
                allowed_keys = {'color', 'alpha', 'edgecolor', 'facecolor', 'hatch', 'linewidth', 'attribute_column', 'label_column', 'classification_method', 'classification_classes', 'no_data_color'}

            filtered_params = {k: v for k, v in valid_params.items() if k in allowed_keys}

            # 处理颜色参数，使用parse_color转换中文颜色名称
            for key in ['color', 'edgecolor', 'facecolor']:
                if key in filtered_params and isinstance(filtered_params[key], str):
                    filtered_params[key] = parse_color(filtered_params[key])

            style_params.update(filtered_params)
            new_style = LayerStyle(**style_params)
            target_layer.style = new_style
            if new_style.attribute_column:
                layer_data = target_layer.gdf
                target_layer.render_spec = build_render_spec(
                    layer_data,
                    new_style.attribute_column,
                    new_style.classification_method,
                    new_style.classification_classes,
                    no_data_color=new_style.no_data_color,
                )
            else:
                target_layer.render_spec = None

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
