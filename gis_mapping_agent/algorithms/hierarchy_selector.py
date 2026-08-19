"""
层次选取算法

基于路网的层次结构（如道路等级、stroke重要性等）进行选取
"""

import geopandas as gpd
import numpy as np
import pandas as pd
from typing import List, Dict, Optional, Literal

from ..utils.logger import get_logger


class HierarchySelector:
    """层次选取器
    
    根据不同的层次标准选取重要的路段
    """
    
    def __init__(self, verbose: bool = True):
        """初始化层次选取器
        
        Args:
            verbose: 是否输出详细信息
        """
        self.verbose = verbose
        self.logger = get_logger("HierarchySelector")
    
    def select_by_hierarchy(
        self,
        gdf: gpd.GeoDataFrame,
        method: Literal['length', 'attribute', 'stroke_importance', 'percentile'] = 'length',
        threshold: Optional[float] = None,
        attribute_name: Optional[str] = None,
        keep_ratio: float = 0.5
    ) -> gpd.GeoDataFrame:
        """根据层次选取路段
        
        Args:
            gdf: 输入的路网GeoDataFrame
            method: 选取方法
                - 'length': 按长度选取
                - 'attribute': 按属性值选取
                - 'stroke_importance': 按stroke重要性选取
                - 'percentile': 按百分位选取
            threshold: 阈值（具体含义取决于method）
            attribute_name: 属性名称（method='attribute'时使用）
            keep_ratio: 保留比例（0-1之间）
            
        Returns:
            选取后的GeoDataFrame
        """
        if self.verbose:
            self.logger.info(f"开始层次选取，方法: {method}, 输入路段数: {len(gdf)}")
        
        if method == 'length':
            result = self._select_by_length(gdf, threshold, keep_ratio)
        elif method == 'attribute':
            result = self._select_by_attribute(gdf, attribute_name, threshold, keep_ratio)
        elif method == 'stroke_importance':
            result = self._select_by_stroke_importance(gdf, keep_ratio)
        elif method == 'percentile':
            result = self._select_by_percentile(gdf, keep_ratio)
        else:
            self.logger.warning(f"未知的选取方法: {method}，返回原始数据")
            result = gdf.copy()
        
        if self.verbose:
            self.logger.info(f"层次选取完成，输出路段数: {len(result)}")
        
        return result
    
    def _select_by_length(
        self,
        gdf: gpd.GeoDataFrame,
        threshold: Optional[float],
        keep_ratio: float
    ) -> gpd.GeoDataFrame:
        """按长度选取
        
        Args:
            gdf: 输入GeoDataFrame
            threshold: 长度阈值
            keep_ratio: 保留比例
            
        Returns:
            选取后的GeoDataFrame
        """
        # 计算长度
        gdf = gdf.copy()
        gdf['_length'] = gdf.geometry.length
        
        if threshold is not None:
            # 使用阈值
            result = gdf[gdf['_length'] >= threshold].copy()
        else:
            # 使用保留比例
            sorted_gdf = gdf.sort_values('_length', ascending=False)
            keep_count = int(len(gdf) * keep_ratio)
            result = sorted_gdf.head(keep_count).copy()
        
        result = result.drop(columns=['_length'])
        return result
    
    def _select_by_attribute(
        self,
        gdf: gpd.GeoDataFrame,
        attribute_name: Optional[str],
        threshold: Optional[float],
        keep_ratio: float
    ) -> gpd.GeoDataFrame:
        """按属性值选取
        
        Args:
            gdf: 输入GeoDataFrame
            attribute_name: 属性名称
            threshold: 属性阈值
            keep_ratio: 保留比例
            
        Returns:
            选取后的GeoDataFrame
        """
        if not attribute_name or attribute_name not in gdf.columns:
            self.logger.warning(f"属性 {attribute_name} 不存在，使用长度选取")
            return self._select_by_length(gdf, threshold, keep_ratio)
        
        gdf = gdf.copy()
        score = self._build_attribute_score(gdf[attribute_name])

        if threshold is not None:
            result = gdf[score >= threshold].copy()
        else:
            gdf['_hierarchy_score'] = score
            sorted_gdf = gdf.sort_values('_hierarchy_score', ascending=False)
            keep_count = int(len(gdf) * keep_ratio)
            result = sorted_gdf.head(keep_count).copy()
            result = result.drop(columns=['_hierarchy_score'])
        
        return result

    def _build_attribute_score(self, series):
        numeric_score = pd.to_numeric(series, errors='coerce')
        if numeric_score.notna().any():
            min_score = numeric_score.min()
            return numeric_score.fillna(min_score)

        road_class_rank = {
            'motorway': 100,
            'motorway_link': 95,
            'trunk': 90,
            'trunk_link': 85,
            'primary': 80,
            'primary_link': 75,
            'secondary': 70,
            'secondary_link': 65,
            'tertiary': 60,
            'tertiary_link': 55,
            'unclassified': 45,
            'residential': 40,
            'living_street': 35,
            'service': 30,
            'track': 20,
            'path': 15,
            'footway': 10,
            'cycleway': 10,
        }

        return series.astype(str).str.lower().map(road_class_rank).fillna(0)
    
    def _select_by_stroke_importance(
        self,
        gdf: gpd.GeoDataFrame,
        keep_ratio: float
    ) -> gpd.GeoDataFrame:
        """按stroke重要性选取

        Args:
            gdf: 输入GeoDataFrame（应该包含stroke信息）
            keep_ratio: 保留比例

        Returns:
            选取后的GeoDataFrame
        """
        # 计算综合重要性得分（考虑长度和路段数）
        gdf = gdf.copy()

        if 'segment_count' in gdf.columns and 'total_length' in gdf.columns:
            # 综合考虑路段数和总长度
            # 归一化到 [0, 1]
            max_count = gdf['segment_count'].max()
            max_length = gdf['total_length'].max()

            if max_count > 0:
                norm_count = gdf['segment_count'] / max_count
            else:
                norm_count = 0

            if max_length > 0:
                norm_length = gdf['total_length'] / max_length
            else:
                norm_length = 0

            # 综合得分：路段数权重0.4，长度权重0.6
            gdf['_importance'] = 0.4 * norm_count + 0.6 * norm_length

            # 按重要性排序并选取
            sorted_gdf = gdf.sort_values('_importance', ascending=False)
            keep_count = int(len(gdf) * keep_ratio)
            result = sorted_gdf.head(keep_count).copy()
            result = result.drop(columns=['_importance'])

            if self.verbose:
                self.logger.info(f"按 Stroke 重要性选取: 从 {len(gdf)} 条路段保留 {len(result)} 条，保留比例 {keep_ratio:.2f}")

            return result
        elif 'segment_count' in gdf.columns:
            return self._select_by_attribute(gdf, 'segment_count', None, keep_ratio)
        elif 'total_length' in gdf.columns:
            return self._select_by_attribute(gdf, 'total_length', None, keep_ratio)
        else:
            # 否则使用长度
            return self._select_by_length(gdf, None, keep_ratio)
    
    def _select_by_percentile(
        self,
        gdf: gpd.GeoDataFrame,
        keep_ratio: float
    ) -> gpd.GeoDataFrame:
        """按百分位选取
        
        Args:
            gdf: 输入GeoDataFrame
            keep_ratio: 保留比例（对应百分位）
            
        Returns:
            选取后的GeoDataFrame
        """
        gdf = gdf.copy()
        gdf['_length'] = gdf.geometry.length
        
        # 计算百分位阈值
        percentile = (1 - keep_ratio) * 100
        threshold = np.percentile(gdf['_length'], percentile)
        
        result = gdf[gdf['_length'] >= threshold].copy()
        result = result.drop(columns=['_length'])
        
        return result
