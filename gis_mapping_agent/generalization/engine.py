"""
路网综合引擎

整合多种路网综合算法，实现从大尺度到小尺度的自动缩编
"""

import geopandas as gpd
import matplotlib.pyplot as plt
import matplotlib
import numpy as np
from pathlib import Path
from typing import Dict, List, Optional, Literal
from datetime import datetime

from ..algorithms.stroke_builder import StrokeBuilder
from ..algorithms.mesh_density import MeshDensityCalculator
from ..algorithms.hierarchy_selector import HierarchySelector
from ..algorithms.gcnn_selector import GCNNSelector
from .result import GeneralizationResult
from ..utils.logger import get_logger
from ..utils.config import Config

# 配置中文字体
matplotlib.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'Arial Unicode MS', 'DejaVu Sans']
matplotlib.rcParams['axes.unicode_minus'] = False  # 解决负号显示问题


class RoadNetworkGeneralizationEngine:
    """路网综合引擎
    
    实现路网的自动综合处理，包括：
    1. Stroke构建
    2. 网眼密度计算
    3. 层次选取
    4. 可视化对比
    """
    
    def __init__(self, verbose: bool = True):
        """初始化路网综合引擎
        
        Args:
            verbose: 是否输出详细信息
        """
        self.verbose = verbose
        self.logger = get_logger("RoadNetworkGeneralizationEngine")
        
        # 初始化各个算法组件
        self.stroke_builder = StrokeBuilder(verbose=verbose)
        self.mesh_calculator = MeshDensityCalculator(verbose=verbose)
        self.hierarchy_selector = HierarchySelector(verbose=verbose)
        self.gcnn_selector = GCNNSelector(verbose=verbose)
    
    def generalize(
        self,
        input_gdf: gpd.GeoDataFrame,
        source_scale: int = 500,
        target_scale: int = 2000,
        algorithm: Literal['stroke', 'mesh_density', 'hierarchy', 'gcnn'] = 'stroke',
        keep_ratio: Optional[float] = None,
        data_dir: Optional[str] = None,
        input_path: Optional[str] = None,
        output_path: Optional[str] = None,
        hierarchy_method: Optional[str] = None,
        hierarchy_attribute: Optional[str] = None,
    ) -> Dict:
        """执行路网综合

        Args:
            input_gdf: 输入的路网GeoDataFrame
            source_scale: 源尺度（如500表示1:500）
                - stroke/mesh_density/hierarchy算法使用此参数
                - gcnn算法不使用此参数
            target_scale: 目标尺度（如2000表示1:2000）
                - stroke/mesh_density/hierarchy算法使用此参数
                - gcnn算法不使用此参数
            algorithm: 使用的算法
                - 'stroke': Stroke构建算法（使用source_scale和target_scale）
                - 'mesh_density': 网眼密度算法（使用source_scale和target_scale）
                - 'hierarchy': 层次选取算法（使用source_scale和target_scale）
                - 'gcnn': 图卷积神经网络算法（只使用keep_ratio，基于深度学习自动选取）
            keep_ratio: 保留比例（0-1之间的浮点数）
                - gcnn算法：必须明确指定此参数（如0.3表示保留30%的路网）
                - 其他算法：如果为None，则根据source_scale和target_scale自动计算
            data_dir: 数据目录（gcnn算法需要，如'data6'）

        Returns:
            包含综合结果的字典
        """
        # 参数处理：区分gcnn算法和其他算法
        if algorithm == 'gcnn':
            # GCNN算法：只使用keep_ratio参数
            if keep_ratio is None:
                raise ValueError("GCNN算法必须指定keep_ratio参数（保留比例，0-1之间）")
            if self.verbose:
                self.logger.info(f"开始路网综合: 算法=gcnn, 保留比例={keep_ratio:.2f}")
            scale_ratio = None  # gcnn不使用尺度比
        else:
            # 其他算法：使用source_scale和target_scale，自动计算keep_ratio
            scale_ratio = target_scale / source_scale

            # 如果未指定保留比例，根据尺度比自动计算
            if keep_ratio is None:
                # 使用反比例关系：尺度越大，保留的路段越少
                # 例如：1:500 -> 1:2000，尺度比为4，保留比例约为 1/4 = 0.25
                # 为了避免过度删减，使用平方根关系
                keep_ratio = 1.0 / np.sqrt(scale_ratio)
                # 确保保留比例在合理范围内 (0.1 - 0.9)
                keep_ratio = max(0.1, min(0.9, keep_ratio))

            if self.verbose:
                self.logger.info(f"开始路网综合: 从 1:{source_scale} 到 1:{target_scale}，算法={algorithm}")
                self.logger.info(f"尺度比: {scale_ratio:.2f}, 保留比例: {keep_ratio:.2f}")
        
        # 执行综合
        stroke_count = None  # 用于存储stroke总数
        if algorithm == 'stroke':
            result_gdf, stroke_count = self._generalize_by_stroke(input_gdf, keep_ratio)
        elif algorithm == 'mesh_density':
            result_gdf = self._generalize_by_mesh_density(input_gdf, keep_ratio)
        elif algorithm == 'hierarchy':
            result_gdf, hierarchy_method, hierarchy_attribute = self._generalize_by_hierarchy(
                input_gdf,
                keep_ratio,
                method=hierarchy_method,
                attribute_name=hierarchy_attribute,
            )
        elif algorithm == 'gcnn':
            if data_dir is None:
                raise ValueError("GCNN算法需要指定data_dir参数")
            result_gdf = self._generalize_by_gcnn(input_gdf, data_dir, keep_ratio)
        else:
            self.logger.warning(f"未知的算法: {algorithm}，使用stroke算法")
            result_gdf, stroke_count = self._generalize_by_stroke(input_gdf, keep_ratio)

        # 计算统计信息
        stats = self._calculate_statistics(input_gdf, result_gdf)

        result = GeneralizationResult(
            input_path=input_path,
            output_path=output_path,
            input_gdf=input_gdf,
            output_gdf=result_gdf,
            metrics=stats,
            params={
                "source_scale": source_scale,
                "target_scale": target_scale,
                "algorithm": algorithm,
                "keep_ratio": keep_ratio,
                "data_dir": data_dir,
                "hierarchy_method": hierarchy_method,
                "hierarchy_attribute": hierarchy_attribute,
            },
            meta={
                "stroke_count": stroke_count,
                "hierarchy_method": hierarchy_method,
                "hierarchy_attribute": hierarchy_attribute,
            },
        ).to_legacy_dict()
        
        if self.verbose:
            self.logger.info(f"路网综合完成: 从 {stats['input_count']} 条路段缩编到 {stats['output_count']} 条路段")
        
        return result
    
    def _generalize_by_stroke(
        self,
        gdf: gpd.GeoDataFrame,
        keep_ratio: float
    ) -> tuple[gpd.GeoDataFrame, int]:
        """使用Stroke算法综合

        Args:
            gdf: 输入GeoDataFrame
            keep_ratio: 保留比例

        Returns:
            (综合后的GeoDataFrame, stroke总数)
        """
        # 1. 构建strokes
        stroke_gdf = self.stroke_builder.build_strokes(gdf)
        stroke_count = len(stroke_gdf)  # 保存stroke总数

        # 2. 按stroke重要性选取
        result_gdf = self.hierarchy_selector.select_by_hierarchy(
            stroke_gdf,
            method='stroke_importance',
            keep_ratio=keep_ratio
        )

        return result_gdf, stroke_count
    
    def _generalize_by_mesh_density(
        self,
        gdf: gpd.GeoDataFrame,
        keep_ratio: float
    ) -> gpd.GeoDataFrame:
        """使用网眼密度算法综合
        
        Args:
            gdf: 输入GeoDataFrame
            keep_ratio: 保留比例
            
        Returns:
            综合后的GeoDataFrame
        """
        # 1. 计算网眼密度
        mesh_info = self.mesh_calculator.calculate_mesh_density(gdf)
        
        # 2. 基于密度信息选取（这里简化为按长度选取）
        result_gdf = self.hierarchy_selector.select_by_hierarchy(
            gdf,
            method='length',
            keep_ratio=keep_ratio
        )
        
        return result_gdf
    
    def _generalize_by_hierarchy(
        self,
        gdf: gpd.GeoDataFrame,
        keep_ratio: float,
        method: Optional[str] = None,
        attribute_name: Optional[str] = None,
    ) -> tuple[gpd.GeoDataFrame, str, Optional[str]]:
        """使用层次选取算法综合

        Args:
            gdf: 输入GeoDataFrame
            keep_ratio: 保留比例

        Returns:
            综合后的GeoDataFrame
        """
        resolved_method, resolved_attribute = self._resolve_hierarchy_selection(
            gdf,
            method=method,
            attribute_name=attribute_name,
        )

        result_gdf = self.hierarchy_selector.select_by_hierarchy(
            gdf,
            method=resolved_method,
            attribute_name=resolved_attribute,
            keep_ratio=keep_ratio
        )

        return result_gdf, resolved_method, resolved_attribute

    def _resolve_hierarchy_selection(
        self,
        gdf: gpd.GeoDataFrame,
        method: Optional[str] = None,
        attribute_name: Optional[str] = None,
    ) -> tuple[str, Optional[str]]:
        """Resolve hierarchy selection method and attribute robustly."""
        valid_methods = {"length", "attribute", "stroke_importance", "percentile"}
        normalized_method = (method or "").strip().lower() or None
        if normalized_method and normalized_method not in valid_methods:
            normalized_method = None

        resolved_attribute = self._resolve_hierarchy_attribute(gdf, attribute_name)
        if resolved_attribute:
            return "attribute", resolved_attribute

        if normalized_method:
            return normalized_method, None

        return "length", None

    def _resolve_hierarchy_attribute(
        self,
        gdf: gpd.GeoDataFrame,
        requested: Optional[str] = None,
    ) -> Optional[str]:
        columns = list(gdf.columns)
        column_lookup = {str(column).lower(): column for column in columns}

        if requested:
            requested_key = str(requested).strip().lower()
            if requested_key in column_lookup:
                return column_lookup[requested_key]

            semantic_aliases = {
                "road_class": ["road_class", "roadclass", "class", "road_type", "type", "fclass", "classzn2", "highway"],
                "roadclass": ["road_class", "roadclass", "class", "road_type", "type", "fclass", "classzn2", "highway"],
                "class": ["road_class", "roadclass", "class", "fclass", "classzn2", "highway"],
            }
            for alias in semantic_aliases.get(requested_key, []):
                if alias in column_lookup:
                    resolved = column_lookup[alias]
                    if self.verbose:
                        self.logger.info(f"层次字段 {requested} 不存在，使用相近字段 {resolved}")
                    return resolved

            for column in columns:
                column_key = str(column).lower()
                if requested_key and (requested_key in column_key or column_key in requested_key):
                    if self.verbose:
                        self.logger.info(f"层次字段 {requested} 不存在，使用相似字段 {column}")
                    return column

        preferred = ["road_class", "roadclass", "fclass", "classzn2", "class", "road_type", "highway", "type"]
        for key in preferred:
            if key in column_lookup:
                return column_lookup[key]

        return None

    def _generalize_by_gcnn(
        self,
        gdf: gpd.GeoDataFrame,
        data_dir: str,
        keep_ratio: Optional[float] = 1.0
    ) -> gpd.GeoDataFrame:
        """使用GCNN算法综合

        注意：GCNN算法不使用比例尺参数（如1:500 → 1:2000），
        而是通过深度学习模型自动判断路网重要性。

        Args:
            gdf: 输入GeoDataFrame
            data_dir: 数据目录路径，需包含data.xlsx文件
            keep_ratio: 保留比例（参考值，GCNN会自动学习，不影响实际选取结果）

        Returns:
            综合后的GeoDataFrame
        """
        result_gdf = self.gcnn_selector.select_by_gcnn(
            gdf,
            data_dir=data_dir,
            keep_ratio=keep_ratio
        )

        return result_gdf
    
    def _calculate_statistics(
        self,
        input_gdf: gpd.GeoDataFrame,
        output_gdf: gpd.GeoDataFrame
    ) -> Dict:
        """计算统计信息
        
        Args:
            input_gdf: 输入GeoDataFrame
            output_gdf: 输出GeoDataFrame
            
        Returns:
            统计信息字典
        """
        input_count = len(input_gdf)
        output_count = len(output_gdf)
        
        input_total_length = input_gdf.geometry.length.sum()
        output_total_length = output_gdf.geometry.length.sum()
        
        reduction_rate = (input_count - output_count) / input_count if input_count > 0 else 0
        length_retention_rate = output_total_length / input_total_length if input_total_length > 0 else 0
        
        return {
            'input_count': input_count,
            'output_count': output_count,
            'reduction_rate': reduction_rate,
            'input_total_length': input_total_length,
            'output_total_length': output_total_length,
            'length_retention_rate': length_retention_rate
        }
    
    def _draw_scalebar_and_compass_on_axis(self, ax, gdf, add_scalebar=True, add_compass=True):
        """在指定的axis上绘制比例尺和指北针（与制图任务样式完全一致）

        Args:
            ax: matplotlib坐标轴
            gdf: GeoDataFrame（用于获取CRS信息）
            add_scalebar: 是否添加比例尺
            add_compass: 是否添加指北针
        """
        # 创建临时的UnifiedMappingTools实例
        from ..tools.unified_mapping_tools import UnifiedMappingTools
        tools = UnifiedMappingTools()
        tools.ax = ax  # 设置当前axis

        # 绘制比例尺（针对投影坐标系进行特殊处理）
        if add_scalebar:
            xlim = ax.get_xlim()
            ylim = ax.get_ylim()

            # 检查是否为投影坐标系
            if gdf.crs and gdf.crs.is_projected:
                # 投影坐标系，单位通常是米
                # 计算网格刻度间隔（与制图任务一致）
                x_span = xlim[1] - xlim[0]

                # 目标是在范围内显示大约 5-10 个刻度
                raw_interval = x_span / 7

                # 将间隔规范化到一个"整齐"的数字
                power = 10 ** np.floor(np.log10(raw_interval))
                normalized_interval = raw_interval / power

                if normalized_interval < 1.5:
                    grid_interval = 1.0 * power
                elif normalized_interval < 3.5:
                    grid_interval = 2.0 * power
                elif normalized_interval < 7.5:
                    grid_interval = 5.0 * power
                else:
                    grid_interval = 10.0 * power

                # 比例尺长度固定为1个刻度间隔（单位：米）
                length_m = grid_interval
                length_km = length_m / 1000  # 转换为公里

                # 设置比例尺位置（与制图任务一致：左下角 [0.01, 0.01]）
                position = [0.01, 0.01]
                x_pos = xlim[0] + (xlim[1] - xlim[0]) * position[0]
                y_pos = ylim[0] + (ylim[1] - ylim[0]) * position[1]

                # 绘制比例尺线条（与制图任务样式一致）
                ax.plot([x_pos, x_pos + length_m], [y_pos, y_pos],
                        'k-', linewidth=2, zorder=10)

                # 添加文字标签（与制图任务样式一致：fontsize=8, 无背景框）
                font_props = {'fontsize': 8}
                if tools.chinese_font:
                    font_props['fontfamily'] = tools.chinese_font
                ax.text(x_pos + length_m / 2,
                        y_pos + (ylim[1] - ylim[0]) * 0.01,
                        f'{int(length_km)} km',
                        ha='center', va='bottom', zorder=10,
                        **font_props)
            else:
                # 地理坐标系，使用UnifiedMappingTools的方法
                scalebar_params = {
                    'position': [0.01, 0.01],
                    'units': 'km'
                }
                tools._draw_scalebar(scalebar_params)

        # 绘制指北针（与制图任务样式完全一致）
        if add_compass:
            compass_params = {
                'position': [0.9, 0.9],
                'size': 0.05
            }
            tools._draw_compass(compass_params)

    def visualize_comparison(
        self,
        generalization_result: Dict,
        output_dir: Optional[str] = None,
        figsize: tuple = (16, 8),
        dpi: int = 500,
        add_scalebar: bool = True,
        add_compass: bool = True
    ) -> Dict:
        """可视化综合前后的对比

        Args:
            generalization_result: 综合结果字典
            output_dir: 输出目录
            figsize: 图片大小
            dpi: 分辨率
            add_scalebar: 是否添加比例尺
            add_compass: 是否添加指北针

        Returns:
            包含文件路径的字典
        """
        # 确保输出目录存在
        if output_dir is None:
            output_dir = Config.OUTPUT_DIR
        else:
            output_dir = Path(output_dir)

        output_dir.mkdir(parents=True, exist_ok=True)

        input_gdf = generalization_result['input_gdf']
        output_gdf = generalization_result['output_gdf']
        stats = generalization_result['statistics']

        # 创建对比图，使用中文字体
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=figsize)

        # 统一字体配置（确保每次生成的图片字体一致）
        font_config = {
            'family': 'sans-serif',
            'sans-serif': ['SimHei', 'Microsoft YaHei', 'Arial Unicode MS', 'DejaVu Sans'],
            'size': 11
        }
        plt.rcParams.update({
            'font.family': font_config['family'],
            'font.sans-serif': font_config['sans-serif'],
            'font.size': font_config['size'],
            'axes.unicode_minus': False
        })

        # 统一的文本样式配置
        title_fontsize = 12
        label_fontsize = 11
        tick_fontsize = 9
        title_fontweight = 'normal'
        title_pad = 12

        # 获取输入数据的边界范围（使用综合前的数据范围作为统一范围）
        input_bounds = input_gdf.total_bounds  # [minx, miny, maxx, maxy]
        output_bounds = output_gdf.total_bounds

        # 打印边界信息用于诊断
        if self.verbose:
            self.logger.info(f"输入数据边界")
            # self.logger.info(f"输出数据边界: X[{output_bounds[0]:.2f}, {output_bounds[2]:.2f}], Y[{output_bounds[1]:.2f}, {output_bounds[3]:.2f}]")

        # 添加一些边距（5%）
        x_margin = (input_bounds[2] - input_bounds[0]) * 0.05
        y_margin = (input_bounds[3] - input_bounds[1]) * 0.05

        xlim = [input_bounds[0] - x_margin, input_bounds[2] + x_margin]
        ylim = [input_bounds[1] - y_margin, input_bounds[3] + y_margin]

        # 构建综合前后的标题 - 根据算法类型决定是否显示尺度信息
        algorithm = generalization_result.get('algorithm', 'stroke')

        # 综合前
        input_gdf.plot(ax=ax1, color='blue', linewidth=0.5, alpha=0.7)
        if algorithm == 'gcnn':
            title1 = f'综合前 路段数：{stats["input_count"]}'
        else:
            title1 = f'综合前（1:{generalization_result["source_scale"]}） 路段数：{stats["input_count"]}'
        ax1.set_title(title1, fontsize=title_fontsize, fontweight=title_fontweight,
                     pad=title_pad, fontfamily='sans-serif')

        # 设置坐标轴范围
        ax1.set_xlim(xlim)
        ax1.set_ylim(ylim)

        # 显示坐标轴
        ax1.set_xlabel('X坐标', fontsize=label_fontsize, fontfamily='sans-serif')
        ax1.set_ylabel('Y坐标', fontsize=label_fontsize, fontfamily='sans-serif')
        ax1.tick_params(labelsize=tick_fontsize)
        ax1.grid(True, alpha=0.3, linestyle='--', linewidth=0.5)

        # 综合后
        output_gdf.plot(ax=ax2, color='red', linewidth=0.5, alpha=0.7)

        if algorithm == 'gcnn':
            # GCNN算法：不显示尺度信息，显示保留比例
            keep_ratio = generalization_result.get('keep_ratio', 0)
            title2 = f'综合后（保留比例：{keep_ratio:.0%}） 路段数：{stats["output_count"]}'
        else:
            # 其他算法：显示目标尺度
            title2 = f'综合后（1:{generalization_result["target_scale"]}） 路段数：{stats["output_count"]}'

            # 如果使用Stroke算法，添加stroke数信息
            if algorithm == 'stroke':
                stroke_count = generalization_result.get('stroke_count')
                if stroke_count is not None:
                    title2 += f' stroke数：{stroke_count}'

        ax2.set_title(title2, fontsize=title_fontsize, fontweight=title_fontweight,
                     pad=title_pad, fontfamily='sans-serif')

        # 设置相同的坐标轴范围（确保两个子图显示相同的区域）
        ax2.set_xlim(xlim)
        ax2.set_ylim(ylim)

        # 显示坐标轴
        ax2.set_xlabel('X坐标', fontsize=label_fontsize, fontfamily='sans-serif')
        ax2.set_ylabel('Y坐标', fontsize=label_fontsize, fontfamily='sans-serif')
        ax2.tick_params(labelsize=tick_fontsize)
        ax2.grid(True, alpha=0.3, linestyle='--', linewidth=0.5)

        # 添加比例尺和指北针（两个子图都添加，直接使用UnifiedMappingTools）
        # 使用input_gdf获取CRS信息
        self._draw_scalebar_and_compass_on_axis(ax1, input_gdf, add_scalebar=add_scalebar, add_compass=add_compass)
        self._draw_scalebar_and_compass_on_axis(ax2, output_gdf, add_scalebar=add_scalebar, add_compass=add_compass)

        # 调整子图布局，增加左右图之间的间距以避免重叠
        plt.tight_layout()
        plt.subplots_adjust(wspace=0.1)  # wspace控制子图之间的水平间距，增加到0.3以避免重叠

        # 保存文件到outputs目录
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"generalization_comparison_{timestamp}.png"
        filepath = output_dir / filename

        # 保存图片，确保中文正确显示
        plt.savefig(filepath, dpi=dpi, bbox_inches='tight', facecolor='white', edgecolor='none')
        plt.close(fig)

        if self.verbose:
            self.logger.info(f"对比图已保存")

        return {
            'success': True,
            'filepath': str(filepath),
            'filename': filename
        }
