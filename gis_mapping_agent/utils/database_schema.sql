-- 地图状态管理数据库表结构
-- SQLite 数据库

-- 会话表
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    session_name TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_accessed TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    current_version INTEGER DEFAULT 1
);

-- 地图状态表（核心表）
CREATE TABLE IF NOT EXISTS map_states (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    
    -- 地图配置（JSON 格式）
    map_id TEXT NOT NULL,
    title TEXT,
    extent TEXT,  -- JSON: [minx, miny, maxx, maxy]
    crs TEXT DEFAULT 'EPSG:4326',
    background_color TEXT DEFAULT 'white',
    figsize TEXT,  -- JSON: [width, height]
    dpi INTEGER DEFAULT 300,
    maintain_data_aspect INTEGER DEFAULT 0,
    fit_figsize_to_extent INTEGER DEFAULT 0,
    auto_legend INTEGER DEFAULT 1,
    auto_scalebar INTEGER DEFAULT 1,
    auto_compass INTEGER DEFAULT 1,
    
    -- 其他配置（JSON 格式）
    scalebar TEXT,  -- JSON
    compass TEXT,   -- JSON
    output_path TEXT,
    
    -- 路网综合相关
    is_generalization_task INTEGER DEFAULT 0,
    generalization_algorithm TEXT,
    generalization_params TEXT,  -- JSON
    generalization_input_path TEXT,
    generalization_output_path TEXT,
    generalization_metrics TEXT,  -- JSON
    generalization_result_meta TEXT,  -- JSON
    generalization_result TEXT,  -- JSON
    
    -- 版本信息
    parent_version INTEGER,
    description TEXT,
    is_current INTEGER DEFAULT 1,
    
    -- 时间戳
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE,
    UNIQUE(session_id, version)
);

-- 图层表
CREATE TABLE IF NOT EXISTS layers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    state_id INTEGER NOT NULL,
    
    -- 图层基本信息
    layer_id TEXT NOT NULL,
    name TEXT NOT NULL,
    data_source TEXT,  -- 文件路径
    geometry_type TEXT,  -- point, line, polygon
    
    -- 样式配置（JSON 格式）
    style TEXT,  -- JSON: {color, linewidth, alpha, ...}
    
    -- 标注配置
    label_column TEXT,
    label_style TEXT,  -- JSON
    
    -- 其他配置
    visible INTEGER DEFAULT 1,
    z_order INTEGER DEFAULT 0,
    
    -- 时间戳
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (state_id) REFERENCES map_states(id) ON DELETE CASCADE
);

-- 图例表
CREATE TABLE IF NOT EXISTS legends (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    state_id INTEGER NOT NULL,
    
    -- 图例配置
    legend_type TEXT,  -- manual, auto
    position TEXT,  -- JSON: [x, y]
    items TEXT,  -- JSON: [{label, color, marker}, ...]
    
    -- 时间戳
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (state_id) REFERENCES map_states(id) ON DELETE CASCADE
);

-- 注记表
CREATE TABLE IF NOT EXISTS annotations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    state_id INTEGER NOT NULL,
    
    -- 注记内容
    text TEXT NOT NULL,
    position TEXT,  -- JSON: [x, y]
    
    -- 样式配置（JSON 格式）
    style TEXT,  -- JSON: {fontsize, color, ...}
    
    -- 时间戳
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (state_id) REFERENCES map_states(id) ON DELETE CASCADE
);

-- 修改记录表
CREATE TABLE IF NOT EXISTS modification_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    state_id INTEGER NOT NULL,
    
    -- 修改信息
    operation_type TEXT,  -- add_layer, modify_style, etc.
    target_element TEXT,
    changes TEXT,  -- JSON: {before, after}
    user_request TEXT,
    
    -- 时间戳
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (state_id) REFERENCES map_states(id) ON DELETE CASCADE
);

-- 索引优化
CREATE INDEX IF NOT EXISTS idx_sessions_last_accessed ON sessions(last_accessed DESC);
CREATE INDEX IF NOT EXISTS idx_map_states_session_version ON map_states(session_id, version);
CREATE INDEX IF NOT EXISTS idx_map_states_current ON map_states(session_id, is_current);
CREATE INDEX IF NOT EXISTS idx_layers_state_id ON layers(state_id);
CREATE INDEX IF NOT EXISTS idx_layers_z_order ON layers(state_id, z_order);
CREATE INDEX IF NOT EXISTS idx_legends_state_id ON legends(state_id);
CREATE INDEX IF NOT EXISTS idx_annotations_state_id ON annotations(state_id);
CREATE INDEX IF NOT EXISTS idx_modification_records_state_id ON modification_records(state_id);
