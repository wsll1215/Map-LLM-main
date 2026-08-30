from gis_mapping_agent.models.schemas import GeometryType, LayerConfig, MapConfig, MapState, SessionInfo
from gis_mapping_agent.specs import AdjustmentPatch, PatchOperation
from gis_mapping_agent.adjustment import ModificationEngine
from gis_mapping_agent.utils.intent_classifier_v2 import BatchOperation, IntentAnalysisV2, IntentClassifierV2

import pytest


def make_state():
    return MapState(
        config=MapConfig(map_id="m1", title="old", extent=[0, 0, 1, 1]),
        session_info=SessionInfo(session_id="s1"),
        layers=[
            LayerConfig(layer_id="l1", name="roads", geometry_type=GeometryType.LINE, data={"type": "FeatureCollection"}),
            LayerConfig(layer_id="l2", name="railway", geometry_type=GeometryType.LINE, data={"type": "FeatureCollection"}),
        ],
        is_generalization_task=True,
        generalization_params={"algorithm": "stroke", "target_scale": 1000, "keep_ratio": 0.5},
    )


def test_adjustment_patch_executes_dynamic_operations():
    patch = AdjustmentPatch(
        operations=[
            PatchOperation(action="remove_layer", target="railway"),
            PatchOperation(action="toggle_layer_visibility", target="roads", parameters={"visible": False}),
            PatchOperation(action="style_layer", target="roads", parameters={"color": "red", "linewidth": 2, "alpha": 0.4}),
            PatchOperation(action="update_map_config", target="title", parameters={"title": "new"}),
            PatchOperation(action="update_generalization_params", target="generalization", parameters={"retention_ratio": 0.3, "target_scale": 2000, "algorithm": "hierarchy"}),
        ]
    )

    result = ModificationEngine().apply_modifications(make_state(), patch, "change map")
    state, records = result
    roads = state.layers[0]

    assert len(records) == 5
    assert [layer.name for layer in state.layers] == ["roads"]
    assert roads.visible is False
    assert roads.style.color == "red"
    assert roads.style.linewidth == 2
    assert roads.style.alpha == 0.4
    assert state.config.title == "new"
    assert state.generalization_params["keep_ratio"] == 0.3
    assert state.generalization_params["target_scale"] == 2000
    assert state.generalization_params["algorithm"] == "hierarchy"
    assert result.diff["layers"]["removed"] == ["railway"]
    assert result.diff["layers"]["visibility"]["roads"]["after"] is False


def test_remove_layer_requires_existing_target():
    patch = AdjustmentPatch(operations=[PatchOperation(action="remove_layer", target="Railway")])

    with pytest.raises(ValueError, match="未找到图层"):
        ModificationEngine().apply_modifications(make_state(), patch, "删除不存在的铁路图层")


def test_intent_validation_rejects_llm_target_when_user_reference_is_missing():
    state = MapState(
        config=MapConfig(map_id="m2", title="data5", extent=[0, 0, 1, 1]),
        session_info=SessionInfo(session_id="s2"),
        layers=[
            LayerConfig(layer_id="l1", name="Wuhan", geometry_type=GeometryType.POLYGON, data_source="data5/Wuhan.shp"),
            LayerConfig(layer_id="l2", name="Skating Rink", geometry_type=GeometryType.POINT, data_source="data5/Skating Rink.shp"),
            LayerConfig(layer_id="l3", name="Racecourse", geometry_type=GeometryType.POINT, data_source="data5/Racecourse.shp"),
        ],
    )
    analysis = IntentAnalysisV2(
        request="删除铁路图层",
        intent="remove_layer",
        confidence=0.9,
        target="Wuhan",
        requires_confirmation=False,
        reasoning="mocked wrong LLM target",
    )

    validated = IntentClassifierV2.__new__(IntentClassifierV2).validate_intent_with_state(analysis, state)

    assert validated.clarification_questions
    assert "铁路" in validated.clarification_questions[0]
    assert "Wuhan" in validated.clarification_questions[0]


def test_intent_validation_rejects_extra_batch_layer_not_mentioned_by_user():
    state = MapState(
        config=MapConfig(map_id="m3", title="data5", extent=[0, 0, 1, 1]),
        session_info=SessionInfo(session_id="s3"),
        layers=[
            LayerConfig(layer_id="l1", name="Wuhan", geometry_type=GeometryType.POLYGON, data_source="data5/Wuhan.shp"),
            LayerConfig(layer_id="l2", name="Skating Rink", geometry_type=GeometryType.POINT, data_source="data5/Skating Rink.shp"),
            LayerConfig(layer_id="l3", name="Racecourse", geometry_type=GeometryType.POINT, data_source="data5/Racecourse.shp"),
        ],
    )
    analysis = IntentAnalysisV2(
        request="删除Skating Rink",
        intent="remove_layer",
        confidence=0.9,
        target="multiple",
        batch_operations=[
            BatchOperation(type="remove_layer", layer_name="Skating Rink"),
            BatchOperation(type="remove_layer", layer_name="Wuhan"),
        ],
        requires_confirmation=False,
        reasoning="mocked extra LLM target",
    )

    validated = IntentClassifierV2.__new__(IntentClassifierV2).validate_intent_with_state(analysis, state)

    assert validated.clarification_questions
    assert "额外目标" in validated.clarification_questions[0]
    assert "Wuhan" in validated.clarification_questions[0]


