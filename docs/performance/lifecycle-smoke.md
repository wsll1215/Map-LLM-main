# GeoJSON 渲染 A/B 性能报告

> 本报告只接受实际浏览器采样结果，不预填性能数字。

- 生成时间：`2026-08-27T20:35:14.559496+00:00`
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
| direct-4999 | A | 1 | 286.60000002384186 | 286.60000002384186 | 1.0 | 1.0 | 1.0 |
| direct-4999 | B | 1 | 269.8000000715256 | 269.8000000715256 | 1.0 | 1.0 | 1.0 |
| direct-5000 | A | 1 | 242.29999995231628 | 242.29999995231628 | 1.0 | 1.0 | 1.0 |
| direct-5000 | B | 1 | 238.09999990463257 | 238.09999990463257 | 1.0 | 1.0 | 1.0 |
| worker-5001 | A | 1 | 373.7999999523163 | 373.7999999523163 | 1.0 | 1.0 | 1.0 |
| worker-5001 | B | 1 | 344.90000009536743 | 344.90000009536743 | 1.0 | 1.0 | 1.0 |
| worker-10000 | A | 1 | 367.0 | 367.0 | 1.0 | 1.0 | 1.0 |
| worker-10000 | B | 1 | 384.39999997615814 | 384.39999997615814 | 1.0 | 1.0 | 1.0 |
| worker-29999 | A | 1 | 1381.1000000238419 | 1381.1000000238419 | 1.0 | 1.0 | 1.0 |
| worker-29999 | B | 1 | 1050.7999999523163 | 1050.7999999523163 | 1.0 | 1.0 | 1.0 |
| worker-30000 | A | 1 | 1057.2000000476837 | 1057.2000000476837 | 1.0 | 1.0 | 1.0 |
| worker-30000 | B | 1 | 1002.9000000953674 | 1002.9000000953674 | 1.0 | 1.0 | 1.0 |
| mvt-30001 | A | 1 | 939.2999999523163 | 939.2999999523163 | 1.0 | 1.0 | 1.0 |
| mvt-30001 | B | 1 | 8385.5 | 8385.5 | 1.0 | 1.0 | 1.0 |

## A/B 变化

> 变化率为 B 相对 A 的 median：正数表示 B 更慢，负数表示 B 更快。没有两组真实样本时不生成比较行。

