# GeoJSON 渲染 A/B 性能报告

> 本报告只接受实际浏览器采样结果，不预填性能数字。

- 生成时间：`2026-08-28T03:53:51.809673+00:00`
- 数据：固定 seed 的合成 LineString GeoJSON
- A：强制主线程直载基线；B：按规模选择 direct/worker/mvt
- 统计：每个场景应预热 5 次、正式采样 30 次，报告 median 和 P95
- 可交互定义：地图完成绘制，并成功响应一次拖动事件
- 每条观测同时保存 strategy、geometry_type、coordinate_count、geojson_bytes、bbox 和 seed

## 场景覆盖

| scenario | variant | feature_count | strategy | sample_count | status |
| --- | --- | ---: | --- | ---: | --- |
| direct-4999 | A | 4999 | direct | 1 | 已采集 |
| direct-4999 | B | 4999 | direct | 1 | 已采集 |
| direct-5000 | A | 5000 | direct | 1 | 已采集 |
| direct-5000 | B | 5000 | direct | 1 | 已采集 |
| worker-5001 | A | 5001 | direct | 1 | 已采集 |
| worker-5001 | B | 5001 | worker | 1 | 已采集 |
| worker-10000 | A | 10000 | direct | 1 | 已采集 |
| worker-10000 | B | 10000 | worker | 1 | 已采集 |
| worker-29999 | A | 29999 | direct | 1 | 已采集 |
| worker-29999 | B | 29999 | worker | 1 | 已采集 |
| worker-30000 | A | 30000 | direct | 1 | 已采集 |
| worker-30000 | B | 30000 | worker | 1 | 已采集 |
| mvt-30001 | A | 30001 | direct | 1 | 已采集 |
| mvt-30001 | B | 30001 | mvt | 1 | 已采集 |

## 统计汇总

| scenario | variant | sample_count | median_interactive_ms | p95_interactive_ms | render_success_rate | feature_count_match_rate | extent_match_rate |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| direct-4999 | A | 1 | 291.89999997615814 | 291.89999997615814 | 1.0 | 1.0 | 1.0 |
| direct-4999 | B | 1 | 270.59999990463257 | 270.59999990463257 | 1.0 | 1.0 | 1.0 |
| direct-5000 | A | 1 | 349.7000000476837 | 349.7000000476837 | 1.0 | 1.0 | 1.0 |
| direct-5000 | B | 1 | 337.09999990463257 | 337.09999990463257 | 1.0 | 1.0 | 1.0 |
| worker-5001 | A | 1 | 293.7000000476837 | 293.7000000476837 | 1.0 | 1.0 | 1.0 |
| worker-5001 | B | 1 | 295.5 | 295.5 | 1.0 | 1.0 | 1.0 |
| worker-10000 | A | 1 | 389.5 | 389.5 | 1.0 | 1.0 | 1.0 |
| worker-10000 | B | 1 | 465.8000000715256 | 465.8000000715256 | 1.0 | 1.0 | 1.0 |
| worker-29999 | A | 1 | 1141.0999999046326 | 1141.0999999046326 | 1.0 | 1.0 | 1.0 |
| worker-29999 | B | 1 | 674.7999999523163 | 674.7999999523163 | 1.0 | 1.0 | 1.0 |
| worker-30000 | A | 1 | 1069.8999999761581 | 1069.8999999761581 | 1.0 | 1.0 | 1.0 |
| worker-30000 | B | 1 | 798.0 | 798.0 | 1.0 | 1.0 | 1.0 |
| mvt-30001 | A | 1 | 1078.6999999284744 | 1078.6999999284744 | 1.0 | 1.0 | 1.0 |
| mvt-30001 | B | 1 | 751.2000000476837 | 751.2000000476837 | 1.0 | 1.0 | 1.0 |

## A/B 变化

> 变化率为 B 相对 A 的 median：正数表示 B 更慢，负数表示 B 更快。没有两组真实样本时不生成比较行。

