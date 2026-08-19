import numpy as np
import pandas as pd
import torch
import torch.nn.functional as F
import os
import json
import pandas as pd
import torch.nn as nn

from torch_geometric.data import Data
from torch_geometric.nn import GCNConv

# 日志前缀
LOG_PREFIX = "GCNN路网选取工具 | "

# 设置随机种子，确保结果可复现
torch.manual_seed(42)
np.random.seed(42)


class GCNN(nn.Module):
    """
    图卷积神经网络模型
    """
    def __init__(self, num_features, hidden_channels, num_classes=2):
        super(GCNN, self).__init__()
        
        # 第一层图卷积: 输入特征 -> hidden_channels
        self.conv1 = GCNConv(num_features, hidden_channels)
        
        # 第二层图卷积: hidden_channels -> hidden_channels
        self.conv2 = GCNConv(hidden_channels, hidden_channels)
        
        # 第三层图卷积: hidden_channels -> num_classes(2)
        self.conv3 = GCNConv(hidden_channels, num_classes)
        
        # Dropout层，防止过拟合
        self.dropout = nn.Dropout(0.3)
        
    def forward(self, x, edge_index):
        # 第一层图卷积 + ReLU
        x = self.conv1(x, edge_index)
        x = F.relu(x)
        x = self.dropout(x)
        
        # 第二层图卷积 + ReLU
        x = self.conv2(x, edge_index)
        x = F.relu(x)
        x = self.dropout(x)
        
        # 最后一层卷积，输出logits，用softmax获得预测概率
        x = self.conv3(x, edge_index)
        
        return x

def load_data(node_attr_path="network_data/node_attributes.xlsx",
              adjacency_path="network_data/adjacency_list.json"):
    """
    加载节点属性和邻接表，构建图数据
    """
    # print(f"{LOG_PREFIX}加载数据: {node_attr_path}, {adjacency_path}")

    # 加载节点属性
    df = pd.read_excel(node_attr_path)

    # 加载邻接表
    with open(adjacency_path, 'r') as f:
        adjacency_list = json.load(f)

    print(f"{LOG_PREFIX}数据加载完成, 节点属性: {df.shape}, 邻接表大小: {len(adjacency_list)}")
    return df, adjacency_list

def preprocess_features(df):
    """
    预处理特征，提取12个特征，并进行标准化
    扩展特征，比如添加度中心性、接近中心性等网络特征
    """
    # print(f"{LOG_PREFIX}步骤2: 预处理特征...")
    
    # 从网络计算额外特征
    node_ids = df['OBJECTID'].tolist()
    
    # 提取原始特征
    features = df[['Shape_Leng', 'Density', 'Connection', 'Grade', 'BuildingNu', 
                   'Centre__Cc', 'Centre__Hc']].values
    
    # 添加归一化的X和Y坐标特征
    x_normalized = (df['X'] - df['X'].min()) / (df['X'].max() - df['X'].min() + 1e-8)
    y_normalized = (df['Y'] - df['Y'].min()) / (df['Y'].max() - df['Y'].min() + 1e-8)
    
    # 计算坐标与原点的距离作为特征
    distance_from_origin = np.sqrt(x_normalized**2 + y_normalized**2)
    
    # 计算位置四分象限特征 (-1,1)共4种组合
    quadrant = np.zeros((len(df), 4))
    for i, (x, y) in enumerate(zip(df['X'], df['Y'])):
        if x >= 0 and y >= 0:  # 第一象限
            quadrant[i, 0] = 1
        elif x < 0 and y >= 0:  # 第二象限
            quadrant[i, 1] = 1
        elif x < 0 and y < 0:   # 第三象限
            quadrant[i, 2] = 1
        else:                   # 第四象限
            quadrant[i, 3] = 1
    
    # 合并所有特征
    expanded_features = np.column_stack((
        features, 
        x_normalized.values.reshape(-1, 1),
        y_normalized.values.reshape(-1, 1),
        distance_from_origin.values.reshape(-1, 1),
        quadrant,
    ))
    
    # 确保有12个特征
    if expanded_features.shape[1] < 12:
        # print(f"{LOG_PREFIX}特征数量不足12个，当前为{expanded_features.shape[1]}个，添加额外特征...")
        # 添加原始特征的一些组合特征，直到达到12个
        extra_features = []
        
        # Shape_Leng * Density
        extra_features.append(features[:, 0] * features[:, 1])
        
        # Connection * BuildingNu
        extra_features.append(features[:, 2] * features[:, 4])
        
        # 添加额外特征直到达到12个
        extra_features_array = np.column_stack(extra_features)
        expanded_features = np.column_stack((expanded_features, extra_features_array))
    
    # 如果特征超过12个，只保留前12个
    if expanded_features.shape[1] > 12:
        # print(f"{LOG_PREFIX}特征数量超过12个，当前为{expanded_features.shape[1]}个，只保留前12个")
        expanded_features = expanded_features[:, :12]

    # 标准化特征
    features_mean = np.mean(expanded_features, axis=0)
    features_std = np.std(expanded_features, axis=0)
    normalized_features = (expanded_features - features_mean) / (features_std + 1e-8)

    # print(f"{LOG_PREFIX}特征预处理完成，最终特征维度: {normalized_features.shape}")
    return normalized_features, df['SorD'].values

