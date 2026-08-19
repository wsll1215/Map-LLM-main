"""Map element operations."""

from typing import Any, Dict

import matplotlib
matplotlib.use('Agg')
import numpy as np

from ...models.schemas import AnnotationConfig
from ...utils.helpers import generate_unique_id, haversine

class ElementOperationsMixin:
    def _draw_scalebar(self, params: Dict[str, Any]):
        if not self.ax: return

        # 获取地图范围和中心点
        xlim = self.ax.get_xlim()
        ylim = self.ax.get_ylim()

        center_lat = sum(ylim) / 2

        # 计算地图宽度（公里）
        map_width_km = haversine(xlim[0], center_lat, xlim[1], center_lat)

        # 自动计算合适的比例尺长度
        # 目标是让比例尺长度约为地图宽度的1/4到1/6
        target_scale_km = map_width_km / 5
        # 将目标长度圆整到一个“好看”的数字 (e.g., 1, 2, 5, 10, 20, 50, 100, ...)
        power = 10**np.floor(np.log10(target_scale_km))
        normalized_target = target_scale_km / power
        if normalized_target < 1.5: round_scale_km = 1 * power
        elif normalized_target < 3.5: round_scale_km = 2 * power
        elif normalized_target < 7.5: round_scale_km = 5 * power
        else: round_scale_km = 10 * power

        # 获取当前地图的经度刻度间隔
        lon_span = xlim[1] - xlim[0]
        lon_interval = self._calculate_grid_interval(lon_span)

        # 固定比例尺长度为1个刻度间隔对应的实际距离（忽略用户传入的length参数）
        one_tick_km = haversine(xlim[0], center_lat, xlim[0] + lon_interval, center_lat)
        length = one_tick_km
        units = params.get('units', 'km')

        # 如果用户传入了length参数，记录但不使用
        user_length = params.get('length')
        if user_length:
            self.logger.debug(f"用户指定比例尺长度 {user_length} km，但系统将使用1个刻度间隔对应的距离 {length:.0f} km")

        # 比例尺在地图坐标系中的长度固定为1个刻度间隔
        scale_length_in_degrees = lon_interval

        self.logger.debug("比例尺计算完成")
        self.logger.debug(f"地图范围: 经度 {xlim[0]:.3f}° 到 {xlim[1]:.3f}°，纬度 {ylim[0]:.3f}° 到 {ylim[1]:.3f}°")
        self.logger.debug(f"中心纬度: {center_lat:.3f}°，地图实际宽度: {map_width_km:.1f} km")
        self.logger.debug(f"刻度间隔: {lon_interval:.3f}°，比例尺长度: {length:.0f} km")

        # 设置比例尺位置
        position = params.get('position', [0.01, 0.01])  # 左下角，与初始化时保持一致
        x_pos = xlim[0] + (xlim[1] - xlim[0]) * position[0]
        y_pos = ylim[0] + (ylim[1] - ylim[0]) * position[1]

        # 绘制比例尺
        self.ax.plot([x_pos, x_pos + scale_length_in_degrees], [y_pos, y_pos], 'k-', linewidth=2, zorder=10)
        font_props = {'fontsize': 8}
        if self.chinese_font:
            font_props['fontfamily'] = self.chinese_font
        self.ax.text(x_pos + scale_length_in_degrees / 2, y_pos + (ylim[1] - ylim[0]) * 0.01, f'{int(length)} {units}', ha='center', va='bottom', zorder=10, **font_props)

    def add_scalebar(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """添加比例尺"""
        try:
            if not self.current_map_state:
                raise ValueError("请先初始化地图")

            # 使其幂等，如果已存在则不重复添加
            if self.current_map_state.scalebar and not params:
                self.logger.info("比例尺已存在，跳过重复添加。")
                return {"success": True, "message": "比例尺已存在，无需重复添加。"}

            scalebar_params = {
                "position": params.get('position', [0.01, 0.01]),
                "units": params.get('units', 'km'),
                "length": params.get('length')  # 传递用户指定的长度
            }
            self.current_map_state.scalebar = scalebar_params

            message = f"成功添加或更新比例尺"
            self.logger.info(message)
            return {"success": True, "message": message}

        except Exception as e:
            error_msg = f"添加比例尺失败: {str(e)}"
            self.logger.error(error_msg)
            return {"success": False, "message": error_msg, "error": str(e)}

    def _draw_compass(self, params: Dict[str, Any]):
        if not self.ax: return
        position = params.get('position', [0.9, 0.9])
        size = params.get('size', 0.05)

        # 处理position参数：如果是字符串，转换为坐标
        if isinstance(position, str):
            position_map = {
                "右上角": [0.9, 0.9],
                "左上角": [0.1, 0.9],
                "右下角": [0.9, 0.1],
                "左下角": [0.1, 0.1],
                "upper right": [0.9, 0.9],
                "upper left": [0.1, 0.9],
                "lower right": [0.9, 0.1],
                "lower left": [0.1, 0.1]
            }
            position = position_map.get(position, [0.9, 0.9])

        # 确保position是列表
        if not isinstance(position, (list, tuple)):
            position = [0.9, 0.9]

        # 确保size是数值
        if not isinstance(size, (int, float)):
            size = 0.05

        xlim = self.ax.get_xlim()
        ylim = self.ax.get_ylim()
        x_pos = xlim[0] + (xlim[1] - xlim[0]) * float(position[0])
        y_pos = ylim[0] + (ylim[1] - ylim[0]) * float(position[1])
        arrow_length = (ylim[1] - ylim[0]) * float(size)
        self.ax.annotate('', xy=(x_pos, y_pos + arrow_length), xytext=(x_pos, y_pos), arrowprops=dict(arrowstyle='->', lw=2, color='black'))
        font_props = {'fontsize': 12, 'fontweight': 'bold'}
        if self.chinese_font:
            font_props['fontfamily'] = self.chinese_font
        self.ax.text(x_pos, y_pos + arrow_length + 0.01, 'N', ha='center', va='bottom', **font_props)

    def add_compass(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """添加指北针"""
        try:
            if not self.current_map_state:
                raise ValueError("请先初始化地图")

            # 使其幂等，如果已存在则不重复添加
            if self.current_map_state.compass and not params:
                self.logger.info("指北针已存在，跳过重复添加。")
                return {"success": True, "message": "指北针已存在，无需重复添加。"}

            compass_params = {
                "position": params.get('position', [0.9, 0.9]),
                "size": params.get('size', 0.05)
            }
            self.current_map_state.compass = compass_params

            message = "成功添加或更新指北针"
            self.logger.info(message)
            return {"success": True, "message": message}

        except Exception as e:
            error_msg = f"添加指北针失败: {str(e)}"
            self.logger.error(error_msg)
            return {"success": False, "message": error_msg, "error": str(e)}

    def add_annotation(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """添加标题和文本注记

        Args:
            params: 注记参数
                - text: 文本内容
                - position: 位置 (x, y)
                - fontsize: 字体大小
                - color: 文字颜色
                - ha: 水平对齐 ('left', 'center', 'right')
                - va: 垂直对齐 ('top', 'center', 'bottom')

        Returns:
            Dict: 操作结果
        """
        try:
            if not self.current_map_state:
                raise ValueError("请先初始化地图")

            text = params.get('text', '')
            fontsize = params.get('fontsize', 14)

            # 使用固定的底部位置，确保注记在横坐标轴下方
            position = [0.5, 0.03]  # 固定位置：水平居中，垂直在横坐标轴下方
            self.logger.debug(f"使用固定底部位置: {position}")

            # 安全检查：防止与主标题重复
            if self.current_map_state.config.title and text == self.current_map_state.config.title:
                self.logger.warning(f"注记 '{text}' 与地图主标题重复，已忽略。")
                return {"success": True, "message": "注记与主标题重复，已忽略。"}

            x_pos, y_pos = position
            # 安全检查：防止注记与地图标题重叠
            if y_pos > 0.9:
                self.logger.warning(f"注记位置 y={y_pos} 过高，可能与标题重叠，自动调整到0.9。")
                y_pos = 0.9

            color = params.get('color', 'black')
            ha = params.get('ha', 'center')

            if not text:
                raise ValueError("必须提供text参数")

            # 处理长文本自动换行
            wrapped_text = self._wrap_text(text, max_chars_per_line=50)

            # 添加文本，使用中文字体
            text_props = {
                'fontsize': fontsize,
                'color': color,
                'ha': 'center',
                'va': 'center',
                'bbox': dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.9, edgecolor='lightgray'),
                'linespacing': 1.2,
                'transform': self.figure.transFigure  # 使用figure坐标
            }

            # 如果设置了中文字体，使用它
            if self.chinese_font:
                text_props['fontfamily'] = self.chinese_font

            # 使用figure.text将注释放置在图表底部
            self.figure.text(x_pos, y_pos, wrapped_text, **text_props)
            self.logger.debug(f"注释放置在图表底部: ({x_pos:.2f}, {y_pos:.2f})")

            # 创建注记配置
            annotation_config = AnnotationConfig(
                annotation_id=generate_unique_id(),
                text=text,
                position=position,
                font_size=fontsize,
                color=color,
                alignment=ha if ha in ["left", "center", "right"] else "center"
            )

            self.current_map_state.annotations.append(annotation_config)

            message = f"成功添加文本注记: {text[:20]}..."
            self.logger.info(message)

            return {
                "success": True,
                "message": message,
                "annotation_id": annotation_config.annotation_id
            }

        except Exception as e:
            error_msg = f"添加文本注记失败: {str(e)}"
            self.logger.error(error_msg)
            return {
                "success": False,
                "message": error_msg,
                "error": str(e)
            }

    def modify_element(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """修改已有元素的位置、大小、字体、颜色等

        Args:
            params: 修改参数
                - element_type: 元素类型 ('layer', 'legend', 'annotation', 'map')
                - element_id: 元素ID或名称
                - properties: 要修改的属性字典

        Returns:
            Dict: 操作结果
        """
        try:
            if not self.current_map_state:
                raise ValueError("请先初始化地图")

            element_type = params.get('element_type')
            element_id = params.get('element_id')
            properties = params.get('properties', {})

            if not element_type or not element_id:
                raise ValueError("必须提供element_type和element_id参数")

            modified = False

            if element_type == 'layer':
                for layer in self.current_map_state.layers:
                    if layer.layer_id == element_id or layer.name == element_id:
                        # 更新图层样式属性
                        for key, value in properties.items():
                            if hasattr(layer.style, key):
                                setattr(layer.style, key, value)
                        modified = True
                        break

            elif element_type == 'legend':
                for legend in self.current_map_state.legends:
                    if legend.legend_id == element_id:
                        if 'title' in properties:
                            legend.title = properties['title']
                        if 'position' in properties:
                            legend.position = properties['position']
                        modified = True
                        break

            elif element_type == 'annotation':
                for annotation in self.current_map_state.annotations:
                    if annotation.annotation_id == element_id:
                        # 更新注记属性
                        for key, value in properties.items():
                            if hasattr(annotation, key):
                                setattr(annotation, key, value)
                        modified = True
                        break

            elif element_type == 'map':
                # 修改地图配置属性
                config = self.current_map_state.config
                for key, value in properties.items():
                    if hasattr(config, key):
                        setattr(config, key, value)
                        modified = True
                        self.logger.debug(f"修改地图配置 {key}: {value}")

            if not modified:
                raise ValueError(f"未找到指定的{element_type}: {element_id}")

            message = f"成功修改{element_type}: {element_id}"
            self.logger.info(message)

            return {
                "success": True,
                "message": message
            }

        except Exception as e:
            error_msg = f"修改元素失败: {str(e)}"
            self.logger.error(error_msg)
            return {
                "success": False,
                "message": error_msg,
                "error": str(e)
            }

    def generate_symbol(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """根据文本描述生成图例符号

        Args:
            params: 符号参数
                - description: 文本描述
                - symbol_type: 符号类型 ('point', 'line', 'polygon')
                - color: 颜色
                - size: 大小

        Returns:
            Dict: 操作结果
        """
        try:
            description = params.get('description', '')
            symbol_type = params.get('symbol_type', 'point')
            color = params.get('color', 'blue')
            size = params.get('size', 10)

            # 简化的符号生成逻辑
            symbol_config = {
                "type": symbol_type,
                "color": color,
                "size": size,
                "description": description
            }

            # 根据描述调整颜色（简化逻辑）
            if '红' in description or 'red' in description.lower():
                symbol_config["color"] = 'red'
            elif '蓝' in description or 'blue' in description.lower():
                symbol_config["color"] = 'blue'
            elif '绿' in description or 'green' in description.lower():
                symbol_config["color"] = 'green'

            message = f"成功生成符号: {description}"
            self.logger.info(message)

            return {
                "success": True,
                "message": message,
                "symbol_config": symbol_config
            }

        except Exception as e:
            error_msg = f"生成符号失败: {str(e)}"
            self.logger.error(error_msg)
            return {
                "success": False,
                "message": error_msg,
                "error": str(e)
            }