| scenario | metric | B 相对 A |
| --- | --- | ---: |
| direct-4999 | first_visible_ms | -9.7% |
| direct-4999 | interactive_ms | -7.3% |
| direct-4999 | long_task_ms | -2.8% |
| direct-5000 | first_visible_ms | -4.5% |
| direct-5000 | interactive_ms | -3.6% |
| direct-5000 | long_task_ms | 12.8% |
| worker-5001 | first_visible_ms | -33.7% |
| worker-5001 | interactive_ms | 0.6% |
| worker-5001 | long_task_ms | -28.9% |
| worker-10000 | first_visible_ms | -20.8% |
| worker-10000 | interactive_ms | 19.6% |
| worker-10000 | long_task_ms | -42.2% |
| worker-29999 | first_visible_ms | -41.9% |
| worker-29999 | interactive_ms | -40.9% |
| worker-29999 | long_task_ms | -58.1% |
| worker-30000 | first_visible_ms | -29.7% |
| worker-30000 | interactive_ms | -25.4% |
| worker-30000 | long_task_ms | -52.3% |
| mvt-30001 | first_visible_ms | -51.8% |
| mvt-30001 | interactive_ms | -30.4% |
| mvt-30001 | long_task_ms | -64.8% |

## 正确性字段

每次采样必须同时记录 `render_success`、`feature_count_match` 和 `extent_match`；
任何正确性字段不满足时，该样本不能作为成功性能结果解释。

## 汇总结果

将真实采样结果写入后，以下字段由生成器计算：`median`、`p95`、
`render_success_rate`、`feature_count_match_rate`、`extent_match_rate`。

## 原始观测 JSON

