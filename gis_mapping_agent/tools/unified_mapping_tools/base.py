"""Shared state and layout helpers for UnifiedMappingTools."""

from typing import Any, Dict, List, Optional, Tuple
import gc
import platform
import re

import geopandas as gpd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from ...models.schemas import MapState
from ...utils.logger import get_logger

class UnifiedMappingToolsBase:
    def __init__(self):
        """初始化统一制图工具"""
        self.logger = get_logger("UnifiedMappingTools")
        self._map_state: Optional[MapState] = None  # 内部状态存储
        self.figure = None
        self.ax = None

        # 设置中文字体支持
        self.chinese_font = self._setup_chinese_font()
        if self.chinese_font:
            self.logger.debug(f"已设置中文字体: {self.chinese_font}")
        else:
            self.logger.debug("未能设置中文字体，中文可能无法正常显示")

        self.logger.debug("统一制图工具初始化完成")

    @property
    def current_map_state(self) -> Optional[MapState]:
        """获取当前地图状态"""
        return self._map_state

    @current_map_state.setter
    def current_map_state(self, value: Optional[MapState]) -> None:
        """设置当前地图状态，同时更新兼容性属性"""
        self._map_state = value
        self._current_map_state = value  # 兼容性属性

    @property
    def _current_map_state(self) -> Optional[MapState]:
        """兼容性属性，用于ThinkingGISMappingAgent"""
        return self._map_state

    @_current_map_state.setter
    def _current_map_state(self, value: Optional[MapState]) -> None:
        """兼容性属性设置器"""
        self._map_state = value

    def _setup_chinese_font(self) -> Optional[str]:
        """设置中文字体支持"""
        try:
            # 根据操作系统选择字体
            system = platform.system()
            if system == "Windows":
                # Windows系统常见中文字体
                fonts_to_try = ['Microsoft YaHei', 'SimHei', 'SimSun', 'KaiTi']
            elif system == "Darwin":  # macOS
                # macOS系统中文字体
                fonts_to_try = ['PingFang SC', 'Heiti SC', 'STHeiti', 'Arial Unicode MS']
            else:  # Linux
                # Linux系统中文字体
                fonts_to_try = ['Microsoft YaHei', 'Noto Sans CJK SC', 'WenQuanYi Micro Hei', 'DejaVu Sans']

            # 尝试设置字体
            for font_name in fonts_to_try:
                try:
                    plt.rcParams['font.sans-serif'] = [font_name] + plt.rcParams['font.sans-serif']
                    plt.rcParams['axes.unicode_minus'] = False  # 解决负号显示问题

                    # 测试字体是否可用
                    fig, ax = plt.subplots(figsize=(1, 1))
                    ax.text(0.5, 0.5, '测试', fontfamily=font_name)
                    plt.close(fig)

                    return font_name
                except Exception:
                    continue

            # 如果所有字体都失败，使用默认设置
            plt.rcParams['axes.unicode_minus'] = False
            return None

        except Exception as e:
            self.logger.warning(f"字体设置失败: {e}")
            return None

    def _wrap_text(self, text: str, max_chars_per_line: int = 30) -> str:
        """自动换行处理长文本

        Args:
            text: 原始文本
            max_chars_per_line: 每行最大字符数

        Returns:
            换行后的文本
        """
        if len(text) <= max_chars_per_line:
            return text

        # 按句号、逗号等标点符号分割
        sentences = re.split(r'([。，、；：！？])', text)

        lines = []
        current_line = ""

        for sentence in sentences:
            if not sentence.strip():
                continue

            # 如果当前行加上新句子不超过限制，就添加到当前行
            if len(current_line + sentence) <= max_chars_per_line:
                current_line += sentence
            else:
                # 如果当前行不为空，先保存当前行
                if current_line.strip():
                    lines.append(current_line.strip())

                # 如果单个句子太长，强制分割
                if len(sentence) > max_chars_per_line:
                    for i in range(0, len(sentence), max_chars_per_line):
                        lines.append(sentence[i:i + max_chars_per_line])
                    current_line = ""
                else:
                    current_line = sentence

        # 添加最后一行
        if current_line.strip():
            lines.append(current_line.strip())

        return '\n'.join(lines)

    def _get_smart_text_position(self, text: str) -> Tuple[float, float]:
        """智能选择文本位置，避免遮盖地图主体

        Args:
            text: 文本内容
            fontsize: 字体大小

        Returns:
            Tuple[float, float]: 相对位置 (x, y)
        """
        # 根据文本长度和已有注记数量选择位置
        text_length = len(text)
        existing_annotations = len(self.current_map_state.annotations) if self.current_map_state else 0

        # 使用智能空白区域检测
        empty_areas = self._detect_empty_areas()

        # 根据文本长度选择最佳位置
        if text_length > 50:
            # 长文本优先选择底部和角落位置
            preferred_areas = [area for area in empty_areas
                             if "底部" in area[2] or "角" in area[2]]
            if not preferred_areas:
                preferred_areas = empty_areas
        else:
            # 短文本可以使用任何空白区域
            preferred_areas = empty_areas

        # 转换为位置坐标
        preferred_positions = [(area[0], area[1]) for area in preferred_areas]

        # 如果没有找到空白区域，使用安全的默认位置
        if not preferred_positions:
            preferred_positions = [
                (0.1, 0.15),    # 左下角（安全）
                (0.9, 0.15),    # 右下角（安全）
                (0.1, 0.85),    # 左上角（安全）
                (0.9, 0.85),    # 右上角（安全）
            ]

        # 根据已有注记数量选择位置
        position_index = existing_annotations % len(preferred_positions)
        return preferred_positions[position_index]

    def _calculate_text_position(self, position: Tuple[float, float]) -> Tuple[float, float]:
        """计算文本的实际位置，支持框外位置

        Args:
            position: 相对位置 (x, y)，特殊值表示框外位置

        Returns:
            Tuple[float, float]: 实际坐标位置
        """
        xlim = self.ax.get_xlim()
        ylim = self.ax.get_ylim()

        x_range = xlim[1] - xlim[0]
        y_range = ylim[1] - ylim[0]

        # 检查是否是框外位置的特殊值
        if position[1] <= 0.05:  # 底部位置，放在框外
            # 底部框外位置
            x_pos = xlim[0] + x_range * position[0]
            y_pos = ylim[0] - y_range * 0.1  # 在底部边界下方10%的位置
        elif position[1] >= 0.95:  # 顶部位置，放在框外
            # 顶部框外位置
            x_pos = xlim[0] + x_range * position[0]
            y_pos = ylim[1] + y_range * 0.03  # 在顶部边界上方3%的位置
        elif position[0] <= 0.05:  # 左侧位置，放在框外
            # 左侧框外位置
            x_pos = xlim[0] - x_range * 0.08  # 在左边界左侧8%的位置
            y_pos = ylim[0] + y_range * position[1]
        elif position[0] >= 0.95:  # 右侧位置，放在框外
            # 右侧框外位置
            x_pos = xlim[1] + x_range * 0.03  # 在右边界右侧3%的位置
            y_pos = ylim[0] + y_range * position[1]
        else:
            # 框内位置（保持原有逻辑）
            x_pos = xlim[0] + x_range * position[0]
            y_pos = ylim[0] + y_range * position[1]

        return x_pos, y_pos

    def _add_inframe_title(self, title: str, title_props: Dict[str, Any]) -> None:
        """在地图框内添加标题，不遮挡地图内容

        Args:
            title: 标题文本
            title_props: 标题属性
        """
        # 获取地图范围
        xlim = self.ax.get_xlim()
        ylim = self.ax.get_ylim()

        # 计算标题位置（地图框内顶部）
        x_pos = xlim[0] + (xlim[1] - xlim[0]) * 0.5  # 水平居中
        y_pos = ylim[1] - (ylim[1] - ylim[0]) * 0.008  # 距离顶部5%

        # 添加标题，带背景框
        title_props.update({
            'ha': 'center',
            'va': 'top',
            'bbox': dict(boxstyle="round,pad=0.5", facecolor="white", alpha=0.9, edgecolor='darkgray')
        })

        self.ax.text(x_pos, y_pos, title, **title_props)

    def _calculate_inframe_text_position(self, position: Tuple[float, float]) -> Tuple[float, float]:
        """计算框内文本的实际位置

        Args:
            position: 相对位置 (x, y)

        Returns:
            Tuple[float, float]: 实际坐标位置
        """
        xlim = self.ax.get_xlim()
        ylim = self.ax.get_ylim()

        x_range = xlim[1] - xlim[0]
        y_range = ylim[1] - ylim[0]

        # 直接使用相对位置计算实际坐标
        x_pos = xlim[0] + x_range * position[0]
        y_pos = ylim[0] + y_range * position[1]

        return x_pos, y_pos

    def _get_bottom_position(self) -> Tuple[float, float]:
        """获取地图框底部的注释位置



        Returns:
            Tuple[float, float]: 底部位置坐标 (x, y)
        """
        # 计算已有注释数量，用于水平分布
        existing_annotations = len(self.current_map_state.annotations) if self.current_map_state else 0

        # 根据注释数量选择水平位置
        if existing_annotations == 0:
            x_pos = 0.5  # 第一个注释居中
        elif existing_annotations == 1:
            x_pos = 0.25  # 第二个注释左侧
        elif existing_annotations == 2:
            x_pos = 0.75  # 第三个注释右侧
        else:
            # 更多注释时循环使用位置
            positions = [0.5, 0.25, 0.75, 0.1, 0.9]
            x_pos = positions[existing_annotations % len(positions)]

        # y位置固定在框底部（负值表示框外）
        y_pos = -0.15  # 框底部下方

        self.logger.debug(f"底部位置计算: 第{existing_annotations + 1}个注释，位置({x_pos:.2f}, {y_pos:.2f})")
        return (x_pos, y_pos)

    def _adjust_unsafe_position(self, position: Tuple[float, float]) -> Tuple[float, float]:
        """调整不安全的位置到安全区域

        Args:
            position: 原始位置 (x, y)

        Returns:
            Tuple[float, float]: 调整后的安全位置
        """
        x, y = position

        # 调整x坐标到安全范围
        if x < 0.1:
            x = 0.1
        elif x > 0.9:
            x = 0.9

        # 调整y坐标到安全范围（避开坐标轴和标题）
        if y < 0.15:  # 底部安全区域
            y = 0.15
        elif y > 0.85:  # 顶部安全区域（避开标题）
            y = 0.85

        self.logger.debug(f"位置调整: {position} -> ({x:.2f}, {y:.2f})")
        return (x, y)

    def _detect_empty_areas(self) -> List[Tuple[float, float, str]]:
        """检测地图中的空白区域，返回可用的注释位置

        Returns:
            List[Tuple[float, float, str]]: [(x_ratio, y_ratio, description), ...]
        """
        if not self.current_map_state or not self.current_map_state.layers:
            # 如果没有图层，返回默认位置
            return [
                (0.1, 0.1, "左下角"),
                (0.9, 0.1, "右下角"),
                (0.1, 0.9, "左上角"),
                (0.9, 0.9, "右上角"),
                (0.5, 0.1, "底部中央")
            ]



        # 分析已有图层的空间分布
        occupied_areas = self._analyze_layer_distribution()

        # 定义候选位置（优先选择边角和边缘的空白区域）
        candidate_positions = [
            # 四个角落（最安全的位置）
            (0.05, 0.85, "左上角"),      # 左上角，避开标题
            (0.95, 0.85, "右上角"),      # 右上角，避开标题
            (0.05, 0.15, "左下角"),      # 左下角，避开坐标轴
            (0.95, 0.15, "右下角"),      # 右下角，避开坐标轴

            # 边缘位置
            (0.05, 0.5, "左侧中央"),     # 左侧中央
            (0.95, 0.5, "右侧中央"),     # 右侧中央
            (0.5, 0.85, "顶部中央"),     # 顶部中央，标题下方
            (0.2, 0.15, "底部左侧"),     # 底部左侧
            (0.8, 0.15, "底部右侧"),     # 底部右侧

            # 次优位置（如果边角都被占用）
            (0.15, 0.75, "左上区域"),
            (0.85, 0.75, "右上区域"),
            (0.15, 0.25, "左下区域"),
            (0.85, 0.25, "右下区域"),
        ]

        # 评估每个位置的空白程度
        empty_areas = []
        for x_ratio, y_ratio, desc in candidate_positions:
            is_empty = self._is_area_empty(x_ratio, y_ratio, occupied_areas)
            self.logger.debug(f"检查位置 {desc} ({x_ratio:.2f}, {y_ratio:.2f}): {'空白' if is_empty else '被占用'}")
            if is_empty:
                empty_areas.append((x_ratio, y_ratio, desc))

        # 如果没有找到空白区域，使用特殊策略
        if not empty_areas:
            self.logger.debug("所有候选位置都被占用，使用特殊策略选择最佳位置")
            # 对于覆盖整个地图的数据（如省级行政区），选择相对较好的位置
            # 选择框内的安全区域，优先考虑海洋区域
            empty_areas = [
                (0.15, 0.15, "左下角海域"),     # 珠江口海域（安全区域）
                (0.85, 0.15, "右下角海域"),     # 南海海域（安全区域）
                (0.15, 0.75, "左上角区域"),     # 北部区域（安全区域）
                (0.85, 0.75, "右上角区域"),     # 东北区域（安全区域）
                (0.5, 0.15, "南部海域"),        # 南海中部（安全区域）
                (0.15, 0.5, "西部区域"),        # 西部区域（安全区域）
            ]

        return empty_areas

    def _analyze_layer_distribution(self) -> List[Tuple[float, float, float, float]]:
        """分析图层的空间分布

        Returns:
            List[Tuple[float, float, float, float]]: [(min_x_ratio, min_y_ratio, max_x_ratio, max_y_ratio), ...]
        """
        occupied_areas = []

        try:
            # 获取地图范围
            xlim = self.ax.get_xlim()
            ylim = self.ax.get_ylim()
            x_range = xlim[1] - xlim[0]
            y_range = ylim[1] - ylim[0]

            # 分析每个图层的边界
            for layer in self.current_map_state.layers:
                try:
                    gdf = gpd.read_file(layer.data_source)

                    # 确保坐标系一致
                    target_crs = self.current_map_state.config.crs
                    if hasattr(target_crs, 'value'):
                        target_crs = target_crs.value

                    if gdf.crs != target_crs:
                        gdf = gdf.to_crs(target_crs)

                    # 获取图层边界
                    bounds = gdf.total_bounds  # [minx, miny, maxx, maxy]

                    # 转换为相对坐标
                    min_x_ratio = max(0, (bounds[0] - xlim[0]) / x_range)
                    min_y_ratio = max(0, (bounds[1] - ylim[0]) / y_range)
                    max_x_ratio = min(1, (bounds[2] - xlim[0]) / x_range)
                    max_y_ratio = min(1, (bounds[3] - ylim[0]) / y_range)

                    occupied_areas.append((min_x_ratio, min_y_ratio, max_x_ratio, max_y_ratio))

                except Exception as e:
                    self.logger.debug(f"分析图层 {layer.name} 分布失败: {e}")
                    continue

        except Exception as e:
            self.logger.debug(f"分析图层分布失败: {e}")

        return occupied_areas

    def _is_area_empty(self, x_ratio: float, y_ratio: float, occupied_areas: List[Tuple[float, float, float, float]],
                      buffer: float = 0.15) -> bool:
        """检查指定位置是否为空白区域

        Args:
            x_ratio, y_ratio: 位置的相对坐标
            occupied_areas: 已占用区域列表
            buffer: 缓冲区大小

        Returns:
            bool: True表示该区域为空白
        """
        # 定义检查区域（考虑文本框大小）
        check_min_x = x_ratio - buffer
        check_max_x = x_ratio + buffer
        check_min_y = y_ratio - buffer
        check_max_y = y_ratio + buffer

        # 检查是否与任何占用区域重叠
        for min_x, min_y, max_x, max_y in occupied_areas:
            # 检查重叠
            if not (check_max_x < min_x or check_min_x > max_x or
                   check_max_y < min_y or check_min_y > max_y):
                return False

        return True

    def _apply_map_scaling(self, extent: List[float], map_scale: float, margin_ratio: float) -> List[float]:
        """应用地图缩放和边距

        Args:
            extent: 原始地图范围 [min_lon, min_lat, max_lon, max_lat]
            map_scale: 地图缩放比例，>1.0放大，<1.0缩小
            margin_ratio: 边距比例，0.0-1.0，表示在原范围基础上扩展的比例

        Returns:
            List[float]: 调整后的地图范围
        """
        min_lon, min_lat, max_lon, max_lat = extent

        # 计算原始范围的中心点和尺寸
        center_lon = (min_lon + max_lon) / 2
        center_lat = (min_lat + max_lat) / 2
        width = max_lon - min_lon
        height = max_lat - min_lat

        # 应用缩放（缩放比例的倒数，因为我们要缩小地图在框内的显示）
        # map_scale < 1.0 会让地图看起来更小（显示更大的范围）
        # map_scale > 1.0 会让地图看起来更大（显示更小的范围）
        scaled_width = width / map_scale
        scaled_height = height / map_scale

        # 应用边距（增加显示范围）
        margin_width = scaled_width * margin_ratio
        margin_height = scaled_height * margin_ratio

        final_width = scaled_width + margin_width
        final_height = scaled_height + margin_height

        # 计算调整后的范围
        new_min_lon = center_lon - final_width / 2
        new_max_lon = center_lon + final_width / 2
        new_min_lat = center_lat - final_height / 2
        new_max_lat = center_lat + final_height / 2

        return [new_min_lon, new_min_lat, new_max_lon, new_max_lat]

    def _setup_axis_ticks(self, min_lon: float, max_lon: float, min_lat: float, max_lat: float):
        """设置合适的坐标轴刻度

        Args:
            min_lon, max_lon: 经度范围
            min_lat, max_lat: 纬度范围
        """
        try:
            # 计算合适的刻度间隔，使用更精确的算法
            lon_span = max_lon - min_lon
            lat_span = max_lat - min_lat

            lon_interval = self._calculate_grid_interval(lon_span)
            lat_interval = self._calculate_grid_interval(lat_span)

            # 生成刻度位置，确保覆盖整个范围
            lon_ticks = np.arange(
                np.floor(min_lon / lon_interval) * lon_interval,
                np.ceil(max_lon / lon_interval) * lon_interval + lon_interval,
                lon_interval
            )

            lat_ticks = np.arange(
                np.floor(min_lat / lat_interval) * lat_interval,
                np.ceil(max_lat / lat_interval) * lat_interval + lat_interval,
                lat_interval
            )

            # 过滤刻度，只保留在实际范围内的
            lon_ticks = lon_ticks[(lon_ticks >= min_lon - lon_interval*0.1) &
                                 (lon_ticks <= max_lon + lon_interval*0.1)]
            lat_ticks = lat_ticks[(lat_ticks >= min_lat - lat_interval*0.1) &
                                 (lat_ticks <= max_lat + lat_interval*0.1)]

            # 设置刻度
            self.ax.set_xticks(lon_ticks)
            self.ax.set_yticks(lat_ticks)

            # 设置刻度标签格式
            self.ax.set_xlabel('经度 (°)', fontsize=10)
            self.ax.set_ylabel('纬度 (°)', fontsize=10)

            # 设置网格
            self.ax.grid(True, alpha=0.3, linestyle='-', linewidth=0.5)

            self.logger.debug(f"设置坐标轴刻度 - 经度间隔: {lon_interval:.2f}°, 纬度间隔: {lat_interval:.2f}°")
            self.logger.debug(f"经度范围: {min_lon:.4f} 到 {max_lon:.4f}")
            self.logger.debug(f"纬度范围: {min_lat:.4f} 到 {max_lat:.4f}")

        except Exception as e:
            self.logger.warning(f"设置坐标轴刻度失败: {e}")

    def _calculate_grid_interval(self, span: float) -> float:
        """根据范围跨度计算一个合适的网格间隔.

        Args:
            span: 经度或纬度的跨度.

        Returns:
            一个“整齐”的间隔值.
        """
        # 目标是在范围内显示大约 5-10 个刻度
        raw_interval = span / 7

        # 将间隔规范化到一个“整齐”的数字 (e.g., 0.1, 0.5, 1, 2, 5, 10, ...)
        power = 10 ** np.floor(np.log10(raw_interval))
        normalized_interval = raw_interval / power

        if normalized_interval < 1.5:
            return 1.0 * power
        elif normalized_interval < 3.5:
            return 2.0 * power
        elif normalized_interval < 7.5:
            return 5.0 * power
        else:
            return 10.0 * power

    def get_current_state(self) -> Optional[MapState]:
        """获取当前地图状态"""
        return self.current_map_state

    def reset(self) -> None:
        """重置工具状态"""
        if self.figure:
            plt.close(self.figure)
        self.figure = None
        self.ax = None
        self.current_map_state = None
        self.logger.debug("工具状态已重置")
        # 强制垃圾回收和内存清理
        gc.collect()
