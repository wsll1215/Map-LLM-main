"""辅助函数模块"""

import uuid
from typing import Any, Dict, List, Optional, Union


def generate_unique_id() -> str:
    """生成唯一ID"""
    return str(uuid.uuid4())


def safe_filename(filename: str) -> str:
    """生成安全的文件名"""
    # 移除或替换不安全的字符
    unsafe_chars = '<>:"/\\|?*'
    for char in unsafe_chars:
        filename = filename.replace(char, '_')
    return filename



def parse_color(color: Union[str, List[float], tuple]) -> str:
    """解析颜色值为标准格式，支持中文颜色名称"""
    # 中文颜色名称映射
    chinese_color_map = {
        # 基础颜色
        "红色": "red",
        "绿色": "green",
        "蓝色": "blue",
        "黄色": "yellow",
        "黑色": "black",
        "白色": "white",
        "灰色": "gray",
        "橙色": "orange",
        "紫色": "purple",
        "粉色": "pink",
        "棕色": "brown",
        "青色": "cyan",

        # 深色系
        "深蓝色": "darkblue",
        "深绿色": "darkgreen",
        "深红色": "darkred",
        "深灰色": "darkgray",
        "深紫色": "darkviolet",
        "深橙色": "darkorange",

        # 浅色系（浅/淡通用）
        "浅蓝色": "lightblue",
        "淡蓝色": "lightblue",  # 添加"淡蓝色"映射
        "浅绿色": "lightgreen",
        "淡绿色": "lightgreen",
        "浅黄色": "lightyellow",
        "淡黄色": "lightyellow",
        "浅灰色": "lightgray",
        "淡灰色": "lightgray",
        "浅红色": "lightcoral",
        "淡红色": "lightcoral",
        "浅粉色": "lightpink",
        "淡粉色": "lightpink",

        # 特殊颜色
        "金色": "gold",
        "银色": "silver",
        "天蓝色": "skyblue",
        "海蓝色": "steelblue",
        "米色": "beige",
        "象牙色": "ivory",
        "珊瑚色": "coral",
        "橄榄色": "olive",
        "卡其色": "khaki",
        "薰衣草色": "lavender",
        "薄荷色": "mintcream",
        "桃色": "peachpuff",
        "玫瑰色": "rosybrown",
        "鲑鱼色": "salmon",
        "海绿色": "seagreen",
        "褐色": "sienna",
        "棕褐色": "tan",
        "青绿色": "teal",
        "番茄色": "tomato",
        "绿松石色": "turquoise",
        "紫罗兰色": "violet",
        "小麦色": "wheat"
    }

    if isinstance(color, str):
        # 如果是中文颜色名称，转换为英文
        return chinese_color_map.get(color, color)
    elif isinstance(color, (list, tuple)) and len(color) >= 3:
        # RGB或RGBA值
        if all(0 <= c <= 1 for c in color[:3]):
            # 0-1范围，转换为0-255
            rgb = [int(c * 255) for c in color[:3]]
        else:
            # 假设是0-255范围
            rgb = [int(c) for c in color[:3]]

        if len(color) >= 4:
            # RGBA
            alpha = color[3] if color[3] <= 1 else color[3] / 255
            return f"rgba({rgb[0]}, {rgb[1]}, {rgb[2]}, {alpha})"
        else:
            # RGB
            return f"rgb({rgb[0]}, {rgb[1]}, {rgb[2]})"

    return "black"  # 默认颜色





import numpy as np

def haversine(lon1, lat1, lon2, lat2):
    """
    Calculate the great circle distance in kilometers between two points
    on the earth (specified in decimal degrees)
    """
    # convert decimal degrees to radians
    lon1, lat1, lon2, lat2 = map(np.radians, [lon1, lat1, lon2, lat2])

    # haversine formula
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = np.sin(dlat/2)**2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon/2)**2
    c = 2 * np.arcsin(np.sqrt(a))
    r = 6371 # Radius of earth in kilometers. Use 3956 for miles. Determines return value units.
    return c * r