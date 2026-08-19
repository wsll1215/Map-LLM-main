"""地图渲染器 - 负责根据地图状态渲染地图"""

from typing import Optional, Dict, Any
from pathlib import Path
import matplotlib.pyplot as plt
from datetime import datetime

from ..models.schemas import MapState
from ..utils.config import Config
from ..utils.logger import get_logger
from ..utils.singleton import singleton
from .elements import MapQualityChecker


class MapRenderer:
    """地图渲染器
    
    负责根据地图状态渲染地图，支持版本化的渲染结果保存
    """
    
    def __init__(self, output_dir: Optional[str] = None):
        """初始化渲染器
        
        Args:
            output_dir: 输出目录，默认使用配置中的输出目录
        """
        self.logger = get_logger("MapRenderer")
        
        if output_dir is None:
            self.output_dir = Config.OUTPUT_DIR
        else:
            self.output_dir = Path(output_dir)
        
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # 初始化统一制图工具
        self.mapping_tools = None
        self.quality_checker = MapQualityChecker()
        
        self.logger.info(f"地图状态管理器、渲染器初始化完成")
    
    def render_map(self, map_state: MapState, save_file: bool = True, 
                   custom_filename: Optional[str] = None) -> Dict[str, Any]:
        """渲染地图
        
        Args:
            map_state: 地图状态
            save_file: 是否保存文件
            custom_filename: 自定义文件名
            
        Returns:
            Dict: 渲染结果，包含文件路径、渲染信息等
        """
        try:
            # 初始化制图工具
            if self.mapping_tools is None:
                from ..tools.unified_mapping_tools import UnifiedMappingTools
                self.mapping_tools = UnifiedMappingTools()
            
            # 重置制图工具状态（如果方法存在）
            if hasattr(self.mapping_tools, '_reset_state'):
                self.mapping_tools._reset_state()
            else:
                # 手动重置状态
                self.mapping_tools.current_map_state = None
            
            # 根据地图状态重建地图
            self._rebuild_map_from_state(map_state)
            
            result = {
                "success": True,
                "session_id": map_state.get_session_id(),
                "version": map_state.get_current_version(),
                "rendered_at": datetime.now().isoformat(),
                "file_path": None,
                "message": "地图渲染成功"
            }
            
            # 保存文件
            if save_file:
                filename = self._generate_filename(map_state, custom_filename)

                # 只传递文件名，让map_save处理输出目录
                save_params = {
                    "filename": filename,
                    "output_dir": str(self.output_dir),
                    "dpi": map_state.config.dpi or Config.DEFAULT_DPI,
                    "format": "png"
                }
                self.mapping_tools.map_save(save_params)

                # 构建完整路径用于返回结果
                file_path = self.output_dir / filename
                
                result["file_path"] = str(file_path)
                result["message"] = f"地图已保存到: {file_path}"
                map_state.output_path = str(file_path)

            result["quality"] = self.quality_checker.check(map_state, result.get("file_path"))
            
            # self.logger.info(f"地图渲染完成: 会话 {map_state.get_session_id()}, 版本 {map_state.get_current_version()}")
            return result
            
        except Exception as e:
            self.logger.error(f"地图渲染失败: {e}")
            return {
                "success": False,
                "error": str(e),
                "message": "地图渲染失败"
            }
    
    def render_comparison(self, old_state: MapState, new_state: MapState) -> Dict[str, Any]:
        """渲染对比图（显示修改前后的差异）
        
        Args:
            old_state: 修改前的状态
            new_state: 修改后的状态
            
        Returns:
            Dict: 渲染结果
        """
        try:
            # 创建对比图布局
            fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(20, 10))
            
            # 渲染修改前的地图
            self._render_state_to_axis(old_state, ax1, "修改前")
            
            # 渲染修改后的地图
            self._render_state_to_axis(new_state, ax2, "修改后")
            
            # 保存对比图
            filename = f"comparison_{new_state.get_session_id()}_v{old_state.get_current_version()}_to_v{new_state.get_current_version()}.png"
            file_path = self.output_dir / filename
            
            plt.tight_layout()
            plt.savefig(file_path, dpi=Config.HYPERPARAMETERS.COMPARISON_DPI, bbox_inches='tight')
            plt.close()
            
            self.logger.info(f"对比图渲染完成: {file_path}")
            
            return {
                "success": True,
                "file_path": str(file_path),
                "message": "对比图渲染成功"
            }
            
        except Exception as e:
            self.logger.error(f"对比图渲染失败: {e}")
            return {
                "success": False,
                "error": str(e),
                "message": "对比图渲染失败"
            }
    
    def _rebuild_map_from_state(self, map_state: MapState) -> None:
        """根据地图状态重建地图"""
        # 1. 初始化地图
        init_params = {
            "title": map_state.config.title,
            "extent": map_state.config.extent,
            "crs": map_state.config.crs,
            "background_color": map_state.config.background_color,
            "figsize": map_state.config.figsize,
            "dpi": map_state.config.dpi,
            # 关键修复：传递自动添加配置
            "auto_compass": map_state.config.auto_compass,
            "auto_scalebar": map_state.config.auto_scalebar,
            "auto_legend": map_state.config.auto_legend
        }
        self.mapping_tools.init_map(init_params)
        
        # 2. 添加图层
        for layer in map_state.layers:
            # 数据路径直接使用数据库中保存的相对路径
            # 不需要额外处理，add_layer 方法会正确解析
            data_path = layer.data_source

            # 显示相对路径而不是绝对路径
            from pathlib import Path
            from ..utils.config import Config
            try:
                if data_path:
                    path_obj = Path(data_path)
                    if path_obj.is_absolute():
                        rel_path = path_obj.relative_to(Config.PROJECT_ROOT)
                        display_path = str(rel_path)
                    else:
                        display_path = data_path
                else:
                    display_path = data_path
            except (ValueError, Exception):
                display_path = data_path

            self.logger.info(f"准备添加图层: {layer.name}, 数据路径: {display_path}")

            layer_params = {
                "data_path": data_path,
                "name": layer.name,  # 修正参数名：layer_name -> name
                "style": layer.style.model_dump() if layer.style else None,
                "visible": layer.visible  # 关键修复：传递visible参数
            }
            add_result = self.mapping_tools.add_layer(layer_params)
            if isinstance(add_result, dict) and not add_result.get("success", False):
                raise ValueError(f"重建图层失败: {layer.name}，原因: {add_result.get('message') or add_result.get('error')}")
        
        # 3. 添加注记
        for annotation in map_state.annotations:
            annotation_params = {
                "text": annotation.text,
                "position": annotation.position,
                "font_size": annotation.font_size,
                "font_family": annotation.font_family,
                "color": annotation.color,
                "background_color": annotation.background_color,
                "rotation": annotation.rotation,
                "alignment": annotation.alignment
            }
            self.mapping_tools.add_annotation(annotation_params)
        
        # 4. 添加比例尺
        if map_state.scalebar:
            self.mapping_tools.add_scalebar(map_state.scalebar)

        # 5. 添加指北针
        if map_state.compass:
            self.mapping_tools.add_compass(map_state.compass)
        
        # 6. 更新图例
        if map_state.legend_items:
            # 自动绘制图例
            self.mapping_tools._draw_auto_legend()

        # 关键修复：调用_redraw_map来实际绘制所有图层
        self.mapping_tools._redraw_map()
    
    def _render_state_to_axis(self, map_state: MapState, ax, title: str) -> None:
        """将地图状态渲染到指定的坐标轴"""
        # 这是一个简化版本，实际实现需要更复杂的逻辑
        # 暂时使用占位符
        ax.text(0.5, 0.5, f"{title}\n会话: {map_state.get_session_id()}\n版本: {map_state.get_current_version()}", 
                ha='center', va='center', transform=ax.transAxes)
        ax.set_title(title)
    
    def _generate_filename(self, map_state: MapState, custom_filename: Optional[str] = None) -> str:
        """生成文件名"""
        if custom_filename:
            return custom_filename
        
        session_id = map_state.get_session_id()[:8]  # 使用前8位作为简短标识
        version = map_state.get_current_version()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        return f"map_{session_id}_v{version}_{timestamp}.png"
    
    def get_render_history(self, session_id: str) -> list:
        """获取会话的渲染历史
        
        Args:
            session_id: 会话ID
            
        Returns:
            list: 渲染历史文件列表
        """
        try:
            session_prefix = session_id[:8]
            pattern = f"map_{session_prefix}_v*_*.png"
            
            files = list(self.output_dir.glob(pattern))
            files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
            
            return [str(f) for f in files]
            
        except Exception as e:
            self.logger.error(f"获取渲染历史失败: {e}")
            return []
    
    def cleanup_old_renders(self, session_id: str, keep_count: int = Config.HYPERPARAMETERS.RENDER_HISTORY_KEEP_COUNT) -> None:
        """清理旧的渲染文件
        
        Args:
            session_id: 会话ID
            keep_count: 保留的文件数量
        """
        try:
            history = self.get_render_history(session_id)
            
            if len(history) > keep_count:
                files_to_delete = history[keep_count:]
                
                for file_path in files_to_delete:
                    Path(file_path).unlink(missing_ok=True)
                
                self.logger.info(f"清理了 {len(files_to_delete)} 个旧渲染文件")
                
        except Exception as e:
            self.logger.error(f"清理渲染文件失败: {e}")


# 使用单例装饰器创建全局渲染器
@singleton
class _MapRendererSingleton:
    """地图渲染器单例包装器"""
    def __init__(self):
        self.renderer = MapRenderer()

def get_map_renderer() -> MapRenderer:
    """获取全局地图渲染器实例

    Returns:
        MapRenderer: 全局唯一的地图渲染器实例

    Note:
        使用单例模式确保整个应用只有一个渲染器实例
    """
    return _MapRendererSingleton().renderer
