import pandas as pd
import numpy as np
import networkx as nx
import json
from tqdm import tqdm
import sys  # 添加这行以支持命令行参数

# 日志前缀
LOG_PREFIX = "GCNN路网选取工具 | "


def load_data(excel_path="data.xlsx"):
    """加载Excel数据"""
    df = pd.read_excel(excel_path)
    
    # 验证必要的列是否存在
    required_columns = ['OBJECTID', 'Shape_Leng', 'Density', 'Connection', 'Grade', 
                        'BuildingNu', 'Centre__Cc', 'Centre__Hc', 'SorD', 
                        'Cor_X', 'Cor_Y', 'from_node', 'to_node']
    
    missing_columns = [col for col in required_columns if col not in df.columns]
    if missing_columns:
        print(f"{LOG_PREFIX}警告: 数据缺少以下列: {missing_columns}")
        return None

    # 重命名坐标列以适应代码
    if 'Cor_X' in df.columns and 'Cor_Y' in df.columns and 'X' not in df.columns and 'Y' not in df.columns:
        df = df.rename(columns={'Cor_X': 'X', 'Cor_Y': 'Y'})
        # print(f"{LOG_PREFIX}已将坐标列 Cor_X 和 Cor_Y 重命名为 X 和 Y")

    # if max_rows is not None and max_rows < len(df):
    #     print(f"{LOG_PREFIX}只使用前 {max_rows} 行数据进行演示")
    #     df = df.head(max_rows)

    print(f"{LOG_PREFIX}数据加载完成，共 {len(df)} 条记录")
    return df

def build_road_network(df):
    """根据已有的from_node和to_node字段构建路网图结构"""
    # print(f"{LOG_PREFIX}步骤1: 构建路网图结构...")
    
    # 创建NetworkX图
    G = nx.Graph()
    
    # 添加节点和节点属性
    # 获取唯一的节点ID列表（from_node和to_node的并集）
    node_ids = set(df['from_node'].unique()).union(set(df['to_node'].unique()))
    
    # 为了为每个节点添加属性，我们需要有一个节点到其属性的映射
    # 使用OBJECTID作为主键，将唯一节点信息提取出来
    node_df = df.drop_duplicates(subset=['OBJECTID'])[['OBJECTID', 'X', 'Y', 'Shape_Leng', 'Density', 
                                                       'Connection', 'Grade', 'BuildingNu', 
                                                       'Centre__Cc', 'Centre__Hc', 'SorD']]
    
    # 创建节点ID到其属性的直接映射
    # 先创建OBJECTID到行的映射
    objectid_to_info = {}
    for _, row in node_df.iterrows():
        object_id = row['OBJECTID']
        objectid_to_info[object_id] = row
    
    # 然后创建一个从from_node/to_node到OBJECTID的映射
    nodeid_to_objectid = {}
    for _, row in df.iterrows():
        from_id = row['from_node']
        to_id = row['to_node']
        object_id = row['OBJECTID']
        
        # 对于每个from_node和to_node，记录它们对应的OBJECTID
        if from_id not in nodeid_to_objectid:
            nodeid_to_objectid[from_id] = object_id
        if to_id not in nodeid_to_objectid:
            nodeid_to_objectid[to_id] = object_id
    
    # 添加节点
    for node_id in node_ids:
        # 查找对应的OBJECTID
        object_id = nodeid_to_objectid.get(node_id)
        
        if object_id is not None and object_id in objectid_to_info:
            row = objectid_to_info[object_id]
            # 添加节点及其属性
            G.add_node(node_id, 
                      x=row['X'],
                      y=row['Y'],
                      shape_leng=row['Shape_Leng'],
                      density=row['Density'],
                      connection=row['Connection'],
                      grade=row['Grade'],
                      building_nu=row['BuildingNu'],
                      centre_cc=row['Centre__Cc'],
                      centre_hc=row['Centre__Hc'],
                      sord=row['SorD'])
        else:
            # 如果找不到该节点的信息，添加一个基本节点
            G.add_node(node_id)
            print(f"{LOG_PREFIX}警告: 节点 {node_id} 缺少属性信息")
    
    # 添加边
    # 使用from_node和to_node字段创建边
    edges_added = set()  # 用于跟踪已添加的边，避免重复
    adjacency_list = {}  # 用于保存邻接表
    
    for _, row in tqdm(df.iterrows(), total=len(df), desc="创建边"):
        from_id = row['from_node']
        to_id = row['to_node']
        
        # 检查是否是有效的边
        if from_id == to_id:
            continue  # 跳过自环
        
        # 创建无向边的规范表示 (小的ID总是在前)
        edge = tuple(sorted([from_id, to_id]))
        
        if edge not in edges_added:
            G.add_edge(from_id, to_id)
            edges_added.add(edge)
            
            # 更新邻接表
            if from_id not in adjacency_list:
                adjacency_list[from_id] = []
            if to_id not in adjacency_list:
                adjacency_list[to_id] = []
            
            adjacency_list[from_id].append(to_id)
            adjacency_list[to_id].append(from_id)  # 因为是无向图

    print(f"{LOG_PREFIX}图构建完成，包含 {G.number_of_nodes()} 个节点和 {G.number_of_edges()} 条边")
    return G, adjacency_list

