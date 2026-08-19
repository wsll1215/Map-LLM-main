class HyperParameters:
    """Central tunables for GIS + LLM agent behavior."""

    LLM_TEMPERATURE = 0.2  # 主制图 Agent 的模型温度，越低输出越稳定。
    INTENT_LLM_TEMPERATURE = 0.1  # 意图识别模型温度，保持较低以减少分类波动。
    INTENT_REQUEST_TIMEOUT_SECONDS = 30  # 意图识别单次模型请求超时时间。
    MAX_TOOL_ITERATIONS = 10  # 单次任务最多允许 LLM 进行的工具调用轮数。

    AUTO_EXTENT_MARGIN_RATIO = 0.05  # 自动计算地图范围时额外扩展的边距比例。
    MAP_SCALE = 1.0  # 地图初始化时的默认缩放比例。
    MAP_MARGIN_RATIO = 0.0  # 地图初始化时额外应用的边距比例。

    DEFAULT_DPI = 300  # 普通地图配置的默认输出分辨率。
    DEFAULT_FIGSIZE = (12, 8)  # 普通地图默认画布尺寸，单位为英寸。
    INIT_MAP_DPI = 150  # 初始化 Matplotlib 地图画布时使用的分辨率。
    SAVE_DPI = 100  # 保存普通地图图片时的默认分辨率，较低可减少内存压力。
    COMPARISON_DPI = 300  # 动态调整前后对比图的保存分辨率。
    GENERALIZATION_DPI = 600  # 路网综合对比图的默认保存分辨率。
    GENERALIZATION_FIGSIZE = (16, 8)  # 路网综合前后对比图的默认画布尺寸。
    RENDER_HISTORY_KEEP_COUNT = 10  # 清理历史渲染文件时默认保留的最近文件数量。

    SCALEBAR_LENGTH = 100  # 默认比例尺长度。
    SCALEBAR_POSITION = [0.01, 0.01]  # 默认比例尺位置，使用 0-1 相对坐标。
    SCALEBAR_UNITS = "km"  # 默认比例尺单位。
    COMPASS_POSITION = [0.9, 0.9]  # 默认指北针位置，使用 0-1 相对坐标。
    COMPASS_SIZE = 0.05  # 默认指北针尺寸比例。

    QUALITY_SCALEBAR_BOX = (0.24, 0.07)  # 质量检查中估算比例尺占用区域的宽高。
    QUALITY_COMPASS_BOX = (0.10, 0.12)  # 质量检查中估算指北针占用区域的宽高。
    QUALITY_ANNOTATION_BOX = (0.16, 0.05)  # 质量检查中估算单个注记占用区域的宽高。
    QUALITY_LEGEND_BOX_SIZE = (0.28, 0.28)  # 质量检查中估算图例占用区域的宽高。