def test_intent_analysis_allows_missing_reasoning_from_llm_tool_call():
    analysis = IntentAnalysisV2(
        request="修改铁路图层颜色为红色",
        intent="style_layer",
        target="Railway",
        color="#FF0000",
    )

    assert analysis.reasoning == ""
    assert analysis.confidence == 0.8


def test_chinese_layer_alias_style_request_generates_patch():
    state = MapState(
        config=MapConfig(map_id="m4", title="roads", extent=[0, 0, 1, 1]),
        session_info=SessionInfo(session_id="s4"),
        layers=[
            LayerConfig(layer_id="railway", name="Railway", geometry_type=GeometryType.LINE, data_source="data1/Railway.shp"),
        ],
    )
    analysis = IntentAnalysisV2(
        request="将铁路的线变成红色",
        intent="style_layer",
        target="铁路",
        color="#FF0000",
    )

    classifier = IntentClassifierV2.__new__(IntentClassifierV2)
    validated = classifier.validate_intent_with_state(analysis, state)
    patch = ModificationEngine().generate_modification_plan(validated)

    assert not validated.clarification_questions
    assert validated.target == "Railway"
    assert patch.operations[0].action == "style_layer"
    assert patch.operations[0].target == "Railway"
    assert patch.operations[0].parameters["color"] == "#FF0000"


def test_batch_poi_request_routes_to_remote_point_layer(monkeypatch):
    state = make_state()
    mocked_analysis = IntentAnalysisV2(
        request="标注出秦皇岛各大高校的位置",
        intent="add_annotation",
        target="秦皇岛各大高校",
        confidence=0.9,
    )

    monkeypatch.setattr(
        "gis_mapping_agent.adjustment.engine.get_intent_classifier_v2",
        lambda: type(
            "Classifier",
            (),
            {
                "classify_intent": lambda self, request, current_state: mocked_analysis,
                "validate_intent_with_state": lambda self, analysis, current_state: analysis,
            },
        )(),
    )

    analysis = ModificationEngine().analyze_modification_request(
        "标注出秦皇岛各大高校的位置", state
    )
    patch = ModificationEngine().generate_modification_plan(analysis)

    assert analysis.intent == "add_layer"
    assert analysis.layer_name == "秦皇岛高校"
    assert analysis.source == "remote_poi://universities/秦皇岛"
    assert patch.operations[0].action == "add_layer"
    assert patch.operations[0].parameters["source"] == "remote_poi://universities/秦皇岛"


def test_remote_poi_patch_loads_cached_geojson_as_point_layer(tmp_path, monkeypatch):
    source_path = tmp_path / "universities.geojson"
    source_path.write_text(
        '{"type":"FeatureCollection","features":[{"type":"Feature","properties":{"name":"燕山大学"},"geometry":{"type":"Point","coordinates":[119.5,39.9]}}]}',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "gis_mapping_agent.adjustment.engine.fetch_remote_pois",
        lambda place, bbox, category="universities": source_path,
    )

    patch = AdjustmentPatch(
        operations=[
            PatchOperation(
                action="add_layer",
                target="秦皇岛高校",
                parameters={"source": "remote_poi://universities/秦皇岛"},
            )
        ]
    )

    new_state, records = ModificationEngine().apply_modifications(make_state(), patch, "标注高校")

    assert len(records) == 1
    assert new_state.layers[-1].name == "秦皇岛高校"
    assert new_state.layers[-1].geometry_type.value == "point"
    assert new_state.layers[-1].data_source.startswith("dataset://remote-")
    assert new_state.layers[-1].data_source_meta["source_type"] == "remote"


def test_remote_poi_adjustment_registers_download_before_runtime_read(monkeypatch, tmp_path):
    import geopandas as gpd
    from shapely.geometry import Point

    from gis_mapping_agent.adjustment import engine

    source_path = tmp_path / "universities.geojson"
    source_path.write_text("{}", encoding="utf-8")
    frame = gpd.GeoDataFrame(
        {"name": ["university"]},
        geometry=[Point(119.5, 39.9)],
        crs="EPSG:4326",
    )
    register_calls = []

    monkeypatch.setattr(
        "gis_mapping_agent.adjustment.engine.fetch_remote_pois",
        lambda place, bbox, category="universities": source_path,
    )
    monkeypatch.setattr(
        "mapping.dataset_reader.register_geojson_dataset",
        lambda path, **kwargs: register_calls.append((path, kwargs)) or "remote-university-1",
    )
    monkeypatch.setattr(
        "mapping.dataset_reader.read_dataset_features",
        lambda dataset_id, bbox=None, limit=None: frame,
    )
    monkeypatch.setattr(
        "geopandas.read_file",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("remote adjustment must read the normalized Dataset")
        ),
    )

    patch = AdjustmentPatch(
        operations=[
            PatchOperation(
                action="add_layer",
                target="秦皇岛高校",
                parameters={"source": "remote_poi://universities/秦皇岛"},
            )
        ]
    )

    new_state, _ = ModificationEngine().apply_modifications(make_state(), patch, "标注高校")

    assert register_calls and register_calls[0][0] == source_path
    assert new_state.layers[-1].data_source == "dataset://remote-university-1"