def save_node_attributes(df, output_path="network_data/node_attributes.xlsx"):
    """保存节点属性表"""
    # print(f"{LOG_PREFIX}保存节点属性表到 {output_path}")
    
    # 提取唯一的节点记录，以防数据集中有重复
    node_attrs = df.drop_duplicates(subset=['OBJECTID'])[
        ['OBJECTID', 'Shape_Leng', 'Density', 'Connection', 'Grade', 
         'BuildingNu', 'Centre__Cc', 'Centre__Hc', 'SorD', 'X', 'Y']
    ]
    
    # 保存到Excel
    node_attrs.to_excel(output_path, index=False)
    print(f"{LOG_PREFIX}邻接表、节点属性表保存完成，包含 {len(node_attrs)} 个节点")

def save_adjacency_list(adjacency_list, output_path="network_data/adjacency_list.json"):
    """保存邻接表"""
    # print(f"{LOG_PREFIX}保存邻接表到 {output_path}")
    
    # 将NumPy类型转换为Python标准类型
    converted_list = {}
    for node, neighbors in adjacency_list.items():
        # 确保节点ID是标准Python类型
        node_key = int(node) if isinstance(node, (np.integer, np.floating)) else node
        # 确保邻居列表中的每个元素都是标准Python类型
        converted_neighbors = [int(n) if isinstance(n, (np.integer, np.floating)) else n for n in neighbors]
        converted_list[node_key] = converted_neighbors
    
    # 保存转换后的邻接表
    with open(output_path, 'w') as f:
        json.dump(converted_list, f, indent=2)




