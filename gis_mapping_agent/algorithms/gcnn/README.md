# GCNN路网选取算法

## 简介

GCNN (Graph Convolutional Neural Network) 是一种基于图卷积神经网络的智能路网选取算法。该算法通过学习路网的拓扑结构和属性特征，自动识别重要的道路段，实现从大比例尺到小比例尺的路网综合。

## 算法特点

- **智能学习**: 基于深度学习，自动学习路网重要性特征
- **拓扑感知**: 考虑路网的图结构和连接关系
- **多特征融合**: 综合考虑道路长度、密度、连接度、等级等多种属性
- **端到端**: 从原始数据到选取结果的自动化处理
- **无需尺度参数**: 与传统算法不同，GCNN算法不需要指定源尺度和目标尺度，模型会自动学习选取规则

## 依赖安装

GCNN算法需要以下依赖包：

```bash
# 安装PyTorch (根据系统选择合适的版本)
pip install torch torchvision

# 安装PyTorch Geometric
pip install torch-geometric

# 或者使用requirements文件一次性安装
pip install -r requirements.txt
```

**注意**: PyTorch的安装可能需要根据您的系统（CPU/GPU）选择合适的版本。详见 [PyTorch官网](https://pytorch.org/)。

## 数据要求

GCNN算法需要以下数据文件：

1. **data.xlsx**: 包含路网节点和边的属性信息
   - 必需字段：
     - `OBJECTID`: 道路段唯一标识
     - `Shape_Leng`: 道路长度
     - `Density`: 网眼密度
     - `Connection`: 连接度
     - `Grade`: 道路等级
     - `from_node`, `to_node`: 起止节点ID
   - 可选字段：
     - `BuildingNu`: 建筑物数量
     - `Centre__Cc`, `Centre__Hc`: 中心性指标
     - `SorD`: 源或目标标识
     - `Cor_X`, `Cor_Y`: 坐标

2. **综合前.shp**: 原始路网Shapefile
   - 必需字段：
     - `OBJECTID_1` 或 `OBJECTID`: 与data.xlsx中的OBJECTID对应

## 使用方法

### 1. 通过系统API调用

```python
from gis_mapping_agent.generalization import RoadNetworkGeneralizationEngine
import geopandas as gpd

# 读取数据
gdf = gpd.read_file("data/data6/综合前.shp")

# 创建综合引擎
engine = RoadNetworkGeneralizationEngine(verbose=True)

# 执行GCNN综合
result = engine.generalize(
    input_gdf=gdf,
    source_scale=500,
    target_scale=20000,
    algorithm='gcnn',
    data_dir='data/data6'  # 包含data.xlsx的目录
)

# 可视化结果
vis_result = engine.visualize_comparison(
    generalization_result=result,
    figsize=(16, 8),
    dpi=300
)
```

### 2. 通过LangChain工具调用

```python
from gis_mapping_agent.tools.generalization_tools import GeneralizeRoadNetworkTool

tool = GeneralizeRoadNetworkTool()
result = tool._run(
    data_file="综合前.shp",
    data_directory="data6",
    source_scale=500,
    target_scale=20000,
    algorithm="gcnn"
)
```

### 3. 直接调用GCNN模块

```python
from gis_mapping_agent.algorithms.gcnn import main

# 执行GCNN选取
main.main(path="data/data6")

# 结果保存在 data/data6/road_selection_results.xlsx
```

## 输出结果

GCNN算法会生成以下文件：

1. **node_attributes.xlsx**: 节点属性文件
2. **adjacency_list.json**: 邻接表（图结构）
3. **road_selection_results.xlsx**: 选取结果
   - `OBJECTID`: 道路段ID
   - `Prediction`: 预测类别（0或1）
   - `KeepProbability`: 保留概率
   - `Selection`: 选取结果（"保留"或"舍弃"）

## 算法流程

1. **构建路网图**: 从data.xlsx读取数据，构建图结构
2. **特征提取**: 提取节点和边的特征向量
3. **模型预测**: 使用训练好的GCNN模型进行预测
4. **结果筛选**: 根据预测结果筛选保留的道路段
5. **数据输出**: 生成选取结果文件

## 模型文件

预训练的GCNN模型文件位于：
```
Map-LLM/gis_mapping_agent/algorithms/model/gcnn_model.pt
```

## 注意事项

1. **数据一致性**: 确保data.xlsx中的OBJECTID与shapefile中的OBJECTID_1字段一致
2. **字段完整性**: data.xlsx必须包含所有必需字段
3. **路径处理**: 数据目录可以是相对路径（相对于项目根目录）或绝对路径
4. **依赖检查**: 如果未安装PyTorch，系统会给出友好的错误提示

## 故障排除

### 问题1: ModuleNotFoundError: No module named 'torch'

**解决方案**: 安装PyTorch
```bash
pip install torch torchvision torch-geometric
```

### 问题2: 找不到data.xlsx文件

**解决方案**: 确保数据目录下有data.xlsx文件，且路径正确

### 问题3: OBJECTID字段不匹配

**解决方案**: 检查shapefile中是否有OBJECTID_1或OBJECTID字段，确保与data.xlsx中的OBJECTID对应

## 参考文献

- Kipf, T. N., & Welling, M. (2016). Semi-supervised classification with graph convolutional networks.
- 相关路网综合研究论文

## 联系方式

如有问题，请联系开发团队。
