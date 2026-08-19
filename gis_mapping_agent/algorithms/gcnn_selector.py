"""GCNN路网选择器

使用图卷积神经网络(GCNN)进行路网选取。
"""

import geopandas as gpd
import pandas as pd
from pathlib import Path
from typing import Optional

# 导入gcnn模块
try:
    from .gcnn import build_road_network
    from .gcnn import apply_gcnn_model
except ImportError as e:
    print(f"警告: 无法导入GCNN模块: {e}")
    build_road_network = None
    apply_gcnn_model = None

from ..utils.logger import get_logger


class GCNNSelector:
    """GCNN路网选择器

    使用图卷积神经网络进行智能路网选取。

    与传统方法不同，GCNN算法不需要比例尺参数（如1:500 → 1:2000），
    而是通过深度学习模型自动判断每条路段的重要性。
    """
    
    def __init__(self, verbose: bool = True):
        """初始化GCNN选择器

        Args:
            verbose: 是否输出详细信息
        """
        self.verbose = verbose
        self.logger = get_logger("GCNNSelector")

        # 检查GCNN模块是否可用
        self.gcnn_available = (build_road_network is not None and apply_gcnn_model is not None)

        if not self.gcnn_available:
            self.logger.warning("GCNN模块未正确导入（可能缺少PyTorch依赖），GCNN功能将不可用")
    
    def select_by_gcnn(
        self,
        gdf: gpd.GeoDataFrame,
        data_dir: str,
        keep_ratio: Optional[float] = 1.0
    ) -> gpd.GeoDataFrame:
        """使用GCNN算法选取路网

        注意：GCNN算法基于深度学习自动选取路网，不需要比例尺参数（如1:500 → 1:2000）。
        算法会根据训练好的模型自动判断每条路段是否保留。

        Args:
            gdf: 输入的路网GeoDataFrame
            data_dir: 数据目录路径（如data6），需包含data.xlsx文件
            keep_ratio: 保留比例
        Returns:
            选取后的GeoDataFrame
        """
        # 检查GCNN模块是否可用
        if not self.gcnn_available:
            raise ImportError(
                "GCNN模块不可用。请确保已安装PyTorch及相关依赖。\n"
                "安装命令: pip install torch torchvision"
            )

        if self.verbose:
            self.logger.info(f"开始使用GCNN算法进行路网选取")
            # self.logger.info(f"数据目录: {data_dir}")

        try:
            # 1. 确保data_dir是绝对路径
            data_path = Path(data_dir)
            if not data_path.is_absolute():
                # 相对于项目根目录
                project_root = Path(__file__).parent.parent.parent
                data_path = project_root / data_dir
            
            if not data_path.exists():
                raise FileNotFoundError(f"数据目录不存在: {data_path}")
            
            # 2. 检查data.xlsx是否存在
            excel_path = data_path / "data.xlsx"
            if not excel_path.exists():
                raise FileNotFoundError(f"数据文件不存在: {excel_path}")
            
            # if self.verbose:
                # self.logger.info(f"找到数据文件: {excel_path}")
            
            # 3. 调用GCNN的build_road_network构建图结构
            if self.verbose:
                self.logger.info("步骤1: 构建路网图结构...")
            
            build_road_network.main(
                input_excel=str(excel_path),
                path=str(data_path)
            )
            
            # 4. 调用GCNN模型进行预测
            if self.verbose:
                self.logger.info("步骤2: 应用GCNN模型进行路网选取...")

            # 模型路径
            model_path = Path(__file__).parent / "model" / "gcnn_model.pt"
            if not model_path.exists():
                raise FileNotFoundError(f"GCNN模型文件不存在: {model_path}")

            # 读取节点属性以计算总数
            node_attr_df = pd.read_excel(str(data_path / "node_attributes.xlsx"))
            total_count = len(node_attr_df)
            select_count = int(total_count * keep_ratio)

            apply_gcnn_model.main(
                model_path=str(model_path),
                node_attr_path=str(data_path / "node_attributes.xlsx"),
                adjacency_path=str(data_path / "adjacency_list.json"),
                result_path=str(data_path),
                select_count=select_count
            )
            
            # 5. 读取选取结果
            result_file = data_path / "road_selection_results.xlsx"
            if not result_file.exists():
                raise FileNotFoundError(f"GCNN结果文件不存在: {result_file}")
            
            if self.verbose:
                self.logger.info("步骤3: 读取选取结果并筛选数据...")
            
            # 读取选取结果
            selection_df = pd.read_excel(result_file)
            
            # 6. 根据Selection字段筛选保留的路段
            # Selection字段值为"保留"或"舍弃"
            kept_objectids = selection_df[selection_df['Selection'] == '保留']['OBJECTID'].tolist()
            
            if self.verbose:
                self.logger.info(f"GCNN选取结果: 保留 {len(kept_objectids)}/{len(selection_df)} 条路段")
            
            # 7. 从原始GeoDataFrame中筛选
            # 假设原始GDF中有OBJECTID_1字段与data.xlsx中的OBJECTID对应
            # if 'OBJECTID_1' in gdf.columns:
            #     result_gdf = gdf[gdf['OBJECTID_1'].isin(kept_objectids)].copy()
            if 'OBJECTID' in gdf.columns:
                result_gdf = gdf[gdf['OBJECTID'].isin(kept_objectids)].copy()
            else:
                # 如果没有OBJECTID字段，尝试使用索引
                self.logger.warning("GeoDataFrame中未找到OBJECTID或OBJECTID字段，使用索引匹配")
                # 假设GDF的索引与OBJECTID对应
                result_gdf = gdf.iloc[kept_objectids].copy()
            
            if self.verbose:
                self.logger.info(f"筛选完成: {len(result_gdf)} 条路段")
            
            return result_gdf
            
        except Exception as e:
            self.logger.error(f"GCNN路网选取失败: {str(e)}")
            import traceback
            traceback.print_exc()
            raise
    
    def select_by_gcnn_with_shp(
        self,
        shp_path: str,
        data_dir: str,
        keep_ratio: Optional[float] = None
    ) -> gpd.GeoDataFrame:
        """使用GCNN算法选取路网（从shapefile读取）
        
        Args:
            shp_path: shapefile路径
            data_dir: 数据目录路径
            keep_ratio: 保留比例（参考值）
            
        Returns:
            选取后的GeoDataFrame
        """
        # 读取shapefile
        gdf = gpd.read_file(shp_path)
        
        # 调用主选取方法
        return self.select_by_gcnn(gdf, data_dir, keep_ratio)