def main(input_excel="data.xlsx", path="network_data"):
    """主函数"""
    # 不再打印分隔线，使用统一的日志格式
    # print("="*50)
    # print("路网图结构构建 (基于已有坐标和连接信息)")
    # print("="*50)
    
    
    # network_data目录下的文件名保持默认（不带后缀）
    node_attrs_path = f"{path}/node_attributes.xlsx"
    adjacency_list_path = f"{path}/adjacency_list.json"

    # 1. 加载数据
    df = load_data(input_excel)
    if df is None:
        print(f"{LOG_PREFIX}错误: 数据加载失败，请确保数据包含所有必要的列")
        return
    
    # 2. 构建路网图 (使用已有的from_node和to_node)
    G, adjacency_list = build_road_network(df)
    
    # 3. 保存节点属性表
    save_node_attributes(df, output_path=node_attrs_path)
    
    # 4. 保存邻接表
    save_adjacency_list(adjacency_list, output_path=adjacency_list_path)
    

    # 7. 输出详细统计信息（简化输出）
    # print("\n" + "="*50)
    # print("数据统计信息")
    # print("="*50)
    
    # 基本统计
    total_rows = len(df)
    unique_from_nodes = df['from_node'].nunique()
    unique_to_nodes = df['to_node'].nunique()
    unique_nodes = len(set(df['from_node']).union(set(df['to_node'])))
    column_count = len(df.columns)
    
    # print(f"总行数: {total_rows}条记录")
    # print(f"唯一from_node数量: {unique_from_nodes}个")
    # print(f"唯一to_node数量: {unique_to_nodes}个")
    # print(f"唯一节点总数: {unique_nodes}个节点")
    # print(f"列数: {column_count}个属性列")
    
    # 连接分布统计
    from_node_counts = df['from_node'].value_counts()
    avg_connections = from_node_counts.mean()
    median_connections = from_node_counts.median()
    q75_connections = from_node_counts.quantile(0.75)
    max_connections = from_node_counts.max()
    min_connections = from_node_counts.min()
    
    # print(f"平均每个from_node有{avg_connections:.1f}个连接")
    # print(f"from_node连接数分布: 中位数为{median_connections:.0f}，75%的节点有{q75_connections:.0f}个或以下连接")
    # print(f"最高连接数为{max_connections:.0f}个连接，最低为{min_connections:.0f}个连接")

    # 节点属性统计
    # print("\n节点属性统计:")
    node_df = df.drop_duplicates(subset=['OBJECTID'])
    # for col in ['Shape_Leng', 'Density', 'Connection', 'Grade', 'BuildingNu', 'Centre__Cc', 'Centre__Hc']:
    #     if col in node_df.columns:
    #         min_val = node_df[col].min()
    #         max_val = node_df[col].max()
    #         print(f"  {col}: 最小值={min_val:.4f}, 最大值={max_val:.4f}")
    
    # 标签分布(SorD)
    # if 'SorD' in node_df.columns:
    #     sord_0_count = (node_df['SorD'] == 0).sum()
    #     sord_1_count = (node_df['SorD'] == 1).sum()
    #     sord_0_pct = sord_0_count / len(node_df) * 100
    #     sord_1_pct = sord_1_count / len(node_df) * 100
    #     print(f"\n标签分布:")
    #     print(f"  舍弃(SorD=0): {sord_0_count}条记录 ({sord_0_pct:.2f}%)")
    #     print(f"  保留(SorD=1): {sord_1_count}条记录 ({sord_1_pct:.2f}%)")
    
    # 空间分布统计（注释掉详细输出）
    # if 'X' in node_df.columns and 'Y' in node_df.columns:
    #     # 获取X和Y的最小值和最大值
    #     x_min = node_df['X'].min()
    #     x_max = node_df['X'].max()
    #     y_min = node_df['Y'].min()
    #     y_max = node_df['Y'].max()
    #
    #     # 定义四个象限的极值点
    #     q1_point = (x_max, y_max)  # 第一象限 (+,+)
    #     q2_point = (x_min, y_max)  # 第二象限 (-,+)
    #     q3_point = (x_min, y_min)  # 第三象限 (-,-)
    #     q4_point = (x_max, y_min)  # 第四象限 (+,-)
    #
    #     print(f"\n空间分布范围(四个象限极值点):")
    #     print(f"  第一象限(+,+): ({q1_point[0]:.2f}, {q1_point[1]:.2f})")
    #     print(f"  第二象限(-,+): ({q2_point[0]:.2f}, {q2_point[1]:.2f})")
    #     print(f"  第三象限(-,-): ({q3_point[0]:.2f}, {q3_point[1]:.2f})")
    #     print(f"  第四象限(+,-): ({q4_point[0]:.2f}, {q4_point[1]:.2f})")

    # print("="*50)
    # print("处理完成！")
    # print("="*50)

if __name__ == "__main__":
    # 从命令行参数获取max_rows
    max_rows = 187685  # 默认值
    
    if len(sys.argv) > 1:
        try:
            max_rows = int(sys.argv[1])
            print(f"使用命令行指定的数据行数: {max_rows}")
        except ValueError:
            print(f"警告: 无效的行数参数 '{sys.argv[1]}'，使用默认值 5000")
    
    main(max_rows=max_rows)
    # 全部数据稍后处理
    # print("开始处理全部数据，这可能需要一些时间...")
    # main() 