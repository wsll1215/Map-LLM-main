from gis_mapping_agent.data_sources.planner import plan_local_sources


PROMPT = "绘制广东省的地图，要标定出广东省下的所有城市以及道路河流"


def test_guangdong_request_selects_distinct_sources_and_city_labels():
    plan = plan_local_sources(PROMPT)

    assert plan.boundary_path == "data/data1/Guangdong.shp"
    assert plan.road_path == "data/data1/Highway.shp"
    assert plan.river_path is None
    assert "未找到可用的河流数据" in plan.issues
    assert plan.city_label_column == "name"
    assert len({plan.boundary_path, plan.road_path}) == 2


def test_semantic_plan_resolves_layer_names_to_their_roles():
    plan = plan_local_sources(PROMPT)

    assert plan.path_for_layer("广东省") == plan.boundary_path
    assert plan.path_for_layer("道路") == plan.road_path
    assert plan.path_for_layer("河流") is None


def test_annotation_request_does_not_trigger_city_dataset_validation():
    plan = plan_local_sources("标注清华大学的位置")

    assert plan.city_label_column is None
    assert not any("城市" in issue for issue in plan.issues)


def test_guangdong_request_does_not_use_wuhan_river_dataset():
    plan = plan_local_sources(PROMPT)

    assert plan.river_path is None
    assert "未找到可用的河流数据" in plan.issues
