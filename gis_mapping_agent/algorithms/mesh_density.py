"""
网眼密度计算算法

计算路网的网眼密度，用于评估路网的复杂程度
"""

import geopandas as gpd
import numpy as np
from shapely.geometry import Polygon, MultiPolygon
from shapely.ops import polygonize, unary_union
from typing import List, Dict, Optional

from ..utils.logger import get_logger


class MeshDensityCalculator:
    """网眼密度计算器
    
    计算路网形成的网眼（面）的密度
    """
    
    def __init__(self, verbose: bool = True):
        """初始化网眼密度计算器
        
        Args:
            verbose: 是否输出详细信息
        """
        self.verbose = verbose
        self.logger = get_logger("MeshDensityCalculator")
    
    def calculate_mesh_density(
        self, 
        gdf: gpd.GeoDataFrame,
        area_threshold: Optional[float] = None
    ) -> Dict:
        """计算网眼密度
        
        Args:
            gdf: 路网GeoDataFrame
            area_threshold: 面积阈值，小于此值的网眼被认为是密集区域
            
        Returns:
            包含密度信息的字典
        """
        if self.verbose:
            self.logger.info("开始计算网眼密度")
        
        # 1. 提取所有线段
        lines = []
        for geom in gdf.geometry:
            if geom.geom_type == 'LineString':
                lines.append(geom)
            elif geom.geom_type == 'MultiLineString':
                lines.extend(list(geom.geoms))
        
        # 2. 构建多边形（网眼）
        try:
            polygons = list(polygonize(lines))
        except:
            self.logger.warning("无法构建网眼，返回空结果")
            return {
                'mesh_count': 0,
                'total_area': 0,
                'average_area': 0,
                'density': 0
            }
        
        if not polygons:
            return {
                'mesh_count': 0,
                'total_area': 0,
                'average_area': 0,
                'density': 0
            }
        
        # 3. 计算统计信息
        areas = [poly.area for poly in polygons]
        total_area = sum(areas)
        average_area = np.mean(areas)
        
        # 4. 计算密度（网眼数量/总面积）
        density = len(polygons) / total_area if total_area > 0 else 0
        
        # 5. 如果指定了阈值，计算密集区域
        dense_meshes = []
        if area_threshold:
            dense_meshes = [poly for poly in polygons if poly.area < area_threshold]
        
        result = {
            'mesh_count': len(polygons),
            'total_area': total_area,
            'average_area': average_area,
            'min_area': min(areas),
            'max_area': max(areas),
            'density': density,
            'dense_mesh_count': len(dense_meshes) if area_threshold else None,
            'polygons': polygons
        }
        
        if self.verbose:
            self.logger.info(f"网眼密度计算完成: {len(polygons)}个网眼, 平均面积: {average_area:.2f}")
        
        return result
    
    def create_mesh_gdf(self, mesh_info: Dict, crs) -> gpd.GeoDataFrame:
        """创建网眼的GeoDataFrame
        
        Args:
            mesh_info: 网眼信息字典
            crs: 坐标系
            
        Returns:
            网眼的GeoDataFrame
        """
        polygons = mesh_info.get('polygons', [])
        
        if not polygons:
            return gpd.GeoDataFrame(columns=['mesh_id', 'area', 'geometry'], crs=crs)
        
        data = []
        for i, poly in enumerate(polygons):
            data.append({
                'mesh_id': i,
                'area': poly.area,
                'geometry': poly
            })
        
        return gpd.GeoDataFrame(data, crs=crs)

