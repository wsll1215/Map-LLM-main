from pydantic import BaseModel

from gis_mapping_agent.agent import ThinkingGISMappingAgent


class _WithSession(BaseModel):
    session_id: str | None = None
    value: int = 1


class _WithoutSession(BaseModel):
    value: int = 1


class _Tool:
    def __init__(self, args_schema):
        self.args_schema = args_schema


def test_tool_input_gets_session_id_when_schema_accepts_it():
    agent = ThinkingGISMappingAgent.__new__(ThinkingGISMappingAgent)
    agent.session_id = "session-1"

    result = agent._with_session_id(_Tool(_WithSession), {"value": 2})

    assert result == {"value": 2, "session_id": "session-1"}


def test_tool_input_keeps_existing_session_id_and_ignores_other_tools():
    agent = ThinkingGISMappingAgent.__new__(ThinkingGISMappingAgent)
    agent.session_id = "session-1"

    assert agent._with_session_id(_Tool(_WithSession), {"session_id": "manual"})["session_id"] == "manual"
    assert agent._with_session_id(_Tool(_WithoutSession), {"value": 2}) == {"value": 2}
