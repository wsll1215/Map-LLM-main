from gis_mapping_agent.specs import LayerManifest, MapSpec


def test_map_spec_accepts_canonical_render_contract() -> None:
    spec = MapSpec.model_validate(
        {
            "schema_version": 1,
            "map_id": "map-23",
            "version": 4,
            "title": "北京市行政区划图",
            "crs": "EPSG:4326",
            "display_crs": "EPSG:3857",
            "extent": [115.4, 39.4, 117.5, 41.1],
            "layers": [
                {
                    "id": "beijing-boundary",
                    "name": "北京市行政区划",
                    "geometry_type": "Polygon",
                    "style": {
                        "fill": "#dcefe4",
                        "stroke": "#166534",
                        "stroke_width": 2,
                        "opacity": 0.9,
                    },
                    "visible": True,
                    "z_index": 10,
                }
            ],
        }
    )

    assert spec.schema_version == 1
    assert spec.version == 4
    assert spec.display_crs == "EPSG:3857"
    assert spec.layers[0].style.stroke == "#166534"


def test_layer_manifest_rejects_unknown_render_mode() -> None:
    try:
        LayerManifest.model_validate(
            {
                "id": "roads",
                "version": 1,
                "name": "道路",
                "geometry_type": "LineString",
                "feature_count": 100,
                "render_mode": "canvas",
            }
        )
    except ValueError as error:
        assert "render_mode" in str(error)
    else:
        raise AssertionError("unknown render mode should be rejected")
