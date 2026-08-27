from pathlib import Path

from PIL import Image

from mapping.finalization import LayerValidation, finalize_execution


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


def test_finalizer_preserves_clarification_as_terminal_decision(tmp_path):
    result = finalize_execution(
        required_roles={"boundary"},
        layers=[],
        png_path=None,
        trace_id="trace-4",
        clarification_required=True,
    )

    assert result.status == "needs_clarification"
