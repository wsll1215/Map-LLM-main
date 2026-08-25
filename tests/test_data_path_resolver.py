from gis_mapping_agent.utils.data_path_resolver import DataPathResolver


def test_beijing_request_resolves_to_data8() -> None:
    resolver = DataPathResolver()

    assert resolver.parse_data_directory_from_request("给我绘制北京的地图") == "data8"


def test_wuhan_request_resolves_to_data2() -> None:
    resolver = DataPathResolver()

    assert resolver.parse_data_directory_from_request("请绘制武汉市行政区划图") == "data2"


def test_explicit_data_directory_takes_precedence_over_location() -> None:
    resolver = DataPathResolver()

    assert resolver.parse_data_directory_from_request("使用 data1 中的数据绘制北京地图") == "data1"


def test_location_request_selects_existing_default_shapefile() -> None:
    resolver = DataPathResolver()

    data_directory, data_files = resolver.extract_data_info("给我绘制北京的地图")

    assert data_directory == "data8"
    assert data_files == ["Beijing.shp"]


def test_wuhan_request_selects_existing_default_shapefile() -> None:
    resolver = DataPathResolver()

    data_directory, data_files = resolver.extract_data_info("请绘制武汉市行政区划图")

    assert data_directory == "data2"
    assert data_files == ["Wuhan.shp"]


def test_absolute_data_directory_is_not_joined_to_project_data_root(tmp_path) -> None:
    resolver = DataPathResolver()

    assert resolver.resolve_data_path(str(tmp_path)) == tmp_path.resolve()
