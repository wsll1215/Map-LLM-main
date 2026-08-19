"""
Stroke构建算法

基于路段的几何和拓扑关系，将多个路段合并成stroke（笔画）
参考文献：Thomson, R. C., & Richardson, D. E. (1999). The 'good continuation' principle of perceptual organization applied to the generalization of road networks.
"""

import geopandas as gpd
import numpy as np
from shapely.geometry import LineString, MultiLineString
from shapely.ops import linemerge
from typing import List, Dict, Tuple, Optional
import networkx as nx
from collections import defaultdict

from ..utils.logger import get_logger


class StrokeBuilder:
    """Stroke构建器
    
    将路网中的多个路段根据"良好延续性"原则合并成stroke
    """
    
    def __init__(self, angle_threshold: float = 45.0, verbose: bool = True):
        """初始化Stroke构建器
        
        Args:
            angle_threshold: 角度阈值（度），小于此角度认为是良好延续
            verbose: 是否输出详细信息
        """
        self.angle_threshold = angle_threshold
        self.verbose = verbose
        self.logger = get_logger("StrokeBuilder")
        
    def build_strokes(self, gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        """构建strokes
        
        Args:
            gdf: 输入的路网GeoDataFrame
            
        Returns:
            包含stroke的GeoDataFrame
        """
        if self.verbose:
            self.logger.info(f"开始构建strokes，输入路段数: {len(gdf)}")
        
        # 1. 构建拓扑网络
        graph = self._build_topology_graph(gdf)
        
        # 2. 计算每条边的延续性得分
        edge_scores = self._calculate_continuation_scores(graph, gdf)
        
        # 3. 构建strokes
        strokes = self._extract_strokes(graph, edge_scores, gdf)
        
        # 4. 创建结果GeoDataFrame
        result_gdf = self._create_stroke_gdf(strokes, gdf)
        
        if self.verbose:
            self.logger.info(f"Stroke构建完成，输出stroke数: {len(result_gdf)}")
        
        return result_gdf
    
    def _build_topology_graph(self, gdf: gpd.GeoDataFrame) -> nx.Graph:
        """构建拓扑网络图
        
        Args:
            gdf: 路网GeoDataFrame
            
        Returns:
            NetworkX图
        """
        G = nx.Graph()
        
        for idx, row in gdf.iterrows():
            geom = row.geometry
            if isinstance(geom, LineString):
                coords = list(geom.coords)
                start = coords[0]
                end = coords[-1]
                
                # 添加边，存储原始索引
                G.add_edge(start, end, idx=idx, geometry=geom)
        
        return G
    
    def _calculate_continuation_scores(
        self, 
        graph: nx.Graph, 
        gdf: gpd.GeoDataFrame
    ) -> Dict[Tuple, float]:
        """计算边之间的延续性得分
        
        Args:
            graph: 拓扑图
            gdf: 路网GeoDataFrame
            
        Returns:
            边对到得分的映射
        """
        scores = {}
        
        for node in graph.nodes():
            neighbors = list(graph.neighbors(node))
            
            # 只处理度数为2的节点（可能的延续点）
            if len(neighbors) == 2:
                edge1 = (node, neighbors[0])
                edge2 = (node, neighbors[1])
                
                # 获取几何
                geom1 = graph.edges[edge1]['geometry']
                geom2 = graph.edges[edge2]['geometry']
                
                # 计算角度
                angle = self._calculate_deflection_angle(geom1, geom2, node)
                
                # 角度越小，延续性越好
                score = 180.0 - angle
                scores[(edge1, edge2)] = score
        
        return scores
    
    def _calculate_deflection_angle(
        self, 
        line1: LineString, 
        line2: LineString, 
        junction_point: Tuple
    ) -> float:
        """计算两条线段在交点处的偏转角
        
        Args:
            line1: 第一条线段
            line2: 第二条线段
            junction_point: 交点
            
        Returns:
            偏转角（度）
        """
        # 获取线段方向
        coords1 = list(line1.coords)
        coords2 = list(line2.coords)
        
        # 确定方向向量
        if coords1[0] == junction_point:
            vec1 = np.array(coords1[1]) - np.array(coords1[0])
        else:
            vec1 = np.array(coords1[-2]) - np.array(coords1[-1])
        
        if coords2[0] == junction_point:
            vec2 = np.array(coords2[1]) - np.array(coords2[0])
        else:
            vec2 = np.array(coords2[-2]) - np.array(coords2[-1])
        
        # 计算角度
        cos_angle = np.dot(vec1, vec2) / (np.linalg.norm(vec1) * np.linalg.norm(vec2))
        cos_angle = np.clip(cos_angle, -1.0, 1.0)
        angle = np.arccos(cos_angle)
        
        return np.degrees(angle)
    
    def _extract_strokes(
        self, 
        graph: nx.Graph, 
        edge_scores: Dict, 
        gdf: gpd.GeoDataFrame
    ) -> List[List[int]]:
        """提取strokes
        
        Args:
            graph: 拓扑图
            edge_scores: 延续性得分
            gdf: 路网GeoDataFrame
            
        Returns:
            stroke列表，每个stroke是路段索引的列表
        """
        visited = set()
        strokes = []
        
        # 按得分排序边对
        sorted_pairs = sorted(edge_scores.items(), key=lambda x: x[1], reverse=True)
        
        for (edge1, edge2), score in sorted_pairs:
            # 检查角度阈值
            angle = 180.0 - score
            if angle > self.angle_threshold:
                continue
            
            idx1 = graph.edges[edge1]['idx']
            idx2 = graph.edges[edge2]['idx']
            
            if idx1 in visited or idx2 in visited:
                continue
            
            # 创建新stroke
            stroke = [idx1, idx2]
            visited.add(idx1)
            visited.add(idx2)
            
            # 尝试扩展stroke
            self._extend_stroke(stroke, graph, edge_scores, visited)
            
            strokes.append(stroke)
        
        # 添加未访问的单独路段
        for idx in gdf.index:
            if idx not in visited:
                strokes.append([idx])
        
        return strokes
    
    def _extend_stroke(
        self, 
        stroke: List[int], 
        graph: nx.Graph, 
        edge_scores: Dict, 
        visited: set
    ):
        """扩展stroke
        
        Args:
            stroke: 当前stroke
            graph: 拓扑图
            edge_scores: 延续性得分
            visited: 已访问的边
        """
        # 简化实现：不进行扩展
        # 完整实现需要递归地在两端查找可延续的边
        pass
    
    def _create_stroke_gdf(
        self, 
        strokes: List[List[int]], 
        gdf: gpd.GeoDataFrame
    ) -> gpd.GeoDataFrame:
        """创建stroke的GeoDataFrame
        
        Args:
            strokes: stroke列表
            gdf: 原始路网GeoDataFrame
            
        Returns:
            stroke的GeoDataFrame
        """
        stroke_data = []
        
        for stroke_id, stroke_indices in enumerate(strokes):
            # 合并几何
            lines = [gdf.loc[idx, 'geometry'] for idx in stroke_indices]
            
            if len(lines) == 1:
                merged_geom = lines[0]
            else:
                # 尝试合并线段
                try:
                    merged_geom = linemerge(lines)
                except:
                    # 如果合并失败，使用MultiLineString
                    merged_geom = MultiLineString(lines)
            
            # 计算stroke属性
            total_length = sum(gdf.loc[idx, 'geometry'].length for idx in stroke_indices)
            
            stroke_data.append({
                'stroke_id': stroke_id,
                'segment_count': len(stroke_indices),
                'total_length': total_length,
                'geometry': merged_geom
            })
        
        result_gdf = gpd.GeoDataFrame(stroke_data, crs=gdf.crs)
        
        return result_gdf