def test_adjustment_runtime_layer_reads_registered_dataset(monkeypatch):
    import geopandas as gpd
    from shapely.geometry import Point
    from gis_mapping_agent.adjustment import engine

    state = make_state()
    frame = gpd.GeoDataFrame(
        {"name": ["road"]},
        geometry=[Point(119.5, 39.5)],
        crs="EPSG:4326",
    )
    monkeypatch.setattr(
        "mapping.dataset_reader.read_dataset_features",
        lambda dataset_id, bbox=None, limit=None: frame,
    )
    monkeypatch.setattr(
        "geopandas.read_file",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("adjustment runtime must not read the source file")
        ),
    )

    patch = AdjustmentPatch(
        operations=[
            PatchOperation(
                action="add_layer",
                target="道路",
                parameters={
                    "source": "dataset://road-1",
                    "data_source_meta": {
                        "dataset_id": "road-1",
                        "source_type": "local",
                        "provider": "PostGIS",
                    },
                },
            )
        ]
    )

    new_state, records = ModificationEngine().apply_modifications(state, patch, "添加道路")

    assert len(records) == 1
    assert new_state.layers[-1].data_source == "dataset://road-1"
    assert new_state.layers[-1].data_source_meta["dataset_id"] == "road-1"


def test_adjustment_explicit_file_is_normalized_before_runtime_use(monkeypatch, tmp_path):
    import geopandas as gpd
    from shapely.geometry import Point

    from gis_mapping_agent.adjustment import engine

    source_path = tmp_path / "roads.shp"
    source_path.touch()
    frame = gpd.GeoDataFrame(
        {"name": ["road"]}, geometry=[Point(119.5, 39.9)], crs="EPSG:4326"
    )
    register_calls = []
    monkeypatch.setattr(
        "gis_mapping_agent.utils.data_path_resolver.extract_data_info_from_request",
        lambda _source: (str(tmp_path), [source_path.name]),
    )
    monkeypatch.setattr(
        "gis_mapping_agent.utils.data_path_resolver.resolve_data_path",
        lambda _directory=None: tmp_path,
    )
    monkeypatch.setattr("geopandas.read_file", lambda _path: frame)
    monkeypatch.setattr(
        "mapping.dataset_reader.register_geodataframe_dataset",
        lambda imported, **kwargs: register_calls.append((imported, kwargs)) or "imported-road-1",
    )
    monkeypatch.setattr(
        "mapping.dataset_reader.read_dataset_features",
        lambda dataset_id, bbox=None, limit=None: frame,
    )

    patch = AdjustmentPatch(
        operations=[
            PatchOperation(
                action="add_layer",
                target="roads",
                parameters={"source": source_path.name},
            )
        ]
    )

    new_state, _ = ModificationEngine().apply_modifications(make_state(), patch, "添加道路")

    assert register_calls and register_calls[0][0] is frame
    assert new_state.layers[-1].data_source == "dataset://imported-road-1"


def test_batch_poi_request_uses_deterministic_route_when_llm_fails(monkeypatch):
    state = make_state()
    monkeypatch.setattr(
        "gis_mapping_agent.adjustment.engine.get_intent_classifier_v2",
        lambda: (_ for _ in ()).throw(RuntimeError("LLM unavailable")),
    )

    analysis = ModificationEngine().analyze_modification_request(
        "标注出秦皇岛各大高校的位置", state
    )

    assert analysis.intent == "add_layer"
    assert analysis.source == "remote_poi://universities/秦皇岛"


def test_generic_poi_request_uses_current_map_place_when_request_omits_place(monkeypatch):
    state = make_state()
    state.config.title = "秦皇岛市地图"
    mocked_analysis = IntentAnalysisV2(
        request="把小学画出来",
        intent="add_annotation",
        target="小学",
        confidence=0.9,
    )
    monkeypatch.setattr(
        "gis_mapping_agent.adjustment.engine.get_intent_classifier_v2",
        lambda: type(
            "Classifier",
            (),
            {
                "classify_intent": lambda self, request, current_state: mocked_analysis,
                "validate_intent_with_state": lambda self, analysis, current_state: analysis,
            },
        )(),
    )

    analysis = ModificationEngine().analyze_modification_request("把小学画出来", state)

    assert analysis.intent == "add_layer"
    assert analysis.layer_name == "秦皇岛市小学"
    assert analysis.source == "remote_poi://primary_schools/秦皇岛市"
