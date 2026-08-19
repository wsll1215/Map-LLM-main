"""
Shapefile可视化脚本
用于可视化"综合前"和"综合后"的shapefile文件
"""

import geopandas as gpd
import matplotlib.pyplot as plt
from matplotlib import rcParams

# 设置中文字体支持
rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'Arial Unicode MS']
rcParams['axes.unicode_minus'] = False

def visualize_shapefiles():
    """读取并可视化两个shapefile"""
    
    # 读取shapefile，尝试不同的编码
    print("正在读取shapefile文件...")
    try:
        gdf_before = gpd.read_file("综合前.shp", encoding='gbk')
        gdf_after = gpd.read_file("综合后.shp", encoding='gbk')
    except:
        try:
            gdf_before = gpd.read_file("综合前.shp", encoding='utf-8')
            gdf_after = gpd.read_file("综合后.shp", encoding='utf-8')
        except:
            gdf_before = gpd.read_file("综合前.shp")
            gdf_after = gpd.read_file("综合后.shp")
    
    print(f"综合前: {len(gdf_before)} 个要素")
    print(f"综合后: {len(gdf_after)} 个要素")
    print(f"\n综合前的列: {list(gdf_before.columns)}")
    print(f"综合后的列: {list(gdf_after.columns)}")
    
    # 创建图形
    fig, axes = plt.subplots(1, 2, figsize=(16, 8))
    
    # 绘制综合前
    gdf_before.plot(ax=axes[0], color='blue', edgecolor='black', alpha=0.7, linewidth=0.5)
    axes[0].set_title('综合前', fontsize=16, fontweight='bold', pad=20)
    axes[0].set_xlabel('经度', fontsize=12)
    axes[0].set_ylabel('纬度', fontsize=12)
    axes[0].grid(True, alpha=0.3)
    
    # 绘制综合后
    gdf_after.plot(ax=axes[1], color='red', edgecolor='black', alpha=0.7, linewidth=0.5)
    axes[1].set_title('综合后', fontsize=16, fontweight='bold', pad=20)
    axes[1].set_xlabel('经度', fontsize=12)
    axes[1].set_ylabel('纬度', fontsize=12)
    axes[1].grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig('shapefile_comparison.png', dpi=300, bbox_inches='tight')
    print("\n对比图已保存为: shapefile_comparison.png")
    plt.show()
    
    # 创建叠加图
    fig, ax = plt.subplots(figsize=(10, 10))
    gdf_before.plot(ax=ax, color='blue', edgecolor='darkblue', alpha=0.5, 
                    linewidth=0.8, label='综合前')
    gdf_after.plot(ax=ax, color='red', edgecolor='darkred', alpha=0.5, 
                   linewidth=0.8, label='综合后')
    ax.set_title('综合前后叠加对比', fontsize=16, fontweight='bold', pad=20)
    ax.set_xlabel('经度', fontsize=12)
    ax.set_ylabel('纬度', fontsize=12)
    ax.legend(fontsize=12)
    ax.grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig('shapefile_overlay.png', dpi=300, bbox_inches='tight')
    print("叠加图已保存为: shapefile_overlay.png")
    plt.show()
    
    # 输出统计信息
    print("\n=== 统计信息 ===")
    print(f"综合前几何类型: {gdf_before.geom_type.unique()}")
    print(f"综合后几何类型: {gdf_after.geom_type.unique()}")
    print(f"\n综合前边界: {gdf_before.total_bounds}")
    print(f"综合后边界: {gdf_after.total_bounds}")
    
    # 显示前几行数据
    print("\n=== 综合前数据预览 ===")
    print(gdf_before.head())
    print("\n=== 综合后数据预览 ===")
    print(gdf_after.head())

if __name__ == "__main__":
    try:
        visualize_shapefiles()
    except Exception as e:
        print(f"错误: {e}")
        print("\n请确保已安装必要的库:")
        print("pip install geopandas matplotlib")
