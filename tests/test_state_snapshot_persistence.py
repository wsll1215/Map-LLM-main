import sqlite3

from gis_mapping_agent.models.schemas import (
    GeometryType,
    LayerConfig,
    MapConfig,
    MapState,
    SessionInfo,
)
from gis_mapping_agent.state import MapStateManager


def test_snapshot_metadata_roundtrips_with_layer_manifest(tmp_path):
    manager = MapStateManager(str(tmp_path / "states.db"))
    state = MapState(
        config=MapConfig(map_id="map-1", title="北京道路", extent=[115, 39, 117, 41]),
        session_info=SessionInfo(session_id="session-1"),
        schema_version=1,
        spec_json={"schema_version": 1, "map_id": "map-1", "version": 1},
        spec_hash="sha256:map-1",
        source_fingerprints={
            "roads": {"sha256": "sha256:roads", "size": 2048, "mtime": 1724342400}
        },
        latest_event_seq=7,
        layers=[
            LayerConfig(
                layer_id="roads",
                name="道路",
                geometry_type=GeometryType.LINE,
                data_source="data/roads.shp",
                data_hash="sha256:roads",
                feature_count=110000,
                extent=[115, 39, 117, 41],
                render_mode="mvt",
                data_url="/mapping/api/map-requests/1/snapshots/1/layers/roads/",
            )
        ],
    )

    assert manager.save_state(state)
    loaded = manager.load_state("session-1")

    assert loaded is not None
    assert loaded.schema_version == 1
    assert loaded.spec_json["map_id"] == "map-1"
    assert loaded.spec_hash == "sha256:map-1"
    assert loaded.source_fingerprints["roads"]["sha256"] == "sha256:roads"
    assert loaded.latest_event_seq == 7
    assert loaded.layers[0].data_hash == "sha256:roads"
    assert loaded.layers[0].feature_count == 110000
    assert loaded.layers[0].extent == [115, 39, 117, 41]
    assert loaded.layers[0].render_mode == "mvt"
    assert loaded.layers[0].data_url.endswith("/roads/")


def test_legacy_state_database_gets_snapshot_columns(tmp_path):
    db_path = tmp_path / "legacy.db"
    connection = sqlite3.connect(db_path)
    connection.executescript(
        """
        CREATE TABLE map_states (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            version INTEGER NOT NULL,
            map_id TEXT NOT NULL,
            is_current INTEGER DEFAULT 1
        );
        CREATE TABLE layers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            state_id INTEGER NOT NULL,
            layer_id TEXT NOT NULL,
            name TEXT NOT NULL,
            z_order INTEGER DEFAULT 0
        );
        """
    )
    connection.commit()
    connection.close()

    MapStateManager(str(db_path))

    connection = sqlite3.connect(db_path)
    map_state_columns = {
        row[1] for row in connection.execute("PRAGMA table_info(map_states)")
    }
    layer_columns = {
        row[1] for row in connection.execute("PRAGMA table_info(layers)")
    }
    connection.close()

    assert {
        "schema_version",
        "spec_json",
        "spec_hash",
        "source_fingerprints",
        "latest_event_seq",
    } <= map_state_columns
    assert {
        "data_hash",
        "feature_count",
        "extent",
        "render_mode",
        "data_url",
    } <= layer_columns
