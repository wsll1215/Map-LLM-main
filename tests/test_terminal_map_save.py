from pathlib import Path

from gis_mapping_agent.agent import ThinkingGISMappingAgent
from gis_mapping_agent.tools.unified_mapping_tools import UnifiedMappingTools


class _FakeLogger:
    def __init__(self):
        self.info_messages = []

    def info(self, message):
        self.info_messages.append(message)

    def error(self, message):
        pass


def test_map_save_records_output_path(tmp_path):
    tools = UnifiedMappingTools()
    init_result = tools.init_map(
        {
            "title": "测试地图",
            "extent": [109.0, 30.0, 110.0, 31.0],
            "figsize": (4, 3),
            "dpi": 80,
            "auto_scalebar": False,
            "auto_compass": False,
        }
    )

    assert init_result["success"]

    save_result = tools.map_save(
        {
            "filename": "saved_map",
            "output_dir": str(tmp_path),
            "dpi": 80,
            "format": "png",
        }
    )

    assert save_result["success"]
    assert tools.current_map_state.output_path == str(tmp_path / "saved_map.png")
    assert Path(tools.current_map_state.output_path).exists()


def test_terminal_tool_result_does_not_log_create_complete(monkeypatch):
    agent = ThinkingGISMappingAgent.__new__(ThinkingGISMappingAgent)
    agent.logger = _FakeLogger()
    agent.save_tool = None

    monkeypatch.setattr(agent, "_calculate_auto_extent", lambda **kwargs: (None, None))
    monkeypatch.setattr(agent, "_enhance_request_with_auto_extent", lambda request: request)
    monkeypatch.setattr(
        agent,
        "_execute_thinking_loop",
        lambda request: {
            "success": True,
            "message": "地图创建完成",
            "output": "✅ 地图已保存",
            "thinking_steps": [],
            "terminal_tool": "map_save",
        },
    )
    monkeypatch.setattr(agent, "_get_final_map_state", lambda: None)

    result = agent.create_map("保存地图")

    assert result["success"]
    assert "地图创建完成" not in agent.logger.info_messages
