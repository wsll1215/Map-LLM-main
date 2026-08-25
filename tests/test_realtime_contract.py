from types import SimpleNamespace

from mapping.realtime import _build_payload


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
