from types import SimpleNamespace

import pytest

from mapping.realtime import _build_payload, _effective_render_mode
from mapping.rest_api import _effective_render_mode as rest_effective_render_mode


@pytest.mark.parametrize(
    ("feature_count", "expected"),
    [
        (7999, "geojson"),
        (8000, "geojson"),
        (8001, "geojson-worker"),
        (30001, "mvt"),
    ],
)
def test_render_mode_threshold_is_consistent_in_realtime_and_rest(
    feature_count, expected
):
    layer = SimpleNamespace(feature_count=feature_count, render_mode="geojson")

    assert _effective_render_mode(layer) == expected
    assert rest_effective_render_mode(layer) == expected


def test_map_events_send_versions_and_metadata_without_geojson():
    layer = SimpleNamespace(
        layer_id="roads",
        name="Roads",
        geometry_type="line",
        visible=True,
        z_order=0,
        data_source="data/roads.shp",
        data_hash="sha256:roads",
        feature_count=10,
        extent=[115, 39, 117, 41],
        render_mode="geojson",
        data_url="/layers/roads/",
        style=SimpleNamespace(model_dump=lambda: {"color": "#333"}),
        gdf=None,
    )
    map_state = SimpleNamespace(
        config=SimpleNamespace(
            title="Beijing",
            extent=[115, 39, 117, 41],
            crs="EPSG:4326",
            background_color="white",
        ),
        version_info=SimpleNamespace(version=3),
        layers=[layer],
        legend_items=[],
        legends=[],
        annotations=[],
        scalebar=None,
        compass=None,
        output_path=None,
    )

    payload = _build_payload(
        request_id=7,
        session_id="web_session_7",
        iteration=1,
        tool_name="add_layer",
        tool_input={},
        observation="layer added",
        map_state=map_state,
    )

    assert payload["map_version"] == 3
    assert payload["layer"]["feature_count"] == 10
    assert "geojson" not in payload["layer"]
    assert "geojson" not in payload["view_state"]["layers"][0]


def test_unregistered_cache_path_does_not_define_runtime_source_type():
    layer = SimpleNamespace(
        layer_id="unregistered",
        name="道路",
        geometry_type="line",
        visible=True,
        z_order=0,
        data_source="data_cache/remote_roads/road.geojson",
        data_source_meta={},
        data_hash=None,
        feature_count=1,
        extent=[120, 30, 121, 31],
        render_mode="geojson",
        data_url=None,
        style=SimpleNamespace(model_dump=lambda: {}),
    )
    payload = _build_payload(
        request_id=1,
        session_id="web_session_1",
        iteration=1,
        tool_name="add_layer",
        tool_input={},
        observation="ok",
        map_state=SimpleNamespace(
            config=SimpleNamespace(extent=[120, 30, 121, 31]),
            version_info=None,
            layers=[layer],
            legend_items=[],
            legends=[],
            annotations=[],
            scalebar=None,
            compass=None,
            output_path=None,
        ),
    )

    assert payload["layer"]["data_source_meta"]["source_type"] is None


def test_preview_publication_closes_one_render_span(monkeypatch):
    from mapping import realtime

    events = []
    span = SimpleNamespace(
        event_id="render-span-1",
        request_id=7,
        run_id=3,
        event_type="render",
        phase="render",
        status="running",
        input_data={},
        output_data={},
        attributes={},
        error=None,
    )

    monkeypatch.setattr(realtime, "_save_matplotlib_preview", lambda **_: {
        "image_url": "/generated_maps/preview.png",
        "version": 2,
    })
    monkeypatch.setattr(
        "mapping.trace.run_for_session",
        lambda _session_id: SimpleNamespace(id=3, request_id=7),
    )
    monkeypatch.setattr(
        "mapping.trace.start_trace_event",
        lambda **kwargs: events.append(("start", kwargs)) or span,
    )
    monkeypatch.setattr(
        "mapping.trace.finish_trace_event",
        lambda event, **kwargs: events.append(("finish", event.event_id, kwargs)) or event,
    )
    monkeypatch.setattr(
        "mapping.trace.publish_trace_lifecycle",
        lambda event, lifecycle: events.append(("lifecycle", event.event_id, lifecycle)),
    )
    monkeypatch.setattr("mapping.trace.publish_trace_event", lambda event: events.append(("trace", event.event_id)))
    monkeypatch.setattr(realtime, "publish_map_build_event", lambda *_args, **_kwargs: "1")

    realtime.publish_agent_map_event(
        session_id="web_session_7",
        iteration=2,
        tool_name="add_layer",
        tool_input={"name": "roads"},
        observation="layer added",
        map_state=SimpleNamespace(layers=[]),
        map_tools=SimpleNamespace(),
    )

    lifecycle = [item[2] for item in events if item[0] == "lifecycle"]
    assert lifecycle == ["render_started", "render_finished"]
    assert [item[1] for item in events if item[0] == "lifecycle"] == [
        "render-span-1",
        "render-span-1",
    ]
    finish = next(item for item in events if item[0] == "finish")
    assert finish[2]["output_data"]["preview"]["version"] == 2
