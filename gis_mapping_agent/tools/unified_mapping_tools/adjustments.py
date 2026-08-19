"""Layer and element adjustment operations."""

from typing import Any, Dict

from ...models.schemas import LegendItem

class AdjustmentOperationsMixin:
    def remove_layer(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """移除指定图层
        
        Args:
            params: 移除参数
                - layer_name: 要移除的图层名称
                
        Returns:
            Dict: 操作结果
        """
        try:
            if not self.current_map_state:
                raise ValueError("请先初始化地图")
            
            layer_name = params.get('layer_name')
            if not layer_name:
                raise ValueError("必须提供layer_name参数")
            
            # 找到目标图层
            target_layer = None
            for layer in self.current_map_state.layers:
                if layer.name == layer_name:
                    target_layer = layer
                    break
            
            if not target_layer:
                raise ValueError(f"未找到图层: {layer_name}")
            
            # 设置图层为不可见
            target_layer.visible = False
            
            # 从图例项中移除
            chinese_name = self.LAYER_NAME_MAPPING.get(layer_name, layer_name)
            self.current_map_state.legend_items = [
                item for item in self.current_map_state.legend_items 
                if item.label != chinese_name
            ]
            
            # 重新绘制地图
            self._redraw_map()
            
            message = f"成功移除图层: {layer_name}"
            self.logger.info(message)
            return {"success": True, "message": message}
            
        except Exception as e:
            error_msg = f"移除图层失败: {str(e)}"
            self.logger.error(error_msg)
            return {"success": False, "message": error_msg, "error": str(e)}

    def toggle_layer_visibility(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """切换图层显示/隐藏状态
        
        Args:
            params: 切换参数
                - layer_name: 图层名称
                - visible: 可见性（可选，如果不提供则自动切换）
                
        Returns:
            Dict: 操作结果
        """
        try:
            if not self.current_map_state:
                raise ValueError("请先初始化地图")
            
            layer_name = params.get('layer_name')
            if not layer_name:
                raise ValueError("必须提供layer_name参数")
            
            # 找到目标图层
            target_layer = None
            for layer in self.current_map_state.layers:
                if layer.name == layer_name:
                    target_layer = layer
                    break
            
            if not target_layer:
                raise ValueError(f"未找到图层: {layer_name}")
            
            # 设置可见性
            if 'visible' in params:
                target_layer.visible = params['visible']
            else:
                # 自动切换
                target_layer.visible = not target_layer.visible
            
            # 更新图例
            chinese_name = self.LAYER_NAME_MAPPING.get(layer_name, layer_name)
            if target_layer.visible:
                # 如果图层变为可见，确保图例项存在
                existing_item = any(item.label == chinese_name for item in self.current_map_state.legend_items)
                if not existing_item:
                    legend_type = 'line' if target_layer.geometry_type.value == 'line' else ('point' if target_layer.geometry_type.value == 'point' else 'patch')
                    legend_item = LegendItem(
                        label=chinese_name,
                        type=legend_type,
                        style=target_layer.style.model_dump()
                    )
                    self.current_map_state.legend_items.append(legend_item)
            else:
                # 如果图层变为不可见，移除图例项
                self.current_map_state.legend_items = [
                    item for item in self.current_map_state.legend_items 
                    if item.label != chinese_name
                ]
            
            # 重新绘制地图
            self._redraw_map()
            
            visibility_status = "显示" if target_layer.visible else "隐藏"
            message = f"成功{visibility_status}图层: {layer_name}"
            self.logger.info(message)
            return {"success": True, "message": message}
            
        except Exception as e:
            error_msg = f"切换图层可见性失败: {str(e)}"
            self.logger.error(error_msg)
            return {"success": False, "message": error_msg, "error": str(e)}

    def update_map_title(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """更新地图标题
        
        Args:
            params: 更新参数
                - title: 新标题
                
        Returns:
            Dict: 操作结果
        """
        try:
            if not self.current_map_state:
                raise ValueError("请先初始化地图")
            
            new_title = params.get('title')
            if not new_title:
                raise ValueError("必须提供title参数")
            
            # 更新配置中的标题
            old_title = self.current_map_state.config.title
            self.current_map_state.config.title = new_title
            
            # 更新matplotlib图形的标题
            if self.figure:
                title_props = {'fontsize': 14, 'fontweight': 'bold'}
                if self.chinese_font:
                    title_props['fontfamily'] = self.chinese_font
                self.figure.suptitle(new_title, **title_props)
            
            message = f"成功更新地图标题: '{old_title}' -> '{new_title}'"
            self.logger.info(message)
            return {"success": True, "message": message}
            
        except Exception as e:
            error_msg = f"更新地图标题失败: {str(e)}"
            self.logger.error(error_msg)
            return {"success": False, "message": error_msg, "error": str(e)}

    def clear_annotations(self, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """清除所有文字注记

        Returns:
            Dict: 操作结果
        """
        try:
            if not self.current_map_state:
                raise ValueError("请先初始化地图")

            annotation_count = len(self.current_map_state.annotations)
            self.current_map_state.annotations.clear()

            # 重新绘制地图以移除注记
            self._redraw_map()

            message = f"成功清除 {annotation_count} 个文字注记"
            self.logger.info(message)
            return {"success": True, "message": message}

        except Exception as e:
            error_msg = f"清除注记失败: {str(e)}"
            self.logger.error(error_msg)
            return {"success": False, "message": error_msg, "error": str(e)}

    def remove_scalebar(self, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """删除比例尺

        Returns:
            Dict: 操作结果
        """
        try:
            if not self.current_map_state:
                raise ValueError("请先初始化地图")

            if self.current_map_state.scalebar is None:
                return {"success": False, "message": "地图中没有比例尺"}

            self.current_map_state.scalebar = None
            self.current_map_state.config.auto_scalebar = False

            # 重新绘制地图以移除比例尺
            self._redraw_map()

            message = "成功删除比例尺"
            self.logger.info(message)
            return {"success": True, "message": message}

        except Exception as e:
            error_msg = f"删除比例尺失败: {str(e)}"
            self.logger.error(error_msg)
            return {"success": False, "message": error_msg, "error": str(e)}

    def remove_compass(self, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """删除指北针

        Returns:
            Dict: 操作结果
        """
        try:
            if not self.current_map_state:
                raise ValueError("请先初始化地图")

            if self.current_map_state.compass is None:
                return {"success": False, "message": "地图中没有指北针"}

            self.current_map_state.compass = None
            self.current_map_state.config.auto_compass = False

            # 重新绘制地图以移除指北针
            self._redraw_map()

            message = "成功删除指北针"
            self.logger.info(message)
            return {"success": True, "message": message}

        except Exception as e:
            error_msg = f"删除指北针失败: {str(e)}"
            self.logger.error(error_msg)
            return {"success": False, "message": error_msg, "error": str(e)}
