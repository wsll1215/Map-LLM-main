from gis_mapping_agent.agent.intent_rules import RuleParser


def test_rule_parser_recognizes_control_commands_without_llm():
    result = RuleParser().parse("请停止当前任务")

    assert result.decision == "complete"
    assert result.intent.task == "cancel"
    assert result.llm_required is False


def test_rule_parser_extracts_location_and_registered_layers_from_generic_expression():
    result = RuleParser().parse("给我天津市的地图，并且要有道路跟河流")

    assert result.decision == "complete"
    assert result.intent.task == "create_map"
    assert result.intent.location.text == "天津市"
    assert {layer.role for layer in result.intent.layers} == {"road", "river"}
    assert result.field_evidence["location"].source == "rule"


def test_rule_parser_keeps_equivalent_surface_forms_equivalent():
    expressions = [
        "请制作成都市地图，显示主要道路和河流",
        "帮我做一张成都市的图，把水系和路网都标出来",
    ]

    results = [RuleParser().parse(expression) for expression in expressions]

    assert all(result.decision == "complete" for result in results)
    assert {result.intent.location.text for result in results} == {"成都市"}
    assert {tuple(sorted(layer.role for layer in result.intent.layers)) for result in results} == {
        ("river", "road")
    }


def test_rule_parser_returns_partial_when_location_is_missing():
    result = RuleParser().parse("请显示主要道路和河流")

    assert result.decision == "partial"
    assert result.llm_required is True
    assert "location" in result.missing_fields


def test_rule_parser_returns_conflict_for_multiple_primary_locations():
    result = RuleParser().parse("制作天津市和北京市的道路地图")

    assert result.decision == "conflict"
    assert result.conflicts == ["multiple_locations"]
    assert "location" in result.missing_fields


def test_rule_parser_extracts_explicit_sources_without_selecting_a_dataset():
    result = RuleParser().parse("使用 data/roads.geojson 绘制某市道路")

    assert result.intent.explicit_sources == ["data/roads.geojson"]
    assert "dataset_id" not in result.intent.model_dump()