```json
{
  "observations": [
    {
      "scenario": "direct-4999",
      "variant": "A",
      "feature_count": 4999,
      "fetch_ms": 73.39999997615814,
      "parse_ms": 7.700000047683716,
      "render_ms": 45.799999952316284,
      "interactive_ms": 291.89999997615814,
      "long_task_ms": 281.0,
      "pointer_delay_ms": 0.8999999761581421,
      "memory_delta_bytes": 38707365.0,
      "render_success": true,
      "feature_count_match": true,
      "extent_match": true,
      "worker_process_ms": 0.0,
      "feature_convert_ms": 28.0,
      "first_visible_ms": 183.89999997615814,
      "strategy": "direct",
      "geometry_type": "LineString",
      "coordinate_count": 14997,
      "geojson_bytes": 1192107,
      "bbox": [
        116.0,
        39.8,
        116.8,
        40.4
      ],
      "seed": 20260827,
      "correctness_scope": "full_dataset"
    },
    {
      "scenario": "direct-4999",
      "variant": "B",
      "feature_count": 4999,
      "fetch_ms": 68.79999995231628,
      "parse_ms": 7.600000023841858,
      "render_ms": 40.199999928474426,
      "interactive_ms": 270.59999990463257,
      "long_task_ms": 273.0,
      "pointer_delay_ms": 1.0,
      "memory_delta_bytes": 38717941.0,
      "render_success": true,
      "feature_count_match": true,
      "extent_match": true,
      "worker_process_ms": 0.0,
      "feature_convert_ms": 24.199999928474426,
      "first_visible_ms": 166.09999990463257,
      "strategy": "direct",
      "geometry_type": "LineString",
      "coordinate_count": 14997,
      "geojson_bytes": 1192107,
      "bbox": [
        116.0,
        39.8,
        116.8,
        40.4
      ],
      "seed": 20260827,
      "correctness_scope": "full_dataset"
    },
    {
      "scenario": "direct-5000",
      "variant": "A",
      "feature_count": 5000,
      "fetch_ms": 82.89999997615814,
      "parse_ms": 8.200000047683716,
      "render_ms": 61.799999952316284,
      "interactive_ms": 349.7000000476837,
      "long_task_ms": 352.0,
      "pointer_delay_ms": 1.2999999523162842,
      "memory_delta_bytes": 38696369.0,
      "render_success": true,
      "feature_count_match": true,
      "extent_match": true,
      "worker_process_ms": 0.0,
      "feature_convert_ms": 27.09999990463257,
      "first_visible_ms": 212.10000002384186,
      "strategy": "direct",
      "geometry_type": "LineString",
      "coordinate_count": 15000,
      "geojson_bytes": 1192345,
      "bbox": [
        116.0,
        39.8,
        116.8,
        40.4
      ],
      "seed": 20260827,
      "correctness_scope": "full_dataset"
    },
    {
      "scenario": "direct-5000",
      "variant": "B",
      "feature_count": 5000,
      "fetch_ms": 79.19999992847443,
      "parse_ms": 8.799999952316284,
      "render_ms": 50.699999928474426,
      "interactive_ms": 337.09999990463257,
      "long_task_ms": 397.0,
      "pointer_delay_ms": 1.100000023841858,
      "memory_delta_bytes": 38930545.0,
      "render_success": true,
      "feature_count_match": true,
      "extent_match": true,
      "worker_process_ms": 0.0,
      "feature_convert_ms": 31.399999976158142,
      "first_visible_ms": 202.5,
      "strategy": "direct",
      "geometry_type": "LineString",
      "coordinate_count": 15000,
      "geojson_bytes": 1192345,
      "bbox": [
        116.0,
        39.8,
        116.8,
        40.4
      ],
      "seed": 20260827,
      "correctness_scope": "full_dataset"
    },
    {
      "scenario": "worker-5001",
      "variant": "A",
      "feature_count": 5001,
      "fetch_ms": 81.20000004768372,
      "parse_ms": 8.300000071525574,
      "render_ms": 42.60000002384186,
      "interactive_ms": 293.7000000476837,
      "long_task_ms": 305.0,
      "pointer_delay_ms": 17.5,
      "memory_delta_bytes": 38736353.0,
      "render_success": true,
      "feature_count_match": true,
      "extent_match": true,
      "worker_process_ms": 0.0,
      "feature_convert_ms": 26.399999976158142,
      "first_visible_ms": 187.80000007152557,
      "strategy": "direct",
      "geometry_type": "LineString",
      "coordinate_count": 15003,
      "geojson_bytes": 1192583,
      "bbox": [
        116.0,
        39.8,
        116.8,
        40.4
      ],
      "seed": 20260827,
      "correctness_scope": "full_dataset"
    },
    {
      "scenario": "worker-5001",
      "variant": "B",
      "feature_count": 5001,
      "fetch_ms": 66.89999997615814,
      "parse_ms": 0.0,
      "render_ms": 23.600000023841858,
      "interactive_ms": 295.5,
      "long_task_ms": 217.0,
      "pointer_delay_ms": 11.0,
      "memory_delta_bytes": 36974904.0,
      "render_success": true,
      "feature_count_match": true,
      "extent_match": true,
      "worker_process_ms": 64.89999997615814,
      "feature_convert_ms": 5.899999976158142,
      "first_visible_ms": 124.5,
      "strategy": "worker",
      "geometry_type": "LineString",
      "coordinate_count": 15003,
      "geojson_bytes": 1192583,
      "bbox": [
        116.0,
        39.8,
        116.8,
        40.4
      ],
      "seed": 20260827,
      "correctness_scope": "full_dataset"
    },
    {
      "scenario": "worker-10000",
      "variant": "A",
      "feature_count": 10000,
      "fetch_ms": 116.70000004768372,
      "parse_ms": 14.600000023841858,
      "render_ms": 57.10000002384186,
      "interactive_ms": 389.5,
      "long_task_ms": 386.0,
      "pointer_delay_ms": 1.100000023841858,
      "memory_delta_bytes": 48583863.0,
      "render_success": true,
      "feature_count_match": true,
      "extent_match": true,
      "worker_process_ms": 0.0,
      "feature_convert_ms": 49.799999952316284,
      "first_visible_ms": 283.40000009536743,
      "strategy": "direct",
      "geometry_type": "LineString",
      "coordinate_count": 30000,
      "geojson_bytes": 2386690,
      "bbox": [
        116.0,
        39.8,
        116.8,
        40.4
      ],
      "seed": 20260827,
      "correctness_scope": "full_dataset"
    },
    {
      "scenario": "worker-10000",
      "variant": "B",
      "feature_count": 10000,
      "fetch_ms": 132.40000009536743,
      "parse_ms": 0.0,
      "render_ms": 32.0,
      "interactive_ms": 465.8000000715256,
      "long_task_ms": 223.0,
      "pointer_delay_ms": 4.400000095367432,
      "memory_delta_bytes": 64413686.0,
      "render_success": true,
      "feature_count_match": true,
      "extent_match": true,
      "worker_process_ms": 156.79999995231628,
      "feature_convert_ms": 7.700000047683716,
      "first_visible_ms": 224.5,
      "strategy": "worker",
      "geometry_type": "LineString",
      "coordinate_count": 30000,
      "geojson_bytes": 2386690,
      "bbox": [
        116.0,
        39.8,
        116.8,
        40.4
      ],
      "seed": 20260827,
      "correctness_scope": "full_dataset"
    },
    {
      "scenario": "worker-29999",
      "variant": "A",
      "feature_count": 29999,
      "fetch_ms": 310.2999999523163,
      "parse_ms": 55.60000002384186,
      "render_ms": 177.80000007152557,
      "interactive_ms": 1141.0999999046326,
      "long_task_ms": 702.0,
      "pointer_delay_ms": 0.0,
      "memory_delta_bytes": 110607757.0,
      "render_success": true,
      "feature_count_match": true,
      "extent_match": true,
      "worker_process_ms": 0.0,
      "feature_convert_ms": 131.29999995231628,
      "first_visible_ms": 800.0,
      "strategy": "direct",
      "geometry_type": "LineString",
      "coordinate_count": 89997,
      "geojson_bytes": 7203916,
      "bbox": [
        116.0,
        39.8,
        116.8,
        40.4
      ],
      "seed": 20260827,
      "correctness_scope": "full_dataset"
    },
    {
      "scenario": "worker-29999",
      "variant": "B",
      "feature_count": 29999,
      "fetch_ms": 334.1999999284744,
      "parse_ms": 0.0,
      "render_ms": 31.09999990463257,
      "interactive_ms": 674.7999999523163,
      "long_task_ms": 294.0,
      "pointer_delay_ms": 2.4000000953674316,
      "memory_delta_bytes": 119262777.0,
      "render_success": true,
      "feature_count_match": true,
      "extent_match": true,
      "worker_process_ms": 423.5,
      "feature_convert_ms": 7.299999952316284,
      "first_visible_ms": 464.5,
      "strategy": "worker",
      "geometry_type": "LineString",
      "coordinate_count": 89997,
      "geojson_bytes": 7203916,
      "bbox": [
        116.0,
        39.8,
        116.8,
        40.4
      ],
      "seed": 20260827,
      "correctness_scope": "full_dataset"
    },
    {
      "scenario": "worker-30000",
      "variant": "A",
      "feature_count": 30000,
      "fetch_ms": 293.2000000476837,
      "parse_ms": 55.59999990463257,
      "render_ms": 160.29999995231628,
      "interactive_ms": 1069.8999999761581,
      "long_task_ms": 664.0,
      "pointer_delay_ms": 0.0,
      "memory_delta_bytes": 110885366.0,
      "render_success": true,
      "feature_count_match": true,
      "extent_match": true,
      "worker_process_ms": 0.0,
      "feature_convert_ms": 126.89999997615814,
      "first_visible_ms": 753.8999999761581,
      "strategy": "direct",
      "geometry_type": "LineString",
      "coordinate_count": 90000,
      "geojson_bytes": 7204157,
      "bbox": [
        116.0,
        39.8,
        116.8,
        40.4
      ],
      "seed": 20260827,
      "correctness_scope": "full_dataset"
    },
    {
      "scenario": "worker-30000",
      "variant": "B",
      "feature_count": 30000,
      "fetch_ms": 356.39999997615814,
      "parse_ms": 0.0,
      "render_ms": 50.10000002384186,
      "interactive_ms": 798.0,
      "long_task_ms": 317.0,
      "pointer_delay_ms": 3.799999952316284,
      "memory_delta_bytes": 90796741.0,
      "render_success": true,
      "feature_count_match": true,
      "extent_match": true,
      "worker_process_ms": 462.7999999523163,
      "feature_convert_ms": 12.600000023841858,
      "first_visible_ms": 529.6999999284744,
      "strategy": "worker",
      "geometry_type": "LineString",
      "coordinate_count": 90000,
      "geojson_bytes": 7204157,
      "bbox": [
        116.0,
        39.8,
        116.8,
        40.4
      ],
      "seed": 20260827,
      "correctness_scope": "full_dataset"
    },
    {
      "scenario": "mvt-30001",
      "variant": "A",
      "feature_count": 30001,
      "fetch_ms": 309.6999999284744,
      "parse_ms": 54.0,
      "render_ms": 171.79999995231628,
      "interactive_ms": 1078.6999999284744,
      "long_task_ms": 679.0,
      "pointer_delay_ms": 0.0,
      "memory_delta_bytes": 102405290.0,
      "render_success": true,
      "feature_count_match": true,
      "extent_match": true,
      "worker_process_ms": 0.0,
      "feature_convert_ms": 115.10000002384186,
      "first_visible_ms": 764.1999999284744,
      "strategy": "direct",
      "geometry_type": "LineString",
      "coordinate_count": 90003,
      "geojson_bytes": 7204397,
      "bbox": [
        116.0,
        39.8,
        116.8,
        40.4
      ],
      "seed": 20260827,
      "correctness_scope": "full_dataset"
    },
    {
      "scenario": "mvt-30001",
      "variant": "B",
      "feature_count": 30001,
      "fetch_ms": 358.7999999523163,
      "parse_ms": 0.0,
      "render_ms": 368.8000000715256,
      "interactive_ms": 751.2000000476837,
      "long_task_ms": 239.0,
      "pointer_delay_ms": 0.0,
      "memory_delta_bytes": 24128121.0,
      "render_success": true,
      "feature_count_match": true,
      "extent_match": true,
      "worker_process_ms": 0.0,
      "feature_convert_ms": 0.0,
      "first_visible_ms": 368.10000002384186,
      "strategy": "mvt",
      "geometry_type": "LineString",
      "coordinate_count": 90003,
      "geojson_bytes": 7204397,
      "bbox": [
        116.0,
        39.8,
        116.8,
        40.4
      ],
      "seed": 20260827,
      "correctness_scope": "visible_tiles"
    }
  ],
  "summaries": {
    "direct-4999": {
      "A": {
        "sample_count": 1,
        "median": {
          "fetch_ms": 73.39999997615814,
          "parse_ms": 7.700000047683716,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 28.0,
          "render_ms": 45.799999952316284,
          "first_visible_ms": 183.89999997615814,
          "interactive_ms": 291.89999997615814,
          "long_task_ms": 281.0,
          "pointer_delay_ms": 0.8999999761581421,
          "memory_delta_bytes": 38707365.0
        },
        "p95": {
          "fetch_ms": 73.39999997615814,
          "parse_ms": 7.700000047683716,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 28.0,
          "render_ms": 45.799999952316284,
          "first_visible_ms": 183.89999997615814,
          "interactive_ms": 291.89999997615814,
          "long_task_ms": 281.0,
          "pointer_delay_ms": 0.8999999761581421,
          "memory_delta_bytes": 38707365.0
        },
        "correctness": {
          "render_success_rate": 1.0,
          "feature_count_match_rate": 1.0,
          "extent_match_rate": 1.0
        }
      },
      "B": {
        "sample_count": 1,
        "median": {
          "fetch_ms": 68.79999995231628,
          "parse_ms": 7.600000023841858,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 24.199999928474426,
          "render_ms": 40.199999928474426,
          "first_visible_ms": 166.09999990463257,
          "interactive_ms": 270.59999990463257,
          "long_task_ms": 273.0,
          "pointer_delay_ms": 1.0,
          "memory_delta_bytes": 38717941.0
        },
        "p95": {
          "fetch_ms": 68.79999995231628,
          "parse_ms": 7.600000023841858,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 24.199999928474426,
          "render_ms": 40.199999928474426,
          "first_visible_ms": 166.09999990463257,
          "interactive_ms": 270.59999990463257,
          "long_task_ms": 273.0,
          "pointer_delay_ms": 1.0,
          "memory_delta_bytes": 38717941.0
        },
        "correctness": {
          "render_success_rate": 1.0,
          "feature_count_match_rate": 1.0,
          "extent_match_rate": 1.0
        }
      }
    },
    "direct-5000": {
      "A": {
        "sample_count": 1,
        "median": {
          "fetch_ms": 82.89999997615814,
          "parse_ms": 8.200000047683716,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 27.09999990463257,
          "render_ms": 61.799999952316284,
          "first_visible_ms": 212.10000002384186,
          "interactive_ms": 349.7000000476837,
          "long_task_ms": 352.0,
          "pointer_delay_ms": 1.2999999523162842,
          "memory_delta_bytes": 38696369.0
        },
        "p95": {
          "fetch_ms": 82.89999997615814,
          "parse_ms": 8.200000047683716,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 27.09999990463257,
          "render_ms": 61.799999952316284,
          "first_visible_ms": 212.10000002384186,
          "interactive_ms": 349.7000000476837,
          "long_task_ms": 352.0,
          "pointer_delay_ms": 1.2999999523162842,
          "memory_delta_bytes": 38696369.0
        },
        "correctness": {
          "render_success_rate": 1.0,
          "feature_count_match_rate": 1.0,
          "extent_match_rate": 1.0
        }
      },
      "B": {
        "sample_count": 1,
        "median": {
          "fetch_ms": 79.19999992847443,
          "parse_ms": 8.799999952316284,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 31.399999976158142,
          "render_ms": 50.699999928474426,
          "first_visible_ms": 202.5,
          "interactive_ms": 337.09999990463257,
          "long_task_ms": 397.0,
          "pointer_delay_ms": 1.100000023841858,
          "memory_delta_bytes": 38930545.0
        },
        "p95": {
          "fetch_ms": 79.19999992847443,
          "parse_ms": 8.799999952316284,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 31.399999976158142,
          "render_ms": 50.699999928474426,
          "first_visible_ms": 202.5,
          "interactive_ms": 337.09999990463257,
          "long_task_ms": 397.0,
          "pointer_delay_ms": 1.100000023841858,
          "memory_delta_bytes": 38930545.0
        },
        "correctness": {
          "render_success_rate": 1.0,
          "feature_count_match_rate": 1.0,
          "extent_match_rate": 1.0
        }
      }
    },
    "worker-5001": {
      "A": {
        "sample_count": 1,
        "median": {
          "fetch_ms": 81.20000004768372,
          "parse_ms": 8.300000071525574,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 26.399999976158142,
          "render_ms": 42.60000002384186,
          "first_visible_ms": 187.80000007152557,
          "interactive_ms": 293.7000000476837,
          "long_task_ms": 305.0,
          "pointer_delay_ms": 17.5,
          "memory_delta_bytes": 38736353.0
        },
        "p95": {
          "fetch_ms": 81.20000004768372,
          "parse_ms": 8.300000071525574,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 26.399999976158142,
          "render_ms": 42.60000002384186,
          "first_visible_ms": 187.80000007152557,
          "interactive_ms": 293.7000000476837,
          "long_task_ms": 305.0,
          "pointer_delay_ms": 17.5,
          "memory_delta_bytes": 38736353.0
        },
        "correctness": {
          "render_success_rate": 1.0,
          "feature_count_match_rate": 1.0,
          "extent_match_rate": 1.0
        }
      },
      "B": {
        "sample_count": 1,
        "median": {
          "fetch_ms": 66.89999997615814,
          "parse_ms": 0.0,
          "worker_process_ms": 64.89999997615814,
          "feature_convert_ms": 5.899999976158142,
          "render_ms": 23.600000023841858,
          "first_visible_ms": 124.5,
          "interactive_ms": 295.5,
          "long_task_ms": 217.0,
          "pointer_delay_ms": 11.0,
          "memory_delta_bytes": 36974904.0
        },
        "p95": {
          "fetch_ms": 66.89999997615814,
          "parse_ms": 0.0,
          "worker_process_ms": 64.89999997615814,
          "feature_convert_ms": 5.899999976158142,
          "render_ms": 23.600000023841858,
          "first_visible_ms": 124.5,
          "interactive_ms": 295.5,
          "long_task_ms": 217.0,
          "pointer_delay_ms": 11.0,
          "memory_delta_bytes": 36974904.0
        },
        "correctness": {
          "render_success_rate": 1.0,
          "feature_count_match_rate": 1.0,
          "extent_match_rate": 1.0
        }
      }
    },
    "worker-10000": {
      "A": {
        "sample_count": 1,
        "median": {
          "fetch_ms": 116.70000004768372,
          "parse_ms": 14.600000023841858,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 49.799999952316284,
          "render_ms": 57.10000002384186,
          "first_visible_ms": 283.40000009536743,
          "interactive_ms": 389.5,
          "long_task_ms": 386.0,
          "pointer_delay_ms": 1.100000023841858,
          "memory_delta_bytes": 48583863.0
        },
        "p95": {
          "fetch_ms": 116.70000004768372,
          "parse_ms": 14.600000023841858,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 49.799999952316284,
          "render_ms": 57.10000002384186,
          "first_visible_ms": 283.40000009536743,
          "interactive_ms": 389.5,
          "long_task_ms": 386.0,
          "pointer_delay_ms": 1.100000023841858,
          "memory_delta_bytes": 48583863.0
        },
        "correctness": {
          "render_success_rate": 1.0,
          "feature_count_match_rate": 1.0,
          "extent_match_rate": 1.0
        }
      },
      "B": {
        "sample_count": 1,
        "median": {
          "fetch_ms": 132.40000009536743,
          "parse_ms": 0.0,
          "worker_process_ms": 156.79999995231628,
          "feature_convert_ms": 7.700000047683716,
          "render_ms": 32.0,
          "first_visible_ms": 224.5,
          "interactive_ms": 465.8000000715256,
          "long_task_ms": 223.0,
          "pointer_delay_ms": 4.400000095367432,
          "memory_delta_bytes": 64413686.0
        },
        "p95": {
          "fetch_ms": 132.40000009536743,
          "parse_ms": 0.0,
          "worker_process_ms": 156.79999995231628,
          "feature_convert_ms": 7.700000047683716,
          "render_ms": 32.0,
          "first_visible_ms": 224.5,
          "interactive_ms": 465.8000000715256,
          "long_task_ms": 223.0,
          "pointer_delay_ms": 4.400000095367432,
          "memory_delta_bytes": 64413686.0
        },
        "correctness": {
          "render_success_rate": 1.0,
          "feature_count_match_rate": 1.0,
          "extent_match_rate": 1.0
        }
      }
    },
    "worker-29999": {
      "A": {
        "sample_count": 1,
        "median": {
          "fetch_ms": 310.2999999523163,
          "parse_ms": 55.60000002384186,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 131.29999995231628,
          "render_ms": 177.80000007152557,
          "first_visible_ms": 800.0,
          "interactive_ms": 1141.0999999046326,
          "long_task_ms": 702.0,
          "pointer_delay_ms": 0.0,
          "memory_delta_bytes": 110607757.0
        },
        "p95": {
          "fetch_ms": 310.2999999523163,
          "parse_ms": 55.60000002384186,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 131.29999995231628,
          "render_ms": 177.80000007152557,
          "first_visible_ms": 800.0,
          "interactive_ms": 1141.0999999046326,
          "long_task_ms": 702.0,
          "pointer_delay_ms": 0.0,
          "memory_delta_bytes": 110607757.0
        },
        "correctness": {
          "render_success_rate": 1.0,
          "feature_count_match_rate": 1.0,
          "extent_match_rate": 1.0
        }
      },
      "B": {
        "sample_count": 1,
        "median": {
          "fetch_ms": 334.1999999284744,
          "parse_ms": 0.0,
          "worker_process_ms": 423.5,
          "feature_convert_ms": 7.299999952316284,
          "render_ms": 31.09999990463257,
          "first_visible_ms": 464.5,
          "interactive_ms": 674.7999999523163,
          "long_task_ms": 294.0,
          "pointer_delay_ms": 2.4000000953674316,
          "memory_delta_bytes": 119262777.0
        },
        "p95": {
          "fetch_ms": 334.1999999284744,
          "parse_ms": 0.0,
          "worker_process_ms": 423.5,
          "feature_convert_ms": 7.299999952316284,
          "render_ms": 31.09999990463257,
          "first_visible_ms": 464.5,
          "interactive_ms": 674.7999999523163,
          "long_task_ms": 294.0,
          "pointer_delay_ms": 2.4000000953674316,
          "memory_delta_bytes": 119262777.0
        },
        "correctness": {
          "render_success_rate": 1.0,
          "feature_count_match_rate": 1.0,
          "extent_match_rate": 1.0
        }
      }
    },
    "worker-30000": {
      "A": {
        "sample_count": 1,
        "median": {
          "fetch_ms": 293.2000000476837,
          "parse_ms": 55.59999990463257,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 126.89999997615814,
          "render_ms": 160.29999995231628,
          "first_visible_ms": 753.8999999761581,
          "interactive_ms": 1069.8999999761581,
          "long_task_ms": 664.0,
          "pointer_delay_ms": 0.0,
          "memory_delta_bytes": 110885366.0
        },
        "p95": {
          "fetch_ms": 293.2000000476837,
          "parse_ms": 55.59999990463257,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 126.89999997615814,
          "render_ms": 160.29999995231628,
          "first_visible_ms": 753.8999999761581,
          "interactive_ms": 1069.8999999761581,
          "long_task_ms": 664.0,
          "pointer_delay_ms": 0.0,
          "memory_delta_bytes": 110885366.0
        },
        "correctness": {
          "render_success_rate": 1.0,
          "feature_count_match_rate": 1.0,
          "extent_match_rate": 1.0
        }
      },
      "B": {
        "sample_count": 1,
        "median": {
          "fetch_ms": 356.39999997615814,
          "parse_ms": 0.0,
          "worker_process_ms": 462.7999999523163,
          "feature_convert_ms": 12.600000023841858,
          "render_ms": 50.10000002384186,
          "first_visible_ms": 529.6999999284744,
          "interactive_ms": 798.0,
          "long_task_ms": 317.0,
          "pointer_delay_ms": 3.799999952316284,
          "memory_delta_bytes": 90796741.0
        },
        "p95": {
          "fetch_ms": 356.39999997615814,
          "parse_ms": 0.0,
          "worker_process_ms": 462.7999999523163,
          "feature_convert_ms": 12.600000023841858,
          "render_ms": 50.10000002384186,
          "first_visible_ms": 529.6999999284744,
          "interactive_ms": 798.0,
          "long_task_ms": 317.0,
          "pointer_delay_ms": 3.799999952316284,
          "memory_delta_bytes": 90796741.0
        },
        "correctness": {
          "render_success_rate": 1.0,
          "feature_count_match_rate": 1.0,
          "extent_match_rate": 1.0
        }
      }
    },
    "mvt-30001": {
      "A": {
        "sample_count": 1,
        "median": {
          "fetch_ms": 309.6999999284744,
          "parse_ms": 54.0,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 115.10000002384186,
          "render_ms": 171.79999995231628,
          "first_visible_ms": 764.1999999284744,
          "interactive_ms": 1078.6999999284744,
          "long_task_ms": 679.0,
          "pointer_delay_ms": 0.0,
          "memory_delta_bytes": 102405290.0
        },
        "p95": {
          "fetch_ms": 309.6999999284744,
          "parse_ms": 54.0,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 115.10000002384186,
          "render_ms": 171.79999995231628,
          "first_visible_ms": 764.1999999284744,
          "interactive_ms": 1078.6999999284744,
          "long_task_ms": 679.0,
          "pointer_delay_ms": 0.0,
          "memory_delta_bytes": 102405290.0
        },
        "correctness": {
          "render_success_rate": 1.0,
          "feature_count_match_rate": 1.0,
          "extent_match_rate": 1.0
        }
      },
      "B": {
        "sample_count": 1,
        "median": {
          "fetch_ms": 358.7999999523163,
          "parse_ms": 0.0,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 0.0,
          "render_ms": 368.8000000715256,
          "first_visible_ms": 368.10000002384186,
          "interactive_ms": 751.2000000476837,
          "long_task_ms": 239.0,
          "pointer_delay_ms": 0.0,
          "memory_delta_bytes": 24128121.0
        },
        "p95": {
          "fetch_ms": 358.7999999523163,
          "parse_ms": 0.0,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 0.0,
          "render_ms": 368.8000000715256,
          "first_visible_ms": 368.10000002384186,
          "interactive_ms": 751.2000000476837,
          "long_task_ms": 239.0,
          "pointer_delay_ms": 0.0,
          "memory_delta_bytes": 24128121.0
        },
        "correctness": {
          "render_success_rate": 1.0,
          "feature_count_match_rate": 1.0,
          "extent_match_rate": 1.0
        }
      }
    }
  }
}
```

## 解释规则

- 先比较正确性，再比较耗时；结果不正确的样本标记为失败。
- 小数据边界用于验证策略切换没有越界或回退。
- 超大图层的 A 组若因全量 GeoJSON 被拒绝，应记录为基线不可交付，不能补写耗时。
- 简历中的性能数字必须来自本报告中的真实采样和测试环境记录。
