from pathlib import Path

from gis_mapping_agent.tools.unified_mapping_tools import UnifiedMappingTools


def test_init_map_without_verified_extent_does_not_use_global_default() -> None:
    tools = UnifiedMappingTools()

    result = tools.init_map({"title": "未指定地点"})

    assert result["success"] is False
    assert result["error_code"] == "clarification_required"
    assert result["next_action"] == "provide_location"


def test_layer_data_replaces_global_init_extent(tmp_path) -> None:
    tools = UnifiedMappingTools()
    initialized = tools.init_map({"title": "北京地图", "extent": [-180, -90, 180, 90]})
    assert initialized["success"] is True

    result = tools.add_layer({
        "name": "北京",
        "data_path": str(Path("data/data8/Beijing.shp")),
    })

    assert result["success"] is True
    min_x, min_y, max_x, max_y = tools.current_map_state.config.extent
    assert 115 < min_x < 116
    assert 39 < min_y < 40
    assert 117 < max_x < 118
    assert 40 < max_y < 42
    assert tools.current_map_state.layers[0].feature_count == result["feature_count"]
    assert tools.current_map_state.layers[0].feature_count > 0

    saved = tools.map_save({"filename": "non_empty_map.png", "output_dir": str(tmp_path)})

    assert saved["success"] is True
    assert saved["file_size"] > 1000