| scenario | metric | B 相对 A |
| --- | --- | ---: |
| direct-4999 | first_visible_ms | 5.7% |
| direct-4999 | interactive_ms | -5.9% |
| direct-4999 | long_task_ms | 27.5% |
| direct-5000 | first_visible_ms | -2.5% |
| direct-5000 | interactive_ms | -1.7% |
| direct-5000 | long_task_ms | -1.9% |
| worker-5001 | first_visible_ms | 16.8% |
| worker-5001 | interactive_ms | -7.7% |
| worker-5001 | long_task_ms | -45.4% |
| worker-10000 | first_visible_ms | -8.6% |
| worker-10000 | interactive_ms | 4.7% |
| worker-10000 | long_task_ms | -44.4% |
| worker-29999 | first_visible_ms | -53.9% |
| worker-29999 | interactive_ms | -23.9% |
| worker-29999 | long_task_ms | -64.9% |
| worker-30000 | first_visible_ms | -46.8% |
| worker-30000 | interactive_ms | -5.1% |
| worker-30000 | long_task_ms | -52.6% |
| mvt-30001 | first_visible_ms | 1109.8% |
| mvt-30001 | interactive_ms | 792.7% |
| mvt-30001 | long_task_ms | -31.0% |

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
      "fetch_ms": 70.89999997615814,
      "parse_ms": 7.100000023841858,
      "render_ms": 42.60000002384186,
      "interactive_ms": 286.60000002384186,
      "long_task_ms": 240.0,
      "pointer_delay_ms": 3.299999952316284,
      "memory_delta_bytes": 39304540.0,
      "render_success": true,
      "feature_count_match": true,
      "extent_match": true,
      "worker_process_ms": 0.0,
      "feature_convert_ms": 24.100000023841858,
      "first_visible_ms": 169.10000002384186,
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
      "seed": 20260827
    },
    {
      "scenario": "direct-4999",
      "variant": "B",
      "feature_count": 4999,
      "fetch_ms": 70.70000004768372,
      "parse_ms": 7.5,
      "render_ms": 39.300000071525574,
      "interactive_ms": 269.8000000715256,
      "long_task_ms": 306.0,
      "pointer_delay_ms": 0.7999999523162842,
      "memory_delta_bytes": 38328766.0,
      "render_success": true,
      "feature_count_match": true,
      "extent_match": true,
      "worker_process_ms": 0.0,
      "feature_convert_ms": 30.699999928474426,
      "first_visible_ms": 178.80000007152557,
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
      "seed": 20260827
    },
    {
      "scenario": "direct-5000",
      "variant": "A",
      "feature_count": 5000,
      "fetch_ms": 65.0,
      "parse_ms": 7.0,
      "render_ms": 35.60000002384186,
      "interactive_ms": 242.29999995231628,
      "long_task_ms": 262.0,
      "pointer_delay_ms": 0.7999999523162842,
      "memory_delta_bytes": 38394478.0,
      "render_success": true,
      "feature_count_match": true,
      "extent_match": true,
      "worker_process_ms": 0.0,
      "feature_convert_ms": 23.300000071525574,
      "first_visible_ms": 153.79999995231628,
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
      "seed": 20260827
    },
    {
      "scenario": "direct-5000",
      "variant": "B",
      "feature_count": 5000,
      "fetch_ms": 63.5,
      "parse_ms": 7.0,
      "render_ms": 34.59999990463257,
      "interactive_ms": 238.09999990463257,
      "long_task_ms": 257.0,
      "pointer_delay_ms": 0.8999999761581421,
      "memory_delta_bytes": 38469910.0,
      "render_success": true,
      "feature_count_match": true,
      "extent_match": true,
      "worker_process_ms": 0.0,
      "feature_convert_ms": 22.0,
      "first_visible_ms": 150.0,
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
      "seed": 20260827
    },
    {
      "scenario": "worker-5001",
      "variant": "A",
      "feature_count": 5001,
      "fetch_ms": 88.0,
      "parse_ms": 9.0,
      "render_ms": 50.39999997615814,
      "interactive_ms": 373.7999999523163,
      "long_task_ms": 401.0,
      "pointer_delay_ms": 1.1999999284744263,
      "memory_delta_bytes": 38726874.0,
      "render_success": true,
      "feature_count_match": true,
      "extent_match": true,
      "worker_process_ms": 0.0,
      "feature_convert_ms": 31.100000023841858,
      "first_visible_ms": 221.5,
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
      "seed": 20260827
    },
    {
      "scenario": "worker-5001",
      "variant": "B",
      "feature_count": 5001,
      "fetch_ms": 67.60000002384186,
      "parse_ms": 0.0,
      "render_ms": 86.20000004768372,
      "interactive_ms": 344.90000009536743,
      "long_task_ms": 219.0,
      "pointer_delay_ms": 0.0,
      "memory_delta_bytes": 36584531.0,
      "render_success": true,
      "feature_count_match": true,
      "extent_match": true,
      "worker_process_ms": 189.5,
      "feature_convert_ms": 12.300000071525574,
      "first_visible_ms": 258.7000000476837,
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
      "seed": 20260827
    },
    {
      "scenario": "worker-10000",
      "variant": "A",
      "feature_count": 10000,
      "fetch_ms": 117.89999997615814,
      "parse_ms": 14.600000023841858,
      "render_ms": 50.60000002384186,
      "interactive_ms": 367.0,
      "long_task_ms": 363.0,
      "pointer_delay_ms": 0.0,
      "memory_delta_bytes": 48536052.0,
      "render_success": true,
      "feature_count_match": true,
      "extent_match": true,
      "worker_process_ms": 0.0,
      "feature_convert_ms": 49.700000047683716,
      "first_visible_ms": 270.39999997615814,
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
      "seed": 20260827
    },
    {
      "scenario": "worker-10000",
      "variant": "B",
      "feature_count": 10000,
      "fetch_ms": 96.70000004768372,
      "parse_ms": 0.0,
      "render_ms": 108.0,
      "interactive_ms": 384.39999997615814,
      "long_task_ms": 202.0,
      "pointer_delay_ms": 0.0,
      "memory_delta_bytes": 45877625.0,
      "render_success": true,
      "feature_count_match": true,
      "extent_match": true,
      "worker_process_ms": 190.39999997615814,
      "feature_convert_ms": 8.5,
      "first_visible_ms": 247.10000002384186,
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
      "seed": 20260827
    },
    {
      "scenario": "worker-29999",
      "variant": "A",
      "feature_count": 29999,
      "fetch_ms": 377.6999999284744,
      "parse_ms": 89.20000004768372,
      "render_ms": 195.60000002384186,
      "interactive_ms": 1381.1000000238419,
      "long_task_ms": 875.0,
      "pointer_delay_ms": 0.0,
      "memory_delta_bytes": 102957618.0,
      "render_success": true,
      "feature_count_match": true,
      "extent_match": true,
      "worker_process_ms": 0.0,
      "feature_convert_ms": 212.59999990463257,
      "first_visible_ms": 1061.3999999761581,
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
      "seed": 20260827
    },
    {
      "scenario": "worker-29999",
      "variant": "B",
      "feature_count": 29999,
      "fetch_ms": 280.10000002384186,
      "parse_ms": 0.0,
      "render_ms": 113.10000002384186,
      "interactive_ms": 1050.7999999523163,
      "long_task_ms": 307.0,
      "pointer_delay_ms": 0.0,
      "memory_delta_bytes": 140128724.0,
      "render_success": true,
      "feature_count_match": true,
      "extent_match": true,
      "worker_process_ms": 576.9000000953674,
      "feature_convert_ms": 10.399999976158142,
      "first_visible_ms": 489.5,
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
      "seed": 20260827
    },
    {
      "scenario": "worker-30000",
      "variant": "A",
      "feature_count": 30000,
      "fetch_ms": 303.10000002384186,
      "parse_ms": 59.799999952316284,
      "render_ms": 134.90000009536743,
      "interactive_ms": 1057.2000000476837,
      "long_task_ms": 666.0,
      "pointer_delay_ms": 0.0,
      "memory_delta_bytes": 110980403.0,
      "render_success": true,
      "feature_count_match": true,
      "extent_match": true,
      "worker_process_ms": 0.0,
      "feature_convert_ms": 154.89999997615814,
      "first_visible_ms": 782.9000000953674,
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
      "seed": 20260827
    },
    {
      "scenario": "worker-30000",
      "variant": "B",
      "feature_count": 30000,
      "fetch_ms": 266.40000009536743,
      "parse_ms": 0.0,
      "render_ms": 60.39999997615814,
      "interactive_ms": 1002.9000000953674,
      "long_task_ms": 316.0,
      "pointer_delay_ms": 0.0,
      "memory_delta_bytes": 142103976.0,
      "render_success": true,
      "feature_count_match": true,
      "extent_match": true,
      "worker_process_ms": 599.1999999284744,
      "feature_convert_ms": 9.899999976158142,
      "first_visible_ms": 416.8000000715256,
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
      "seed": 20260827
    },
    {
      "scenario": "mvt-30001",
      "variant": "A",
      "feature_count": 30001,
      "fetch_ms": 272.7999999523163,
      "parse_ms": 45.300000071525574,
      "render_ms": 132.79999995231628,
      "interactive_ms": 939.2999999523163,
      "long_task_ms": 616.0,
      "pointer_delay_ms": 0.0,
      "memory_delta_bytes": 110954935.0,
      "render_success": true,
      "feature_count_match": true,
      "extent_match": true,
      "worker_process_ms": 0.0,
      "feature_convert_ms": 112.89999997615814,
      "first_visible_ms": 682.8999999761581,
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
      "seed": 20260827
    },
    {
      "scenario": "mvt-30001",
      "variant": "B",
      "feature_count": 30001,
      "fetch_ms": 0.20000004768371582,
      "parse_ms": 0.0,
      "render_ms": 52.90000009536743,
      "interactive_ms": 8385.5,
      "long_task_ms": 425.0,
      "pointer_delay_ms": 0.0,
      "memory_delta_bytes": 46495926.0,
      "render_success": true,
      "feature_count_match": true,
      "extent_match": true,
      "worker_process_ms": 0.0,
      "feature_convert_ms": 0.0,
      "first_visible_ms": 8261.700000047684,
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
      "seed": 20260827
    }
  ],
  "summaries": {
    "direct-4999": {
      "A": {
        "sample_count": 1,
        "median": {
          "fetch_ms": 70.89999997615814,
          "parse_ms": 7.100000023841858,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 24.100000023841858,
          "render_ms": 42.60000002384186,
          "first_visible_ms": 169.10000002384186,
          "interactive_ms": 286.60000002384186,
          "long_task_ms": 240.0,
          "pointer_delay_ms": 3.299999952316284,
          "memory_delta_bytes": 39304540.0
        },
        "p95": {
          "fetch_ms": 70.89999997615814,
          "parse_ms": 7.100000023841858,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 24.100000023841858,
          "render_ms": 42.60000002384186,
          "first_visible_ms": 169.10000002384186,
          "interactive_ms": 286.60000002384186,
          "long_task_ms": 240.0,
          "pointer_delay_ms": 3.299999952316284,
          "memory_delta_bytes": 39304540.0
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
          "fetch_ms": 70.70000004768372,
          "parse_ms": 7.5,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 30.699999928474426,
          "render_ms": 39.300000071525574,
          "first_visible_ms": 178.80000007152557,
          "interactive_ms": 269.8000000715256,
          "long_task_ms": 306.0,
          "pointer_delay_ms": 0.7999999523162842,
          "memory_delta_bytes": 38328766.0
        },
        "p95": {
          "fetch_ms": 70.70000004768372,
          "parse_ms": 7.5,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 30.699999928474426,
          "render_ms": 39.300000071525574,
          "first_visible_ms": 178.80000007152557,
          "interactive_ms": 269.8000000715256,
          "long_task_ms": 306.0,
          "pointer_delay_ms": 0.7999999523162842,
          "memory_delta_bytes": 38328766.0
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
          "fetch_ms": 65.0,
          "parse_ms": 7.0,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 23.300000071525574,
          "render_ms": 35.60000002384186,
          "first_visible_ms": 153.79999995231628,
          "interactive_ms": 242.29999995231628,
          "long_task_ms": 262.0,
          "pointer_delay_ms": 0.7999999523162842,
          "memory_delta_bytes": 38394478.0
        },
        "p95": {
          "fetch_ms": 65.0,
          "parse_ms": 7.0,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 23.300000071525574,
          "render_ms": 35.60000002384186,
          "first_visible_ms": 153.79999995231628,
          "interactive_ms": 242.29999995231628,
          "long_task_ms": 262.0,
          "pointer_delay_ms": 0.7999999523162842,
          "memory_delta_bytes": 38394478.0
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
          "fetch_ms": 63.5,
          "parse_ms": 7.0,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 22.0,
          "render_ms": 34.59999990463257,
          "first_visible_ms": 150.0,
          "interactive_ms": 238.09999990463257,
          "long_task_ms": 257.0,
          "pointer_delay_ms": 0.8999999761581421,
          "memory_delta_bytes": 38469910.0
        },
        "p95": {
          "fetch_ms": 63.5,
          "parse_ms": 7.0,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 22.0,
          "render_ms": 34.59999990463257,
          "first_visible_ms": 150.0,
          "interactive_ms": 238.09999990463257,
          "long_task_ms": 257.0,
          "pointer_delay_ms": 0.8999999761581421,
          "memory_delta_bytes": 38469910.0
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
          "fetch_ms": 88.0,
          "parse_ms": 9.0,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 31.100000023841858,
          "render_ms": 50.39999997615814,
          "first_visible_ms": 221.5,
          "interactive_ms": 373.7999999523163,
          "long_task_ms": 401.0,
          "pointer_delay_ms": 1.1999999284744263,
          "memory_delta_bytes": 38726874.0
        },
        "p95": {
          "fetch_ms": 88.0,
          "parse_ms": 9.0,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 31.100000023841858,
          "render_ms": 50.39999997615814,
          "first_visible_ms": 221.5,
          "interactive_ms": 373.7999999523163,
          "long_task_ms": 401.0,
          "pointer_delay_ms": 1.1999999284744263,
          "memory_delta_bytes": 38726874.0
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
          "fetch_ms": 67.60000002384186,
          "parse_ms": 0.0,
          "worker_process_ms": 189.5,
          "feature_convert_ms": 12.300000071525574,
          "render_ms": 86.20000004768372,
          "first_visible_ms": 258.7000000476837,
          "interactive_ms": 344.90000009536743,
          "long_task_ms": 219.0,
          "pointer_delay_ms": 0.0,
          "memory_delta_bytes": 36584531.0
        },
        "p95": {
          "fetch_ms": 67.60000002384186,
          "parse_ms": 0.0,
          "worker_process_ms": 189.5,
          "feature_convert_ms": 12.300000071525574,
          "render_ms": 86.20000004768372,
          "first_visible_ms": 258.7000000476837,
          "interactive_ms": 344.90000009536743,
          "long_task_ms": 219.0,
          "pointer_delay_ms": 0.0,
          "memory_delta_bytes": 36584531.0
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
          "fetch_ms": 117.89999997615814,
          "parse_ms": 14.600000023841858,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 49.700000047683716,
          "render_ms": 50.60000002384186,
          "first_visible_ms": 270.39999997615814,
          "interactive_ms": 367.0,
          "long_task_ms": 363.0,
          "pointer_delay_ms": 0.0,
          "memory_delta_bytes": 48536052.0
        },
        "p95": {
          "fetch_ms": 117.89999997615814,
          "parse_ms": 14.600000023841858,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 49.700000047683716,
          "render_ms": 50.60000002384186,
          "first_visible_ms": 270.39999997615814,
          "interactive_ms": 367.0,
          "long_task_ms": 363.0,
          "pointer_delay_ms": 0.0,
          "memory_delta_bytes": 48536052.0
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
          "fetch_ms": 96.70000004768372,
          "parse_ms": 0.0,
          "worker_process_ms": 190.39999997615814,
          "feature_convert_ms": 8.5,
          "render_ms": 108.0,
          "first_visible_ms": 247.10000002384186,
          "interactive_ms": 384.39999997615814,
          "long_task_ms": 202.0,
          "pointer_delay_ms": 0.0,
          "memory_delta_bytes": 45877625.0
        },
        "p95": {
          "fetch_ms": 96.70000004768372,
          "parse_ms": 0.0,
          "worker_process_ms": 190.39999997615814,
          "feature_convert_ms": 8.5,
          "render_ms": 108.0,
          "first_visible_ms": 247.10000002384186,
          "interactive_ms": 384.39999997615814,
          "long_task_ms": 202.0,
          "pointer_delay_ms": 0.0,
          "memory_delta_bytes": 45877625.0
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
          "fetch_ms": 377.6999999284744,
          "parse_ms": 89.20000004768372,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 212.59999990463257,
          "render_ms": 195.60000002384186,
          "first_visible_ms": 1061.3999999761581,
          "interactive_ms": 1381.1000000238419,
          "long_task_ms": 875.0,
          "pointer_delay_ms": 0.0,
          "memory_delta_bytes": 102957618.0
        },
        "p95": {
          "fetch_ms": 377.6999999284744,
          "parse_ms": 89.20000004768372,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 212.59999990463257,
          "render_ms": 195.60000002384186,
          "first_visible_ms": 1061.3999999761581,
          "interactive_ms": 1381.1000000238419,
          "long_task_ms": 875.0,
          "pointer_delay_ms": 0.0,
          "memory_delta_bytes": 102957618.0
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
          "fetch_ms": 280.10000002384186,
          "parse_ms": 0.0,
          "worker_process_ms": 576.9000000953674,
          "feature_convert_ms": 10.399999976158142,
          "render_ms": 113.10000002384186,
          "first_visible_ms": 489.5,
          "interactive_ms": 1050.7999999523163,
          "long_task_ms": 307.0,
          "pointer_delay_ms": 0.0,
          "memory_delta_bytes": 140128724.0
        },
        "p95": {
          "fetch_ms": 280.10000002384186,
          "parse_ms": 0.0,
          "worker_process_ms": 576.9000000953674,
          "feature_convert_ms": 10.399999976158142,
          "render_ms": 113.10000002384186,
          "first_visible_ms": 489.5,
          "interactive_ms": 1050.7999999523163,
          "long_task_ms": 307.0,
          "pointer_delay_ms": 0.0,
          "memory_delta_bytes": 140128724.0
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
          "fetch_ms": 303.10000002384186,
          "parse_ms": 59.799999952316284,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 154.89999997615814,
          "render_ms": 134.90000009536743,
          "first_visible_ms": 782.9000000953674,
          "interactive_ms": 1057.2000000476837,
          "long_task_ms": 666.0,
          "pointer_delay_ms": 0.0,
          "memory_delta_bytes": 110980403.0
        },
        "p95": {
          "fetch_ms": 303.10000002384186,
          "parse_ms": 59.799999952316284,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 154.89999997615814,
          "render_ms": 134.90000009536743,
          "first_visible_ms": 782.9000000953674,
          "interactive_ms": 1057.2000000476837,
          "long_task_ms": 666.0,
          "pointer_delay_ms": 0.0,
          "memory_delta_bytes": 110980403.0
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
          "fetch_ms": 266.40000009536743,
          "parse_ms": 0.0,
          "worker_process_ms": 599.1999999284744,
          "feature_convert_ms": 9.899999976158142,
          "render_ms": 60.39999997615814,
          "first_visible_ms": 416.8000000715256,
          "interactive_ms": 1002.9000000953674,
          "long_task_ms": 316.0,
          "pointer_delay_ms": 0.0,
          "memory_delta_bytes": 142103976.0
        },
        "p95": {
          "fetch_ms": 266.40000009536743,
          "parse_ms": 0.0,
          "worker_process_ms": 599.1999999284744,
          "feature_convert_ms": 9.899999976158142,
          "render_ms": 60.39999997615814,
          "first_visible_ms": 416.8000000715256,
          "interactive_ms": 1002.9000000953674,
          "long_task_ms": 316.0,
          "pointer_delay_ms": 0.0,
          "memory_delta_bytes": 142103976.0
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
          "fetch_ms": 272.7999999523163,
          "parse_ms": 45.300000071525574,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 112.89999997615814,
          "render_ms": 132.79999995231628,
          "first_visible_ms": 682.8999999761581,
          "interactive_ms": 939.2999999523163,
          "long_task_ms": 616.0,
          "pointer_delay_ms": 0.0,
          "memory_delta_bytes": 110954935.0
        },
        "p95": {
          "fetch_ms": 272.7999999523163,
          "parse_ms": 45.300000071525574,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 112.89999997615814,
          "render_ms": 132.79999995231628,
          "first_visible_ms": 682.8999999761581,
          "interactive_ms": 939.2999999523163,
          "long_task_ms": 616.0,
          "pointer_delay_ms": 0.0,
          "memory_delta_bytes": 110954935.0
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
          "fetch_ms": 0.20000004768371582,
          "parse_ms": 0.0,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 0.0,
          "render_ms": 52.90000009536743,
          "first_visible_ms": 8261.700000047684,
          "interactive_ms": 8385.5,
          "long_task_ms": 425.0,
          "pointer_delay_ms": 0.0,
          "memory_delta_bytes": 46495926.0
        },
        "p95": {
          "fetch_ms": 0.20000004768371582,
          "parse_ms": 0.0,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 0.0,
          "render_ms": 52.90000009536743,
          "first_visible_ms": 8261.700000047684,
          "interactive_ms": 8385.5,
          "long_task_ms": 425.0,
          "pointer_delay_ms": 0.0,
          "memory_delta_bytes": 46495926.0
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
