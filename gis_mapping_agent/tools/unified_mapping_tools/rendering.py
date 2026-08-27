"""Matplotlib rendering and saving operations."""

from typing import Any, Dict
import gc
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import pandas as pd
from matplotlib.colors import BoundaryNorm, ListedColormap
from matplotlib.lines import Line2D
from matplotlib.transforms import Bbox

from ...models.schemas import GeometryType
from ...rendering.elements import MapQualityChecker
from ...utils.config import Config


_CITY_LABEL_ALIASES = {
    "Chaozhou": "潮州",
    "Dongyuan": "东莞",
    "Foshan": "佛山",
    "Guangzhou": "广州",
    "Heyuan": "河源",
    "Huizhou": "惠州",
    "Jiangmen": "江门",
    "Jieyang": "揭阳",
    "Maoming": "茂名",
    "Meizhou": "梅州",
    "Qingyuan": "清远",
    "Shantou": "汕头",
    "Shanwei": "汕尾",
    "Shaoguan": "韶关",
    "Shenzhen": "深圳",
    "Yangjiang": "阳江",
    "Yunfu": "云浮",
    "Zhanjiang": "湛江",
    "Zhaoqing": "肇庆",
    "Zhongshan": "中山",
    "Zhuhai": "珠海",
}


class RenderingMixin:
    def _redraw_map(self):
        """清除并根据当前状态重新绘制所有图层和元素"""
        if not self.ax or not self.current_map_state:
            return

        # 清除旧的绘图
        self.ax.clear()

        # 重新应用地图基本设置
        self.ax.set_facecolor(self.current_map_state.config.background_color)
        min_lon, min_lat, max_lon, max_lat = self.current_map_state.config.extent
        self.ax.set_xlim(min_lon, max_lon)
        self.ax.set_ylim(min_lat, max_lat)
        self._setup_axis_ticks(min_lon, max_lon, min_lat, max_lat)

        # 重新设置标题
        if self.current_map_state.config.title and self.figure:
            title_props = {'fontsize': 14, 'fontweight': 'bold'}
            if self.chinese_font:
                title_props['fontfamily'] = self.chinese_font
            self.figure.suptitle(self.current_map_state.config.title, **title_props)

        # 重新绘制所有图层（按z_order排序）
        sorted_layers = sorted(self.current_map_state.layers, key=lambda l: l.z_order)
        for layer in sorted_layers:
            if layer.visible and layer.gdf is not None:
                plot_params = {
                    "ax": self.ax,
                    "alpha": layer.style.alpha,
                    "zorder": layer.z_order
                }

                # 根据几何类型设置不同的绘图参数
                if layer.geometry_type in [GeometryType.POLYGON, GeometryType.MULTIPOLYGON]:
                    # 使用用户设置的边框颜色和线宽，如果没有设置则使用默认值
                    # Keep administrative boundaries legible in the final PNG and the
                    # realtime vector preview when a request did not specify a style.
                    plot_params['edgecolor'] = layer.style.edgecolor or '#334155'
                    plot_params['linewidth'] = max(layer.style.linewidth or 0.8, 1.1)
                    self.logger.debug(
                        f"面图层 '{layer.name}' 边框设置: 颜色={plot_params['edgecolor']}，线宽={plot_params['linewidth']}"
                    )
                    # 如果设置了facecolor，使用它；否则使用color
                    plot_params['facecolor'] = layer.style.facecolor or layer.style.color
                elif layer.geometry_type == GeometryType.POINT:
                    plot_params['marker'] = layer.style.marker
                    plot_params['markersize'] = layer.style.size
                    # 为点图层添加边框效果
                    if layer.style.edgecolor:
                        plot_params['edgecolor'] = layer.style.edgecolor
                        plot_params['linewidth'] = layer.style.linewidth
                else: # a line
                    plot_params['linewidth'] = max(layer.style.linewidth or 0.8, 0.8)

                # 应用颜色和线型
                if layer.style.attribute_column and layer.style.attribute_column in layer.gdf.columns:
                    plot_params['column'] = layer.style.attribute_column
                    plot_params['legend'] = False  # 我们自己管理图例，不让geopandas自动创建
                    render_spec = layer.render_spec or {}
                    if render_spec.get('enabled'):
                        colors = render_spec.get('colors') or self.COLOR_PALETTE
                        plot_params['cmap'] = ListedColormap(colors)
                        if render_spec.get('kind') == 'numeric' and len(render_spec.get('breaks', [])) >= 2:
                            plot_params['norm'] = BoundaryNorm(render_spec['breaks'], len(colors), clip=True)
                        elif render_spec.get('kind') == 'categorical':
                            plot_params['categorical'] = True
                        plot_params['missing_kwds'] = {
                            'color': render_spec.get('no_data_color', '#CBD5E1'),
                            'label': '无数据',
                        }
                    elif pd.api.types.is_numeric_dtype(layer.gdf[layer.style.attribute_column]):
                        plot_params['cmap'] = 'viridis'
                    else:
                        unique_values = sorted(layer.gdf[layer.style.attribute_column].dropna().unique())
                        colors = [self.COLOR_PALETTE[i % len(self.COLOR_PALETTE)] for i in range(len(unique_values))]
                        plot_params['cmap'] = ListedColormap(colors)
                else:
                    plot_params['legend'] = False # 对于非分类图层，不自动创建图例
                    plot_params['color'] = layer.style.color
                    plot_params['linestyle'] = layer.style.linestyle

                layer.gdf.plot(**plot_params)

                # 添加地理标签
                if layer.style.label_column and layer.style.label_column in layer.gdf.columns:
                    self.logger.info(f"开始为图层 '{layer.name}' 添加标签，使用列 '{layer.style.label_column}'")
                    for _, row in layer.gdf.iterrows():
                        centroid = row.geometry.centroid
                        label_text = row[layer.style.label_column]
                        label_text = _CITY_LABEL_ALIASES.get(str(label_text), label_text)

                        # 设置标签样式，包括中文字体支持
                        text_props = {
                            'fontsize': 9,
                            'ha': 'center',
                            'va': 'center',
                            'color': 'black',
                            'weight': 'bold',
                            'zorder': 10  # 设置高z-order，确保文字在图例上方
                        }
                        if self.chinese_font:
                            text_props['fontfamily'] = self.chinese_font

                        self.ax.text(centroid.x, centroid.y, label_text, **text_props)

        # 先绘制图例（较低层级，避免遮挡文字）
        self._draw_auto_legend()

        # 重新绘制其他元素
        if self.current_map_state.scalebar:
            self._draw_scalebar(self.current_map_state.scalebar)
        if self.current_map_state.compass:
            self._draw_compass(self.current_map_state.compass)

    def _draw_auto_legend(self):
        """根据 current_map_state.legend_items 自动绘制图例"""
        if not self.ax or not self.current_map_state:
            return

        handles, labels = [], []
        if self.current_map_state.legend_items:
            # 提取所有图例项，包括分类图例
            for item in self.current_map_state.legend_items:
                # 通过中文名称反向查找英文图层名
                english_name = None
                for eng_name, chi_name in self.LAYER_NAME_MAPPING.items():
                    if chi_name == item.label:
                        english_name = eng_name
                        break
                if not english_name:
                    english_name = item.label  # 如果没找到映射，使用原始名称

                layer_config = next(
                    (l for l in self.current_map_state.layers if l.name == item.label),
                    None,
                ) or next(
                    (l for l in self.current_map_state.layers if l.name == english_name),
                    None,
                )
                if not layer_config or layer_config.gdf is None:
                    continue

                style = item.style
                attribute_column = style.get('attribute_column')

                if attribute_column and attribute_column in layer_config.gdf.columns:
                    gdf = layer_config.gdf
                    render_spec = layer_config.render_spec or {}
                    if render_spec.get('enabled'):
                        if render_spec.get('kind') == 'numeric':
                            entries = zip(render_spec.get('labels', []), render_spec.get('colors', []))
                        else:
                            entries = zip(render_spec.get('values', []), render_spec.get('colors', []))
                        for label, color in entries:
                            label = str(label)
                            if label in labels:
                                continue
                            handles.append(patches.Patch(color=color, label=label))
                            labels.append(label)
                    else:
                        unique_values = sorted(gdf[attribute_column].dropna().unique())
                        colors = [self.COLOR_PALETTE[i % len(self.COLOR_PALETTE)] for i in range(len(unique_values))]
                        for value, color in zip(unique_values, colors):
                            label = str(value)
                            if label not in labels:
                                handles.append(patches.Patch(color=color, label=label))
                                labels.append(label)
                else:
                    # 为单一图例项生成图例
                    if item.label not in labels:
                        if item.type == 'line':
                            # 线图层使用更细的线条以便在图例中显示更小
                            line_width = max(style.get('linewidth', 1.5) * 0.7, 1.0)  # 缩小30%，最小1.0
                            handles.append(Line2D([0], [0], color=style.get('color', 'black'), lw=line_width, ls=style.get('linestyle', '-'), label=item.label))
                        elif item.type == 'point':
                            # ✅ 为点图层使用与地图上完全一致的符号
                            # 获取实际图层配置以确保一致性
                            actual_marker = style.get('marker', 'o')
                            actual_size = style.get('size', 50.0)
                            actual_color = style.get('color', 'blue')
                            actual_edgecolor = style.get('edgecolor', 'white')
                            actual_linewidth = style.get('linewidth', 1.5)

                            # ✅ 关键修复：geopandas 的 markersize 对应 scatter 的 s 参数（面积，points²）
                            # Line2D 的 markersize 是点的直径（points）
                            # 转换公式：Line2D_markersize = sqrt(scatter_s / pi) * 2
                            # 为了在图例中显示得更小，再除以一个缩放因子
                            import math
                            # 直接使用相同的面积，但缩小显示
                            legend_markersize = math.sqrt(actual_size / math.pi) * 2 / 2.5

                            handles.append(Line2D([0], [0],
                                                marker=actual_marker,
                                                color='w',
                                                markerfacecolor=actual_color,
                                                markeredgecolor=actual_edgecolor,
                                                markeredgewidth=actual_linewidth,
                                                markersize=legend_markersize,
                                                label=item.label))
                        else:
                            handles.append(patches.Patch(color=style.get('color', 'blue'), label=item.label))
                        labels.append(item.label)

        # 绘制最终图例
        if handles:
            legend_props = {'family': self.chinese_font} if self.chinese_font else None

            # 设置图例位置为右下角
            legend_position = "lower right"  # 改为右下角显示

            legend_obj = self.ax.legend(
                handles, labels,
                title="图例",
                loc=legend_position,
                frameon=False,  # 关闭边框，实现全透明
                title_fontproperties=legend_props,
                fontsize=8,  # 缩小字体大小
                framealpha=0,  # 设置背景为全透明
                edgecolor='none',  # 无边框颜色
                facecolor='none',  # 无背景颜色
                handlelength=1.5,  # 缩小图例符号长度
                handletextpad=0.5,  # 缩小符号与文字间距
                columnspacing=0.8,  # 缩小列间距
                borderpad=0.3  # 缩小内边距
            )

            # 设置图例的z-order为较低层级，确保不遮挡文字
            if legend_obj:
                legend_obj.set_zorder(1)  # 低层级
                if legend_obj.get_frame():
                    legend_obj.get_frame().set_zorder(1)

            if self.chinese_font and legend_obj:
                for text in legend_obj.get_texts():
                    text.set_fontfamily(self.chinese_font)
                # 设置标题字体
                if legend_obj.get_title():
                    legend_obj.get_title().set_fontfamily(self.chinese_font)

            self.logger.debug("自动绘制图例完成")

    def map_save(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """保存最终地图为PNG文件

        Args:
            params: 保存参数
                - filename: 文件名（不含扩展名）
                - output_dir: 输出目录
                - dpi: 分辨率
                - format: 文件格式 ('png', 'jpg', 'pdf')

        Returns:
            Dict: 操作结果
        """
        try:
            if not self.current_map_state or not self.figure:
                raise ValueError("没有可保存的地图")

            filename = params.get('file_name', params.get('filename', 'map_output'))
            output_dir = params.get('output_dir')
            if output_dir is None:
                output_dir = str(Config.OUTPUT_DIR)

            # 使用更保守的DPI设置，避免内存问题
            dpi = params.get('dpi', Config.HYPERPARAMETERS.SAVE_DPI)

            # self.logger.info(f"地图保存DPI设置为: {dpi}")
            file_format = params.get('format', 'png')

            # add_layer 负责更新状态，保存前统一重绘，避免没有额外
            # style_layer/render_map 调用时把空画布误保存为成功结果。
            self._redraw_map()


            # 确保输出目录存在
            output_path = Path(output_dir)
            output_path.mkdir(parents=True, exist_ok=True)

            # 构建完整文件路径，避免重复扩展名
            if filename.endswith(f'.{file_format}'):
                full_filename = filename
            else:
                full_filename = f"{filename}.{file_format}"
            file_path = output_path / full_filename

            # 强制垃圾回收，释放内存
            gc.collect()


            # --- 最终解决方案：手动计算所有元素的精确边界框 ---
            # 这是解决 'Image size too large' 错误的根本方法，它完全绕过了Matplotlib有缺陷的自动计算

            # 确保所有元素都已绘制，以便计算它们的尺寸
            self.figure.canvas.draw()

            # 获取所有需要包含在内的元素的边界框 (in inches)
            renderers = self.figure.canvas.get_renderer()
            items_to_include = self.figure.get_children()

            # 有时图例等元素不在figure的直接子元素中，需要单独添加
            if self.ax and self.ax.get_legend():
                items_to_include.append(self.ax.get_legend())

            # 初始化一个空的边界框
            total_bbox = None

            for item in items_to_include:
                if hasattr(item, 'get_window_extent'):
                    bbox_display = item.get_window_extent(renderer=renderers)
                    # 将边界框从显示坐标转换回英寸坐标
                    bbox_inches = bbox_display.transformed(self.figure.dpi_scale_trans.inverted())

                    if total_bbox is None:
                        total_bbox = bbox_inches
                    else:
                        # 合并当前元素的边界框到总边界框中
                        total_bbox = Bbox.union([total_bbox, bbox_inches])

            if total_bbox:
                # 增加一点点边距 (e.g., 0.1 inches)
                total_bbox = total_bbox.padded(0.1)

                # 使用我们手动计算的精确边界框来保存图像
                self.figure.savefig(
                    str(file_path),
                    dpi=dpi,
                    bbox_inches=total_bbox,
                    format=file_format,
                    facecolor='white',
                    edgecolor='none'
                )
            else:
                # 如果无法计算边界框，则回退到标准保存，不使用tight
                self.logger.warning("无法计算手动边界框，回退到标准保存模式")
                self.figure.savefig(str(file_path), dpi=dpi, format=file_format)

            # 立即关闭图形以释放内存
            plt.close(self.figure)
            self.figure = None
            self.ax = None

            # 强制垃圾回收
            gc.collect()

            # # 显示相对路径而不是绝对路径
            # try:
            #     rel_path = Path(file_path).relative_to(Config.PROJECT_ROOT)
            #     display_path = str(rel_path)
            # except (ValueError, Exception):
            #     display_path = file_path

            message = f"地图已保存"
            self.current_map_state.output_path = str(file_path)
            self.logger.info(message)

            return {
                "success": True,
                "message": message,
                "file_path": str(file_path),
                "file_size": file_path.stat().st_size if file_path.exists() else 0,
                "actual_dpi": dpi,
                "quality": MapQualityChecker().check(self.current_map_state, str(file_path))
            }

        except Exception as e:
            error_msg = f"保存地图失败: {str(e)}"
            self.logger.error(error_msg)



            return {
                "success": False,
                "message": error_msg,
                "error": str(e)
            }
