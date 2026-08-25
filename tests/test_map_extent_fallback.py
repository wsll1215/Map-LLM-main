from pathlib import Path

from gis_mapping_agent.tools.unified_mapping_tools import UnifiedMappingTools


def test_layer_data_replaces_global_init_extent() -> None:
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
