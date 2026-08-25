from pathlib import Path

from gis_mapping_agent.agent.thinking import ThinkingGISMappingAgent


class CaptureTool:
    name = "add_layer"
    args_schema = None

    def __init__(self):
        self.received = None

    def invoke(self, tool_input):
        self.received = tool_input
        return {"success": True}


def test_location_default_file_overrides_model_hallucinated_path():
    tool = CaptureTool()
    agent = object.__new__(ThinkingGISMappingAgent)
    agent.tool_dict = {"add_layer": tool}
    agent.session_id = None
    agent._default_data_file_path = Path("data/data8/Beijing.shp")
    agent._explicit_data_files = False

    agent._execute_tool("add_layer", {"name": "北京", "data_path": "data/北京市.shp"})

    assert tool.received["data_path"] == "data/data8/Beijing.shp"
