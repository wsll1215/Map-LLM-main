from pathlib import Path

from PIL import Image

from mapping.finalization import LayerValidation, finalize_execution, validate_source_spatial


def _png(path: Path):
    Image.new("RGB", (2, 2), "white").save(path)


def test_finalizer_completes_only_when_all_required_layers_and_png_are_valid(tmp_path):
    output = tmp_path / "map.png"
    _png(output)

    result = finalize_execution(
        required_roles={"boundary", "road"},
        layers=[
            LayerValidation("boundary", True, "local", 1, True),
            LayerValidation("road", True, "remote", 4, True),
        ],
        png_path=output,
        trace_id="trace-1",
    )

    assert result.status == "completed"
    assert result.error_code is None


def test_finalizer_returns_partial_when_a_required_layer_is_missing_but_result_is_viewable(tmp_path):
    output = tmp_path / "map.png"
    _png(output)

    result = finalize_execution(
        required_roles={"boundary", "school"},
        layers=[LayerValidation("boundary", True, "remote", 1, True)],
        png_path=output,
        trace_id="trace-2",
    )

    assert result.status == "partial"
    assert result.completion_report["missing_layers"] == ["school"]


def test_finalizer_fails_when_png_is_missing_even_if_agent_claims_success(tmp_path):
    result = finalize_execution(
        required_roles={"boundary"},
        layers=[LayerValidation("boundary", True, "local", 1, True)],
        png_path=tmp_path / "missing.png",
        trace_id="trace-3",
    )

    assert result.status == "failed"
    assert result.error_code == "render_error"


def test_finalizer_fails_when_png_exists_but_no_valid_layer_exists(tmp_path):
    output = tmp_path / "map.png"
    _png(output)

    result = finalize_execution(
        required_roles=set(), layers=[], png_path=output, trace_id="trace-5"
    )

    assert result.status == "failed"
    assert result.error_code == "resource_not_found"


def test_finalizer_does_not_complete_when_required_layer_is_present_but_invalid(tmp_path):
    output = tmp_path / "map.png"
    _png(output)

    result = finalize_execution(
        required_roles={"boundary"},
        layers=[
            LayerValidation(
                "boundary", True, "local", 2, spatial_valid=False,
                geometry_valid=True, source_valid=True,
            )
        ],
        png_path=output,
        trace_id="trace-invalid",
    )

    assert result.status == "failed"
    assert result.completion_report["missing_layers"] == ["boundary"]


def test_finalizer_preserves_clarification_as_terminal_decision(tmp_path):
    result = finalize_execution(
        required_roles={"boundary"},
        layers=[],
        png_path=None,
        trace_id="trace-4",
        clarification_required=True,
    )

    assert result.status == "needs_clarification"


def test_spatial_validation_does_not_read_unregistered_runtime_file(tmp_path):
    source = type(
        "Source",
        (),
        {
            "data_source": str(tmp_path / "roads.geojson"),
            "cache_path": str(tmp_path / "roads.geojson"),
            "data_source_meta": {},
            "feature_count": 12,
        },
    )()
    location = type("Location", (), {"geometry": None, "bbox": [0, 0, 1, 1]})()

    result = validate_source_spatial(source, location, "road")

    assert result.geometry_valid is False
    assert result.spatial_valid is False
    assert result.reason == "dataset_not_registered"


def test_admin_completion_action_delegates_terminal_decision_to_finalizer(monkeypatch):
    from types import SimpleNamespace

    from mapping.admin_enhanced import MapRequestAdminEnhanced

    request = SimpleNamespace(id=1, result_message="已有成果")
    finalized = []
    messages = []

    monkeypatch.setattr(
        "mapping.admin_enhanced._finalize_map_request",
        lambda item, *_args, **_kwargs: finalized.append(item)
        or SimpleNamespace(status="failed"),
        raising=False,
    )
    admin_instance = object.__new__(MapRequestAdminEnhanced)
    admin_instance.message_user = lambda _request, message: messages.append(message)

    MapRequestAdminEnhanced.mark_as_completed(admin_instance, None, [request])

    assert finalized == [request]
    assert messages == ["没有请求通过成果校验，未标记为已完成"]