def build_graph_data(features, labels, adjacency_list, node_ids):
    """
    构建PyTorch Geometric格式的图数据
    """
    # print(f"{LOG_PREFIX}步骤3: 构建图数据...")
    
    # 创建边索引列表
    edge_index = []
    
    # 创建节点ID到索引的映射
    node_id_to_index = {node_id: i for i, node_id in enumerate(node_ids)}
    
    # 构建边索引
    for source_id, target_ids in adjacency_list.items():
        source_id = int(source_id)  # 确保是整数
        if str(source_id) in adjacency_list and source_id in node_id_to_index:
            source_idx = node_id_to_index[source_id]
            
            for target_id in target_ids:
                target_id = int(target_id)  # 确保是整数
                if target_id in node_id_to_index:
                    target_idx = node_id_to_index[target_id]
                    edge_index.append([source_idx, target_idx])
    
    # 转换为PyTorch张量
    edge_index = torch.tensor(edge_index, dtype=torch.long).t().contiguous()
    x = torch.tensor(features, dtype=torch.float)
    y = torch.tensor(labels, dtype=torch.long)
    
    # 创建图数据对象
    data = Data(x=x, edge_index=edge_index, y=y)

    # print(f"{LOG_PREFIX}图数据构建完成: {len(node_ids)}个节点, {edge_index.size(1)}条边")
    return data





# 设置随机种子，确保结果可复现
torch.manual_seed(42)
np.random.seed(42)

def load_model(model_path="results/gcnn_model.pt", num_features=12, hidden_channels=64):
    """
    加载训练好的模型
    """
    # print(f"{LOG_PREFIX}步骤4: 加载模型: {model_path}")

    # 创建模型实例
    model = GCNN(num_features=num_features, hidden_channels=hidden_channels)

    # 加载模型参数
    model.load_state_dict(torch.load(model_path, weights_only=True))


    # 设置为评估模式
    model.eval()

    # print(f"{LOG_PREFIX}模型加载完成")
    return model



def apply_model(model, data):
    """
    应用模型进行预测
    """
    
    # 使用模型进行预测
    with torch.no_grad():
        out = model(data.x, data.edge_index)
        pred_probs = F.softmax(out, dim=1)
        preds = out.argmax(dim=1)
    
    # 将预测结果转换为numpy数组
    keep_probs = pred_probs[:, 1].cpu().numpy()
    predictions = preds.cpu().numpy()
    
    return predictions, keep_probs


def save_results_to_excel(df, predictions, probs,result_path):
    """
    将选取结果保存到Excel
    """
    output_path=f"{result_path}/road_selection_results.xlsx"
    # print(f"{LOG_PREFIX}步骤6: 保存选取结果到 {output_path}...")

    # 创建结果DataFrame
    results_df = df.copy()

    # 添加预测结果和概率
    results_df['Prediction'] = predictions
    results_df['KeepProbability'] = probs
    results_df['Selection'] = results_df['Prediction'].apply(lambda x: '保留' if x == 1 else '舍弃')

    # 保存到Excel
    results_df.to_excel(output_path, index=False)
    # print(f"{LOG_PREFIX}选取结果已保存到 {output_path}")

    return results_df


def generate_statistics(df, predictions, probs):
    """
    生成选取统计信息
    """
    # print(f"{LOG_PREFIX}生成选取统计信息...")
    
    # 计算选取率
    selection_rate = np.mean(predictions)
    
    # 按等级分组统计
    grade_stats = pd.DataFrame({
        'Grade': df['Grade'],
        'Prediction': predictions,
        'Probability': probs
    }).groupby('Grade').agg({
        'Prediction': ['count', 'mean'],
        'Probability': 'mean'
    })
    
    # 计算总体统计
    total_roads = len(predictions)
    kept_roads = np.sum(predictions)
    
    # 按连通度分析
    conn_stats = pd.DataFrame({
        'Connection': df['Connection'],
        'Prediction': predictions
    }).groupby('Connection').agg({
        'Prediction': ['count', 'mean']
    })
    
    
    # 返回统计信息
    return {
        'total_roads': total_roads,
        'kept_roads': kept_roads,
        'selection_rate': selection_rate,
        'grade_stats': grade_stats,
        'conn_stats': conn_stats
    }

def main(model_path,
         node_attr_path,
         adjacency_path,
         result_path,
         select_count=1.0):
    """
    主函数
    """
    # 不再打印分隔线，使用统一的日志格式
    # print("=" * 50)
    # print("GCNN路网智能选取模型应用")
    # print("=" * 50)

    # 1. 加载数据
    df, adjacency_list = load_data(node_attr_path, adjacency_path)

    # 2. 预处理特征
    features, labels = preprocess_features(df)

    # 3. 构建图数据
    node_ids = df['OBJECTID'].values
    data = build_graph_data(features, labels, adjacency_list, node_ids)

    # 4. 加载模型
    model = load_model(model_path, num_features=features.shape[1])

    # 5. 应用模型进行预测
    predictions, probs = apply_model(model, data)

    order = np.argsort(probs)[::-1]
    top_idx = order[:int(select_count)]
    predictions = np.zeros_like(predictions)
    predictions[top_idx] = 1

    # 7. 保存结果到Excel
    _ = save_results_to_excel(df, predictions, probs, result_path)

    # 9. 生成统计信息
    _ = generate_statistics(df, predictions, probs)

    # print("=" * 50)
    # print("路网选取完成！")
    # print("=" * 50)

if __name__ == "__main__":
    main() 
