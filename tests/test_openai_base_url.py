from gis_mapping_agent.utils.config import Config


def test_openai_compatible_base_url_gets_v1_path():
    assert Config._normalize_base_url("https://weapi.pw") == "https://weapi.pw/v1"
    assert Config._normalize_base_url("https://weapi.pw/v1") == "https://weapi.pw/v1"


def test_openai_compatible_base_url_preserves_custom_path():
    assert Config._normalize_base_url("https://weapi.pw/openai") == "https://weapi.pw/openai"
    assert Config._normalize_base_url("https://weapi.pw/openai/") == "https://weapi.pw/openai"
