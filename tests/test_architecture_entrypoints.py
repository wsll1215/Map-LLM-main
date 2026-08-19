from gis_mapping_agent.adjustment import ModificationEngine
from gis_mapping_agent.agent import ConversationalMappingAgent, ThinkingGISMappingAgent
from gis_mapping_agent.gis import DataLoader, calculate_extent_from_files, format_extent_for_request
from gis_mapping_agent.generalization import GeneralizationResult, RoadNetworkGeneralizationEngine
from gis_mapping_agent.rendering import MapQualityChecker
from gis_mapping_agent.state import MapStateManager, get_session_context
from gis_mapping_agent.tools import GENERALIZATION_TOOLS


def test_target_architecture_entrypoints_are_importable():
    assert ConversationalMappingAgent is not None
    assert ThinkingGISMappingAgent is not None
    assert RoadNetworkGeneralizationEngine is not None
    assert GeneralizationResult is not None
    assert MapQualityChecker is not None
    assert MapStateManager is not None
    assert ModificationEngine is not None
    assert DataLoader is not None
    assert calculate_extent_from_files is not None
    assert format_extent_for_request([1, 2, 3, 4]) == "[1.0000, 2.0000, 3.0000, 4.0000]"
    assert get_session_context("entrypoint-test") is not None
    assert {tool.name for tool in GENERALIZATION_TOOLS} >= {
        "generalize_road_network",
        "visualize_generalization",
        "modify_generalization_params",
    }
