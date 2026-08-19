"""地理数据加载和处理模块"""

import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
import geopandas as gpd
import pandas as pd
from shapely.geometry import Point, LineString, Polygon
import warnings

from .config import Config
from .logger import get_logger

# 忽略一些常见的警告
warnings.filterwarnings('ignore', category=UserWarning)


class DataLoader:
    """地理数据加载器"""

    def __init__(self):
        self.logger = get_logger("DataLoader")
        self.data_dir = Config.DATA_DIRECTORY_BASE
        self.loaded_data = {}  # 缓存已加载的数据

    def load_shapefile(self, filename: str, encoding: str = 'utf-8') -> Optional[gpd.GeoDataFrame]:
        """加载Shapefile文件

        Args:
            filename: 文件名（可以是相对路径或绝对路径）
            encoding: 文件编码

        Returns:
            GeoDataFrame或None
        """
        try:
            # 处理文件路径
            if filename.startswith('../data/'):
                # 特殊处理 ../data/ 路径，指向 gis_mapping_agent/data/
                relative_filename = filename.replace('../data/', '')
                file_path = self.data_dir / relative_filename
            elif filename.startswith('../'):
                # 其他相对路径，从项目根目录开始
                file_path = Config.PROJECT_ROOT / filename.lstrip('../')
            elif os.path.isabs(filename):
                # 绝对路径
                file_path = Path(filename)
            elif filename.startswith('data/') or filename.startswith('data\\'):
                # 相对于PROJECT_ROOT的路径（如 "data/data1/Highway.shp"）
                file_path = Config.PROJECT_ROOT / filename
            else:
                # 其他情况：首先尝试相对于PROJECT_ROOT
                potential_path = Config.PROJECT_ROOT / filename
                if potential_path.exists():
                    file_path = potential_path
                else:
                    # 如果不存在，尝试相对于data目录
                    file_path = self.data_dir / filename

            # 确保文件存在
            if not file_path.exists():
                self.logger.error(f"文件不存在: {file_path}")
                return None

            # 检查缓存
            cache_key = str(file_path)
            if cache_key in self.loaded_data:
                self.logger.debug(f"从缓存加载: {filename}")
                return self.loaded_data[cache_key].copy()

            # 加载数据
            self.logger.info(f"加载Shapefile: {file_path}")

            # 尝试不同的编码
            encodings = [encoding, 'utf-8', 'gbk', 'gb2312', 'latin1']
            gdf = None

            for enc in encodings:
                try:
                    gdf = gpd.read_file(file_path, encoding=enc)
                    self.logger.debug(f"成功使用编码 {enc} 加载文件")
                    break
                except (UnicodeDecodeError, UnicodeError):
                    continue
                except Exception as e:
                    self.logger.warning(f"使用编码 {enc} 加载失败: {e}")
                    continue

            if gdf is None:
                self.logger.error(f"无法加载文件: {file_path}")
                return None

            # 确保CRS存在
            if gdf.crs is None:
                self.logger.warning(f"文件 {filename} 没有坐标系信息，假设为WGS84")
                gdf.set_crs('EPSG:4326', inplace=True)

            # 转换为WGS84（如果不是的话）
            if gdf.crs.to_string() != 'EPSG:4326':
                self.logger.debug(f"转换坐标系从 {gdf.crs} 到 EPSG:4326")
                gdf = gdf.to_crs('EPSG:4326')

            # 缓存数据
            self.loaded_data[cache_key] = gdf.copy()

            self.logger.info(f"成功加载 {filename}: {len(gdf)} 个要素")
            return gdf

        except Exception as e:
            self.logger.error(f"加载Shapefile失败 {filename}: {str(e)}")
            return None

    def get_data_info(self, filename: str) -> Optional[Dict[str, Any]]:
        """获取数据文件信息"""
        gdf = self.load_shapefile(filename)
        if gdf is None:
            return None

        # 几何类型统计
        geom_types = gdf.geometry.geom_type.value_counts().to_dict()

        # 属性字段信息
        columns_info = {}
        for col in gdf.columns:
            if col != 'geometry':
                dtype = str(gdf[col].dtype)
                null_count = gdf[col].isnull().sum()
                unique_count = gdf[col].nunique()
                columns_info[col] = {
                    'type': dtype,
                    'null_count': null_count,
                    'unique_count': unique_count
                }

        # 空间范围
        bounds = gdf.total_bounds  # [minx, miny, maxx, maxy]

        return {
            'filename': filename,
            'feature_count': len(gdf),
            'geometry_types': geom_types,
            'columns': columns_info,
            'bounds': bounds.tolist(),
            'crs': str(gdf.crs)
        }

    def create_geojson_from_gdf(self, gdf: gpd.GeoDataFrame) -> Dict[str, Any]:
        """将GeoDataFrame转换为GeoJSON格式"""
        try:
            # 确保几何图形有效
            gdf = gdf[gdf.geometry.is_valid]

            # 转换为GeoJSON
            geojson = gdf.__geo_interface__

            return geojson

        except Exception as e:
            self.logger.error(f"转换GeoJSON失败: {str(e)}")
            return {
                "type": "FeatureCollection",
                "features": []
            }

    def filter_data(
        self,
        gdf: gpd.GeoDataFrame,
        attribute_filter: Optional[Dict[str, Any]] = None,
        spatial_filter: Optional[Tuple[float, float, float, float]] = None
    ) -> gpd.GeoDataFrame:
        """过滤数据

        Args:
            gdf: 输入的GeoDataFrame
            attribute_filter: 属性过滤条件，如 {'column': 'value'}
            spatial_filter: 空间过滤范围 (minx, miny, maxx, maxy)

        Returns:
            过滤后的GeoDataFrame
        """
        filtered_gdf = gdf.copy()

        # 属性过滤
        if attribute_filter:
            for column, value in attribute_filter.items():
                if column in filtered_gdf.columns:
                    if isinstance(value, list):
                        filtered_gdf = filtered_gdf[filtered_gdf[column].isin(value)]
                    else:
                        filtered_gdf = filtered_gdf[filtered_gdf[column] == value]

        # 空间过滤
        if spatial_filter:
            minx, miny, maxx, maxy = spatial_filter
            bbox = Polygon([(minx, miny), (maxx, miny), (maxx, maxy), (minx, maxy)])
            filtered_gdf = filtered_gdf[filtered_gdf.geometry.intersects(bbox)]

        return filtered_gdf

    def get_attribute_values(self, filename: str, column: str) -> List[Any]:
        """获取指定属性列的所有值"""
        gdf = self.load_shapefile(filename)
        if gdf is None or column not in gdf.columns:
            return []

        return gdf[column].dropna().unique().tolist()

    def create_choropleth_data(
        self,
        gdf: gpd.GeoDataFrame,
        value_column: str,
        classification_method: str = 'quantiles',
        n_classes: int = 5
    ) -> gpd.GeoDataFrame:
        """创建分级设色数据

        Args:
            gdf: 输入数据
            value_column: 用于分级的数值列
            classification_method: 分级方法 ('quantiles', 'equal_interval', 'natural_breaks')
            n_classes: 分级数量

        Returns:
            包含分级信息的GeoDataFrame
        """
        if value_column not in gdf.columns:
            self.logger.error(f"列 {value_column} 不存在")
            return gdf

        # 确保是数值类型
        try:
            values = pd.to_numeric(gdf[value_column], errors='coerce')
            values = values.dropna()

            if len(values) == 0:
                self.logger.error(f"列 {value_column} 没有有效的数值")
                return gdf

            # 分级
            if classification_method == 'quantiles':
                bins = pd.qcut(values, q=n_classes, duplicates='drop', retbins=True)[1]
            elif classification_method == 'equal_interval':
                bins = pd.cut(values, bins=n_classes, retbins=True)[1]
            else:  # natural_breaks 或其他
                # 简化的自然断点法
                bins = pd.qcut(values, q=n_classes, duplicates='drop', retbins=True)[1]

            # 分配分级
            gdf_copy = gdf.copy()
            gdf_copy[f'{value_column}_class'] = pd.cut(
                pd.to_numeric(gdf_copy[value_column], errors='coerce'),
                bins=bins,
                include_lowest=True,
                labels=False
            )

            return gdf_copy

        except Exception as e:
            self.logger.error(f"创建分级设色数据失败: {str(e)}")
            return gdf


# 全局数据加载器实例
data_loader = DataLoader()
