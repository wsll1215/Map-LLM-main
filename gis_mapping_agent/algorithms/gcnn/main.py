"""GCNN路网选取主程序

整合build_road_network和apply_gcnn_model两个模块
"""

import build_road_network
import apply_gcnn_model
from pathlib import Path


def main(path="network_data"):
    """GCNN路网选取主函数

    Args:
        path: 数据目录路径，可以是相对路径或绝对路径
              如果是相对路径，会相对于项目根目录解析
    """
    # 确保path是Path对象
    data_path = Path(path)

    # 如果不是绝对路径，相对于项目根目录
    if not data_path.is_absolute():
        # 获取项目根目录（Map-LLM目录）
        current_file = Path(__file__)  # gcnn/main.py
        algorithms_dir = current_file.parent.parent  # algorithms目录
        gis_agent_dir = algorithms_dir.parent  # gis_mapping_agent目录
        project_root = gis_agent_dir.parent  # Map-LLM目录
        data_path = project_root / path

    # 转换为字符串路径
    path_str = str(data_path)

    # 数据文件路径
    excel_path = f'{path_str}/data.xlsx'

    # 模型文件路径（相对于algorithms目录）
    model_path = str(algorithms_dir / "model" / "gcnn_model.pt")

    # 1. 构建路网图结构
    build_road_network.main(input_excel=excel_path, path=path_str)

    # 2. 应用GCNN模型进行选取
    apply_gcnn_model.main(
        model_path=model_path,
        node_attr_path=f"{path_str}/node_attributes.xlsx",
        adjacency_path=f"{path_str}/adjacency_list.json",
        result_path=path_str
    )


if __name__ == "__main__":
    main(path="network_data")
