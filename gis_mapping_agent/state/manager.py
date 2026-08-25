"""地图状态管理器 - 负责状态的保存、加载和版本管理（SQLite 数据库版本）"""

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime

from ..models.schemas import MapState, SessionInfo, MapVersion, ModificationRecord
from ..utils.config import Config
from ..utils.logger import get_logger
from ..utils.singleton import singleton


class MapStateManager:
    """地图状态管理器（SQLite 数据库版本）

    负责地图状态的持久化存储、版本管理和会话管理
    使用 SQLite 数据库替代 JSON 文件存储
    """

    def __init__(self, db_path: Optional[str] = None):
        """初始化状态管理器

        Args:
            db_path: 数据库文件路径，默认使用 outputs/states/map_states.db
        """
        self.logger = get_logger("MapStateManager")

        # 设置数据库路径
        if db_path is None:
            db_dir = Config.OUTPUT_DIR / "states"
            db_dir.mkdir(parents=True, exist_ok=True)
            db_path = db_dir / "map_states.db"
        else:
            db_path = Path(db_path)
            db_path.parent.mkdir(parents=True, exist_ok=True)

        self.db_path = str(db_path)

        # 初始化数据库
        self._init_database()

        # self.logger.info(f"状态管理器初始化完成")

    def _init_database(self):
        """初始化数据库表结构"""
        schema_file = Path(__file__).parent / "database_schema.sql"

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            # 读取并执行 SQL schema
            if schema_file.exists():
                with open(schema_file, 'r', encoding='utf-8') as f:
                    schema_sql = f.read()
                cursor.executescript(schema_sql)
            else:
                # 如果 schema 文件不存在，使用内联 SQL
                self._create_tables_inline(cursor)

            self._migrate_database(cursor)

            conn.commit()
            self.logger.info("数据库表结构初始化完成")

        except Exception as e:
            self.logger.error(f"初始化数据库失败: {e}")
            conn.rollback()
            raise
        finally:
            conn.close()

    def _migrate_database(self, cursor):
        """Keep old SQLite files compatible with newer MapState fields."""
        cursor.execute("PRAGMA table_info(map_states)")
        existing_map_state_columns = {row[1] for row in cursor.fetchall()}
        map_state_columns = {
            "output_path": "TEXT",
            "generalization_algorithm": "TEXT",
            "generalization_params": "TEXT",
            "generalization_input_path": "TEXT",
            "generalization_output_path": "TEXT",
            "generalization_metrics": "TEXT",
            "generalization_result_meta": "TEXT",
            "schema_version": "INTEGER DEFAULT 1",
            "spec_json": "TEXT",
            "spec_hash": "TEXT",
            "source_fingerprints": "TEXT",
            "latest_event_seq": "INTEGER DEFAULT 0",
        }
        for column, column_type in map_state_columns.items():
            if column not in existing_map_state_columns:
                cursor.execute(f"ALTER TABLE map_states ADD COLUMN {column} {column_type}")

        cursor.execute("PRAGMA table_info(layers)")
        existing_layer_columns = {row[1] for row in cursor.fetchall()}
        layer_columns = {
            "data_hash": "TEXT",
            "feature_count": "INTEGER DEFAULT 0",
            "extent": "TEXT",
            "render_mode": "TEXT DEFAULT 'geojson'",
            "data_url": "TEXT",
        }
        for column, column_type in layer_columns.items():
            if column not in existing_layer_columns:
                cursor.execute(f"ALTER TABLE layers ADD COLUMN {column} {column_type}")

    def _create_tables_inline(self, cursor):
        """内联创建数据库表（备用方案）"""
        # 会话表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                session_name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_accessed TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                current_version INTEGER DEFAULT 1
            )
        """)

        # 地图状态表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS map_states (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                map_id TEXT NOT NULL,
                title TEXT,
                extent TEXT,
                crs TEXT DEFAULT 'EPSG:4326',
                background_color TEXT DEFAULT 'white',
                figsize TEXT,
                dpi INTEGER DEFAULT 300,
                maintain_data_aspect INTEGER DEFAULT 0,
                fit_figsize_to_extent INTEGER DEFAULT 0,
                auto_legend INTEGER DEFAULT 1,
                auto_scalebar INTEGER DEFAULT 1,
                auto_compass INTEGER DEFAULT 1,
                scalebar TEXT,
                compass TEXT,
                schema_version INTEGER DEFAULT 1,
                spec_json TEXT,
                spec_hash TEXT,
                source_fingerprints TEXT,
                latest_event_seq INTEGER DEFAULT 0,
                output_path TEXT,
                is_generalization_task INTEGER DEFAULT 0,
                generalization_algorithm TEXT,
                generalization_params TEXT,
                generalization_input_path TEXT,
                generalization_output_path TEXT,
                generalization_metrics TEXT,
                generalization_result_meta TEXT,
                generalization_result TEXT,
                parent_version INTEGER,
                description TEXT,
                is_current INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE,
                UNIQUE(session_id, version)
            )
        """)

        # 图层表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS layers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                state_id INTEGER NOT NULL,
                layer_id TEXT NOT NULL,
                name TEXT NOT NULL,
                data_source TEXT,
                geometry_type TEXT,
                style TEXT,
                label_column TEXT,
                label_style TEXT,
                visible INTEGER DEFAULT 1,
                z_order INTEGER DEFAULT 0,
                data_hash TEXT,
                feature_count INTEGER DEFAULT 0,
                extent TEXT,
                render_mode TEXT DEFAULT 'geojson',
                data_url TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (state_id) REFERENCES map_states(id) ON DELETE CASCADE
            )
        """)

        # 注记表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS annotations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                state_id INTEGER NOT NULL,
                text TEXT NOT NULL,
                position TEXT,
                style TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (state_id) REFERENCES map_states(id) ON DELETE CASCADE
            )
        """)

        # 创建索引
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_map_states_session_version ON map_states(session_id, version)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_layers_state_id ON layers(state_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_annotations_state_id ON annotations(state_id)")
    
    def save_state(self, map_state: MapState) -> bool:
        """保存地图状态到数据库

        Args:
            map_state: 要保存的地图状态

        Returns:
            bool: 保存是否成功
        """
        conn = None
        try:
            session_id = map_state.get_session_id()
            version = map_state.get_current_version()

            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # 1. 确保会话存在
            self._ensure_session_exists(cursor, map_state.session_info)

            # 2. 将旧版本标记为非当前版本
            cursor.execute("""
                UPDATE map_states
                SET is_current = 0
                WHERE session_id = ? AND is_current = 1
            """, (session_id,))
            cursor.execute("""
                DELETE FROM map_states
                WHERE session_id = ? AND version = ?
            """, (session_id, version))

            # 3. 插入地图状态
            state_id = self._insert_map_state(cursor, map_state)

            # 4. 插入图层
            self._insert_layers(cursor, state_id, map_state.layers)

            # 5. 插入注记
            self._insert_annotations(cursor, state_id, map_state.annotations)

            # 6. 更新会话的当前版本和最后访问时间
            cursor.execute("""
                UPDATE sessions
                SET current_version = ?, last_accessed = CURRENT_TIMESTAMP
                WHERE session_id = ?
            """, (version, session_id))

            conn.commit()
            self.logger.info(f"状态保存成功")
            return True

        except Exception as e:
            if conn:
                conn.rollback()
            self.logger.error(f"状态保存失败: {e}")
            import traceback
            traceback.print_exc()
            return False
        finally:
            if conn:
                conn.close()

    def _ensure_session_exists(self, cursor, session_info: SessionInfo):
        """确保会话记录存在"""
        cursor.execute("""
            INSERT OR IGNORE INTO sessions (session_id, session_name, created_at)
            VALUES (?, ?, ?)
        """, (
            session_info.session_id,
            session_info.session_name,
            session_info.created_at.isoformat() if session_info.created_at else datetime.now().isoformat()
        ))

    def _insert_map_state(self, cursor, map_state: MapState) -> int:
        """插入地图状态记录，返回 state_id"""
        config = map_state.config
        version_info = map_state.version_info

        # 处理路网综合结果
        generalization_result_json = None
        if map_state.is_generalization_task and map_state.generalization_result:
            # 移除 GeoDataFrame
            result_copy = map_state.generalization_result.copy()
            if 'input_gdf' in result_copy:
                result_copy['input_gdf'] = None
            if 'output_gdf' in result_copy:
                result_copy['output_gdf'] = None
            generalization_result_json = json.dumps(result_copy, default=str)

        algorithm = map_state.generalization_algorithm
        if not algorithm and map_state.generalization_params:
            algorithm = map_state.generalization_params.get("algorithm")

        cursor.execute("""
            INSERT INTO map_states (
                session_id, version, map_id, title, extent, crs,
                background_color, figsize, dpi, maintain_data_aspect,
                fit_figsize_to_extent, auto_legend, auto_scalebar, auto_compass,
                scalebar, compass, schema_version, spec_json, spec_hash,
                source_fingerprints, latest_event_seq, output_path, is_generalization_task,
                generalization_algorithm, generalization_params,
                generalization_input_path, generalization_output_path,
                generalization_metrics, generalization_result_meta, generalization_result,
                parent_version, description, is_current, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            map_state.get_session_id(),
            map_state.get_current_version(),
            config.map_id,
            config.title,
            json.dumps(config.extent),
            config.crs.value if hasattr(config.crs, 'value') else str(config.crs),
            config.background_color,
            json.dumps(config.figsize),
            config.dpi,
            1 if config.maintain_data_aspect else 0,
            1 if config.fit_figsize_to_extent else 0,
            1 if config.auto_legend else 0,
            1 if config.auto_scalebar else 0,
            1 if config.auto_compass else 0,
            json.dumps(map_state.scalebar) if map_state.scalebar else None,
            json.dumps(map_state.compass) if map_state.compass else None,
            map_state.schema_version,
            json.dumps(map_state.spec_json, ensure_ascii=False) if map_state.spec_json else None,
            map_state.spec_hash,
            json.dumps(map_state.source_fingerprints, ensure_ascii=False),
            map_state.latest_event_seq,
            map_state.output_path,
            1 if map_state.is_generalization_task else 0,
            algorithm,
            json.dumps(map_state.generalization_params, ensure_ascii=False, default=str) if map_state.generalization_params else None,
            map_state.generalization_input_path,
            map_state.generalization_output_path,
            json.dumps(map_state.generalization_metrics, ensure_ascii=False, default=str) if map_state.generalization_metrics else None,
            json.dumps(map_state.generalization_result_meta, ensure_ascii=False, default=str) if map_state.generalization_result_meta else None,
            generalization_result_json,
            version_info.parent_version if version_info else None,
            version_info.description if version_info else "",
            1,  # is_current
            map_state.created_at or datetime.now().isoformat(),
            map_state.updated_at or datetime.now().isoformat()
        ))

        return cursor.lastrowid

    def _row_get(self, row, key: str, default: Any = None) -> Any:
        try:
            return row[key]
        except (KeyError, IndexError):
            return default

    def _insert_layers(self, cursor, state_id: int, layers: List):
        """插入图层记录"""
        for i, layer in enumerate(layers):
            # 序列化样式
            style_json = json.dumps({
                'color': layer.style.color if layer.style else None,
                'linewidth': layer.style.linewidth if layer.style else None,
                'alpha': layer.style.alpha if layer.style else None,
                'marker': layer.style.marker if layer.style else None,
                'size': layer.style.size if layer.style else None,
                'linestyle': layer.style.linestyle if layer.style else None,
                'edgecolor': layer.style.edgecolor if layer.style else None,
                'facecolor': layer.style.facecolor if layer.style else None,
                'hatch': layer.style.hatch if layer.style else None,
                'attribute_column': layer.style.attribute_column if layer.style else None,
                'label_column': layer.style.label_column if layer.style else None,
            }) if layer.style else None

            # label_column 直接从 layer 获取（不是从 label_style）
            label_column = layer.style.label_column if layer.style else None

            # 处理数据源路径：将绝对路径转换为相对路径
            data_source = layer.data_source
            if data_source:
                from pathlib import Path
                data_source_path = Path(data_source)

                # 如果是绝对路径，转换为相对于 PROJECT_ROOT 的路径
                if data_source_path.is_absolute():
                    try:
                        # 尝试相对于 PROJECT_ROOT
                        rel_path = data_source_path.relative_to(Config.PROJECT_ROOT)
                        data_source = str(rel_path).replace('\\', '/')
                    except ValueError:
                        # 如果不在 PROJECT_ROOT 下，保持原样
                        pass

            cursor.execute("""
                INSERT INTO layers (
                    state_id, layer_id, name, data_source, geometry_type,
                    style, label_column, label_style, visible, z_order,
                    data_hash, feature_count, extent, render_mode, data_url
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                state_id,
                layer.layer_id,
                layer.name,
                data_source,
                layer.geometry_type.value if hasattr(layer.geometry_type, 'value') else str(layer.geometry_type),
                style_json,
                label_column,
                None,  # label_style 暂时为 None
                1 if layer.visible else 0,
                i,  # z_order
                layer.data_hash,
                layer.feature_count,
                json.dumps(layer.extent) if layer.extent else None,
                layer.render_mode,
                layer.data_url,
            ))

    def _insert_annotations(self, cursor, state_id: int, annotations: List):
        """插入注记记录"""
        for annotation in annotations:
            style_json = json.dumps({
                'font_size': annotation.font_size,
                'font_family': annotation.font_family,
                'color': annotation.color,
                'background_color': annotation.background_color,
                'rotation': annotation.rotation,
                'alignment': annotation.alignment,
            }) if annotation else None

            cursor.execute("""
                INSERT INTO annotations (
                    state_id, text, position, style
                ) VALUES (?, ?, ?, ?)
            """, (
                state_id,
                annotation.text,
                json.dumps(annotation.position) if annotation.position else None,
                style_json
            ))
    
    def load_state(self, session_id: str, version: Optional[int] = None) -> Optional[MapState]:
        """从数据库加载地图状态

        Args:
            session_id: 会话ID
            version: 版本号，如果为None则加载最新版本

        Returns:
            MapState: 加载的地图状态，失败时返回None
        """
        conn = None
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row  # 使用字典式访问
            cursor = conn.cursor()

            # 如果没有指定版本，加载当前版本
            if version is None:
                cursor.execute("""
                    SELECT current_version FROM sessions WHERE session_id = ?
                """, (session_id,))
                row = cursor.fetchone()
                if row:
                    version = row['current_version']
                else:
                    # self.logger.warning(f"会话不存在: {session_id}")
                    return None

            # 加载地图状态
            cursor.execute("""
                SELECT * FROM map_states
                WHERE session_id = ? AND version = ?
            """, (session_id, version))

            state_row = cursor.fetchone()
            if not state_row:
                self.logger.warning(f"状态不存在: session={session_id}, version={version}")
                return None

            # 加载图层
            cursor.execute("""
                SELECT * FROM layers
                WHERE state_id = ?
                ORDER BY z_order
            """, (state_row['id'],))
            layer_rows = cursor.fetchall()

            # 加载注记
            cursor.execute("""
                SELECT * FROM annotations
                WHERE state_id = ?
            """, (state_row['id'],))
            annotation_rows = cursor.fetchall()

            # 加载会话信息
            cursor.execute("""
                SELECT * FROM sessions WHERE session_id = ?
            """, (session_id,))
            session_row = cursor.fetchone()

            # 反序列化为 MapState 对象
            map_state = self._deserialize_from_db(state_row, layer_rows, annotation_rows, session_row)

            # 更新最后访问时间
            cursor.execute("""
                UPDATE sessions
                SET last_accessed = CURRENT_TIMESTAMP
                WHERE session_id = ?
            """, (session_id,))
            conn.commit()

            self.logger.info(f"状态加载成功: session={session_id}, version={version}")
            return map_state

        except Exception as e:
            self.logger.error(f"状态加载失败: {e}")
            import traceback
            traceback.print_exc()
            return None
        finally:
            if conn:
                conn.close()

    def _deserialize_from_db(self, state_row, layer_rows, annotation_rows, session_row) -> MapState:
        """从数据库行反序列化为 MapState 对象"""
        from ..models.schemas import (
            MapConfig, LayerConfig, AnnotationConfig,
            GeometryType, CoordinateSystem, LayerStyle
        )
        from ..utils.config import Config

        # 构建 MapConfig
        map_config = MapConfig(
            map_id=state_row['map_id'],
            title=state_row['title'],
            extent=json.loads(state_row['extent']) if state_row['extent'] else [0, 0, 1, 1],
            crs=CoordinateSystem(state_row['crs']) if state_row['crs'] else CoordinateSystem.WGS84,
            background_color=state_row['background_color'] or 'white',
            figsize=tuple(json.loads(state_row['figsize'])) if state_row['figsize'] else Config.DEFAULT_FIGSIZE,
            dpi=state_row['dpi'] or Config.DEFAULT_DPI,
            maintain_data_aspect=bool(state_row['maintain_data_aspect']),
            fit_figsize_to_extent=bool(state_row['fit_figsize_to_extent']),
            auto_legend=bool(state_row['auto_legend']),
            auto_scalebar=bool(state_row['auto_scalebar']),
            auto_compass=bool(state_row['auto_compass'])
        )

        # 构建图层列表
        layers = []
        for layer_row in layer_rows:
            style_dict = json.loads(layer_row['style']) if layer_row['style'] else {}

            # 如果有 label_column，添加到 style_dict
            if layer_row['label_column']:
                style_dict['label_column'] = layer_row['label_column']

            layer = LayerConfig(
                layer_id=layer_row['layer_id'],
                name=layer_row['name'],
                data_source=layer_row['data_source'],
                geometry_type=GeometryType(layer_row['geometry_type']) if layer_row['geometry_type'] else GeometryType.POLYGON,
                style=LayerStyle(**style_dict) if style_dict else LayerStyle(),
                visible=bool(layer_row['visible']),
                data_hash=self._row_get(layer_row, 'data_hash'),
                feature_count=self._row_get(layer_row, 'feature_count', 0) or 0,
                extent=json.loads(self._row_get(layer_row, 'extent')) if self._row_get(layer_row, 'extent') else None,
                render_mode=self._row_get(layer_row, 'render_mode', 'geojson') or 'geojson',
                data_url=self._row_get(layer_row, 'data_url'),
                gdf=None  # GeoDataFrame 不存储在数据库中
            )
            layers.append(layer)

        # 构建注记列表
        annotations = []
        for ann_row in annotation_rows:
            style_dict = json.loads(ann_row['style']) if ann_row['style'] else {}

            # 生成唯一ID
            import uuid
            annotation = AnnotationConfig(
                annotation_id=str(uuid.uuid4()),
                text=ann_row['text'],
                position=json.loads(ann_row['position']) if ann_row['position'] else [0, 0],
                font_size=style_dict.get('font_size', 12.0),
                font_family=style_dict.get('font_family', 'Arial'),
                color=style_dict.get('color', 'black'),
                background_color=style_dict.get('background_color'),
                rotation=style_dict.get('rotation', 0.0),
                alignment=style_dict.get('alignment', 'center')
            )
            annotations.append(annotation)

        # 构建 SessionInfo
        session_info = SessionInfo(
            session_id=session_row['session_id'],
            session_name=session_row['session_name'],
            created_at=datetime.fromisoformat(session_row['created_at']) if session_row['created_at'] else datetime.now(),
            last_accessed=datetime.fromisoformat(session_row['last_accessed']) if session_row['last_accessed'] else datetime.now()
        )

        # 构建 MapVersion
        map_version = MapVersion(
            version=state_row['version'],
            parent_version=state_row['parent_version'],
            created_at=datetime.fromisoformat(state_row['created_at']) if state_row['created_at'] else datetime.now(),
            description=state_row['description'] or "",
            is_current=bool(state_row['is_current'])
        )

        # 构建 MapState
        map_state = MapState(
            config=map_config,
            layers=layers,
            legends=[],  # 暂时为空
            annotations=annotations,
            scalebar=json.loads(state_row['scalebar']) if state_row['scalebar'] else None,
            compass=json.loads(state_row['compass']) if state_row['compass'] else None,
            output_path=self._row_get(state_row, 'output_path'),
            schema_version=self._row_get(state_row, 'schema_version', 1) or 1,
            spec_json=json.loads(self._row_get(state_row, 'spec_json')) if self._row_get(state_row, 'spec_json') else None,
            spec_hash=self._row_get(state_row, 'spec_hash'),
            source_fingerprints=json.loads(self._row_get(state_row, 'source_fingerprints')) if self._row_get(state_row, 'source_fingerprints') else {},
            latest_event_seq=self._row_get(state_row, 'latest_event_seq', 0) or 0,
            session_info=session_info,
            version_info=map_version,
            is_generalization_task=bool(state_row['is_generalization_task']),
            generalization_algorithm=self._row_get(state_row, 'generalization_algorithm'),
            generalization_params=json.loads(self._row_get(state_row, 'generalization_params')) if self._row_get(state_row, 'generalization_params') else None,
            generalization_input_path=self._row_get(state_row, 'generalization_input_path'),
            generalization_output_path=self._row_get(state_row, 'generalization_output_path'),
            generalization_metrics=json.loads(self._row_get(state_row, 'generalization_metrics')) if self._row_get(state_row, 'generalization_metrics') else None,
            generalization_result_meta=json.loads(self._row_get(state_row, 'generalization_result_meta')) if self._row_get(state_row, 'generalization_result_meta') else None,
            generalization_result=json.loads(state_row['generalization_result']) if state_row['generalization_result'] else None,
            created_at=state_row['created_at'],
            updated_at=state_row['updated_at']
        )

        return map_state
    
    def list_sessions(self) -> List[Dict[str, any]]:
        """从数据库列出所有会话

        Returns:
            List[Dict]: 会话信息列表
        """
        sessions = []
        conn = None

        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("""
                SELECT
                    s.session_id,
                    s.session_name,
                    s.created_at,
                    s.last_accessed,
                    s.current_version,
                    COUNT(DISTINCT m.version) as total_versions
                FROM sessions s
                LEFT JOIN map_states m ON s.session_id = m.session_id
                GROUP BY s.session_id
                ORDER BY s.last_accessed DESC
            """)

            for row in cursor.fetchall():
                sessions.append({
                    'session_id': row['session_id'],
                    'session_name': row['session_name'],
                    'created_at': row['created_at'],
                    'last_accessed': row['last_accessed'],
                    'current_version': row['current_version'],
                    'total_versions': row['total_versions']
                })

        except Exception as e:
            self.logger.error(f"列出会话失败: {e}")
        finally:
            if conn:
                conn.close()

        return sessions
    
    def list_versions(self, session_id: str) -> List[Dict[str, any]]:
        """从数据库列出会话的所有版本

        Args:
            session_id: 会话ID

        Returns:
            List[Dict]: 版本信息列表
        """
        versions = []
        conn = None

        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("""
                SELECT
                    version,
                    created_at,
                    description,
                    is_current,
                    parent_version
                FROM map_states
                WHERE session_id = ?
                ORDER BY version
            """, (session_id,))

            for row in cursor.fetchall():
                versions.append({
                    'version': row['version'],
                    'created_at': row['created_at'],
                    'description': row['description'],
                    'is_current': bool(row['is_current']),
                    'parent_version': row['parent_version']
                })

        except Exception as e:
            self.logger.error(f"列出版本失败: {e}")
        finally:
            if conn:
                conn.close()

        return versions

    def list_recent_versions(self, session_id: str, limit: int = 5) -> List[Dict[str, any]]:
        return self.list_versions(session_id)[-limit:]

    def rollback_to_previous(self, session_id: str) -> Optional[MapState]:
        versions = self.list_versions(session_id)
        if len(versions) < 2:
            return None
        current = next((item for item in versions if item.get("is_current")), versions[-1])
        previous_versions = [item for item in versions if item["version"] < current["version"]]
        if not previous_versions:
            return None
        previous_state = self.load_state(session_id, previous_versions[-1]["version"])
        if previous_state is None:
            return None
        conn = None
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("UPDATE map_states SET is_current = 0 WHERE session_id = ?", (session_id,))
            cursor.execute(
                "UPDATE map_states SET is_current = 1 WHERE session_id = ? AND version = ?",
                (session_id, previous_state.get_current_version()),
            )
            cursor.execute(
                "UPDATE sessions SET current_version = ?, last_accessed = CURRENT_TIMESTAMP WHERE session_id = ?",
                (previous_state.get_current_version(), session_id),
            )
            conn.commit()
            return previous_state
        except Exception as e:
            if conn:
                conn.rollback()
            self.logger.error(f"回退版本失败: {e}")
            return None
        finally:
            if conn:
                conn.close()
    
    def delete_session(self, session_id: str) -> bool:
        """从数据库删除会话及其所有版本

        Args:
            session_id: 会话ID

        Returns:
            bool: 删除是否成功
        """
        conn = None
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # 检查会话是否存在
            cursor.execute("SELECT session_id FROM sessions WHERE session_id = ?", (session_id,))
            if not cursor.fetchone():
                # self.logger.warning(f"会话不存在: {session_id}")
                return False

            # 删除会话（级联删除相关的 map_states, layers, annotations）
            cursor.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))

            conn.commit()
            self.logger.info(f"会话删除成功: {session_id}")
            return True

        except Exception as e:
            if conn:
                conn.rollback()
            self.logger.error(f"删除会话失败: {e}")
            return False
        finally:
            if conn:
                conn.close()



# 使用单例装饰器创建全局状态管理器
@singleton
class _StateManagerSingleton:
    """状态管理器单例包装器"""
    def __init__(self):
        self.manager = MapStateManager()

def get_state_manager() -> MapStateManager:
    """获取全局状态管理器实例

    Returns:
        MapStateManager: 全局唯一的状态管理器实例

    Note:
        使用单例模式确保整个应用只有一个状态管理器实例
    """
    return _StateManagerSingleton().manager
