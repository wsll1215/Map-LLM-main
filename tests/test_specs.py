from gis_mapping_agent.specs import AdjustmentPatch, GeneralizationSpec, MapSpec, PatchOperation


def test_specs_roundtrip():
    map_spec = MapSpec(
        title="Road map",
        extent=[0, 0, 1, 1],
        data_files=["roads.shp"],
        layer_styles={"roads": {"color": "red"}},
    )
    assert MapSpec.model_validate(map_spec.model_dump()).title == "Road map"

    gen_spec = GeneralizationSpec(
        data_file="roads.shp",
        algorithm="stroke",
        source_scale=500,
        target_scale=2000,
        keep_ratio=0.4,
    )
    assert GeneralizationSpec.model_validate(gen_spec.model_dump()).keep_ratio == 0.4

    patch = AdjustmentPatch(
        session_id="s1",
        operations=[PatchOperation(action="style_layer", target="roads", parameters={"color": "blue"})],
    )
    assert AdjustmentPatch.model_validate(patch.model_dump()).operations[0].target == "roads"
