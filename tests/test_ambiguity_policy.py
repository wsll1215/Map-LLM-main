from gis_mapping_agent.agent.ambiguity import detect_ambiguity


def test_short_create_request_requires_scope_and_layer():
    result = detect_ambiguity("帮我画个图", has_map_state=False)

    assert result is not None
    assert result["reason"] == "incomplete_create_request"
    assert "map_scope" in result["missing_fields"]
    assert result["suggestions"]


def test_location_only_request_does_not_guess_a_map_type():
    result = detect_ambiguity("北京", has_map_state=False)

    assert result is not None
    assert result["reason"] == "location_without_map_type"


def test_vague_adjustment_requires_a_target():
    result = detect_ambiguity("再改一下", has_map_state=True)

    assert result is not None
    assert result["reason"] == "incomplete_adjustment_request"
    assert "target" in result["missing_fields"]


def test_conflicting_layer_scope_is_not_executed():
    result = detect_ambiguity("只显示道路，但加上所有建筑", has_map_state=False)

    assert result is not None
    assert result["reason"] == "conflicting_layer_scope"


def test_specific_map_request_is_not_blocked():
    result = detect_ambiguity(
        "请绘制武汉市行政区划图，显示各区边界", has_map_state=False
    )

    assert result is None


def test_specific_adjustment_is_not_blocked():
    result = detect_ambiguity("把道路图层改成深绿色", has_map_state=True)

    assert result is None
