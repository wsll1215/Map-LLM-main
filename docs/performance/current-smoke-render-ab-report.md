# GeoJSON 渲染 A/B 性能报告

> 本报告只接受实际浏览器采样结果，不预填性能数字。

- 生成时间：`2026-08-27T20:08:25.930539+00:00`
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
| direct-4999 | A | 1 | 358.2000000476837 | 358.2000000476837 | 1.0 | 1.0 | 1.0 |
| direct-4999 | B | 1 | 382.89999997615814 | 382.89999997615814 | 1.0 | 1.0 | 1.0 |
| direct-5000 | A | 1 | 421.7000000476837 | 421.7000000476837 | 1.0 | 1.0 | 1.0 |
| direct-5000 | B | 1 | 343.60000002384186 | 343.60000002384186 | 1.0 | 1.0 | 1.0 |
| worker-5001 | A | 1 | 252.5 | 252.5 | 1.0 | 1.0 | 1.0 |
| worker-5001 | B | 1 | 306.5 | 306.5 | 1.0 | 1.0 | 1.0 |
| worker-10000 | A | 1 | 406.0 | 406.0 | 1.0 | 1.0 | 1.0 |
| worker-10000 | B | 1 | 396.90000009536743 | 396.90000009536743 | 1.0 | 1.0 | 1.0 |
| worker-29999 | A | 1 | 1054.2999999523163 | 1054.2999999523163 | 1.0 | 1.0 | 1.0 |
| worker-29999 | B | 1 | 1136.3000000715256 | 1136.3000000715256 | 1.0 | 1.0 | 1.0 |
| worker-30000 | A | 1 | 938.8999999761581 | 938.8999999761581 | 1.0 | 1.0 | 1.0 |
| worker-30000 | B | 1 | 1062.7999999523163 | 1062.7999999523163 | 1.0 | 1.0 | 1.0 |
| mvt-30001 | A | 1 | 884.1999999284744 | 884.1999999284744 | 1.0 | 1.0 | 1.0 |
| mvt-30001 | B | 1 | 8662.299999952316 | 8662.299999952316 | 1.0 | 1.0 | 1.0 |

## A/B 变化

> 变化率为 B 相对 A 的 median：正数表示 B 更慢，负数表示 B 更快。没有两组真实样本时不生成比较行。

| scenario | metric | B 相对 A |
| --- | --- | ---: |
| direct-4999 | first_visible_ms | 13.2% |
| direct-4999 | interactive_ms | 6.9% |
| direct-4999 | long_task_ms | 45.4% |
| direct-5000 | first_visible_ms | -12.4% |
| direct-5000 | interactive_ms | -18.5% |
| direct-5000 | long_task_ms | -27.6% |
| worker-5001 | first_visible_ms | 35.4% |
| worker-5001 | interactive_ms | 21.4% |
| worker-5001 | long_task_ms | -24.8% |
| worker-10000 | first_visible_ms | -18.1% |
| worker-10000 | interactive_ms | -2.2% |
| worker-10000 | long_task_ms | -48.4% |
| worker-29999 | first_visible_ms | -47.4% |
| worker-29999 | interactive_ms | 7.8% |
| worker-29999 | long_task_ms | -54.4% |
| worker-30000 | first_visible_ms | -33.2% |
| worker-30000 | interactive_ms | 13.2% |
| worker-30000 | long_task_ms | -52.2% |
| mvt-30001 | first_visible_ms | 1226.8% |
| mvt-30001 | interactive_ms | 879.7% |
| mvt-30001 | long_task_ms | -50.0% |

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
      "fetch_ms": 86.60000002384186,
      "parse_ms": 8.0,
      "render_ms": 54.10000002384186,
      "interactive_ms": 358.2000000476837,
      "long_task_ms": 335.0,
      "pointer_delay_ms": 1.100000023841858,
      "memory_delta_bytes": 38555734.0,
      "render_success": true,
      "feature_count_match": true,
      "extent_match": true,
      "worker_process_ms": 0.0,
      "feature_convert_ms": 34.5,
      "first_visible_ms": 217.39999997615814,
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
      "fetch_ms": 96.70000004768372,
      "parse_ms": 9.599999904632568,
      "render_ms": 57.89999997615814,
      "interactive_ms": 382.89999997615814,
      "long_task_ms": 487.0,
      "pointer_delay_ms": 1.0,
      "memory_delta_bytes": 38493702.0,
      "render_success": true,
      "feature_count_match": true,
      "extent_match": true,
      "worker_process_ms": 0.0,
      "feature_convert_ms": 41.300000071525574,
      "first_visible_ms": 246.20000004768372,
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
      "fetch_ms": 104.20000004768372,
      "parse_ms": 9.699999928474426,
      "render_ms": 65.0,
      "interactive_ms": 421.7000000476837,
      "long_task_ms": 544.0,
      "pointer_delay_ms": 1.399999976158142,
      "memory_delta_bytes": 38983194.0,
      "render_success": true,
      "feature_count_match": true,
      "extent_match": true,
      "worker_process_ms": 0.0,
      "feature_convert_ms": 47.60000002384186,
      "first_visible_ms": 265.2000000476837,
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
      "fetch_ms": 87.60000002384186,
      "parse_ms": 8.5,
      "render_ms": 54.39999997615814,
      "interactive_ms": 343.60000002384186,
      "long_task_ms": 394.0,
      "pointer_delay_ms": 22.0,
      "memory_delta_bytes": 38886106.0,
      "render_success": true,
      "feature_count_match": true,
      "extent_match": true,
      "worker_process_ms": 0.0,
      "feature_convert_ms": 45.60000002384186,
      "first_visible_ms": 232.19999992847443,
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
      "fetch_ms": 70.10000002384186,
      "parse_ms": 7.400000095367432,
      "render_ms": 35.89999997615814,
      "interactive_ms": 252.5,
      "long_task_ms": 270.0,
      "pointer_delay_ms": 0.8000000715255737,
      "memory_delta_bytes": 38734450.0,
      "render_success": true,
      "feature_count_match": true,
      "extent_match": true,
      "worker_process_ms": 0.0,
      "feature_convert_ms": 23.40000009536743,
      "first_visible_ms": 161.60000002384186,
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
      "fetch_ms": 59.90000009536743,
      "parse_ms": 0.0,
      "render_ms": 68.5,
      "interactive_ms": 306.5,
      "long_task_ms": 203.0,
      "pointer_delay_ms": 0.7999999523162842,
      "memory_delta_bytes": 42130435.0,
      "render_success": true,
      "feature_count_match": true,
      "extent_match": true,
      "worker_process_ms": 156.60000002384186,
      "feature_convert_ms": 9.399999976158142,
      "first_visible_ms": 218.80000007152557,
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
      "fetch_ms": 107.5,
      "parse_ms": 16.40000009536743,
      "render_ms": 66.29999995231628,
      "interactive_ms": 406.0,
      "long_task_ms": 384.0,
      "pointer_delay_ms": 0.0,
      "memory_delta_bytes": 48523224.0,
      "render_success": true,
      "feature_count_match": true,
      "extent_match": true,
      "worker_process_ms": 0.0,
      "feature_convert_ms": 54.699999928474426,
      "first_visible_ms": 293.2999999523163,
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
      "fetch_ms": 99.30000007152557,
      "parse_ms": 0.0,
      "render_ms": 97.79999995231628,
      "interactive_ms": 396.90000009536743,
      "long_task_ms": 198.0,
      "pointer_delay_ms": 0.0,
      "memory_delta_bytes": 45829797.0,
      "render_success": true,
      "feature_count_match": true,
      "extent_match": true,
      "worker_process_ms": 199.89999997615814,
      "feature_convert_ms": 9.0,
      "first_visible_ms": 240.10000002384186,
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
      "fetch_ms": 363.0,
      "parse_ms": 61.5,
      "render_ms": 140.5,
      "interactive_ms": 1054.2999999523163,
      "long_task_ms": 800.0,
      "pointer_delay_ms": 0.0,
      "memory_delta_bytes": 110792778.0,
      "render_success": true,
      "feature_count_match": true,
      "extent_match": true,
      "worker_process_ms": 0.0,
      "feature_convert_ms": 152.20000004768372,
      "first_visible_ms": 856.2999999523163,
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
      "fetch_ms": 281.3000000715256,
      "parse_ms": 0.0,
      "render_ms": 84.70000004768372,
      "interactive_ms": 1136.3000000715256,
      "long_task_ms": 365.0,
      "pointer_delay_ms": 0.0,
      "memory_delta_bytes": 139413064.0,
      "render_success": true,
      "feature_count_match": true,
      "extent_match": true,
      "worker_process_ms": 661.1000000238419,
      "feature_convert_ms": 10.100000023841858,
      "first_visible_ms": 450.7000000476837,
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
      "fetch_ms": 267.10000002384186,
      "parse_ms": 45.60000002384186,
      "render_ms": 128.0,
      "interactive_ms": 938.8999999761581,
      "long_task_ms": 648.0,
      "pointer_delay_ms": 0.0,
      "memory_delta_bytes": 110641291.0,
      "render_success": true,
      "feature_count_match": true,
      "extent_match": true,
      "worker_process_ms": 0.0,
      "feature_convert_ms": 118.69999992847443,
      "first_visible_ms": 674.7000000476837,
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
      "fetch_ms": 261.1999999284744,
      "parse_ms": 0.0,
      "render_ms": 107.39999997615814,
      "interactive_ms": 1062.7999999523163,
      "long_task_ms": 310.0,
      "pointer_delay_ms": 0.0,
      "memory_delta_bytes": 115252404.0,
      "render_success": true,
      "feature_count_match": true,
      "extent_match": true,
      "worker_process_ms": 648.8999999761581,
      "feature_convert_ms": 8.599999904632568,
      "first_visible_ms": 450.7999999523163,
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
      "fetch_ms": 256.0,
      "parse_ms": 45.09999990463257,
      "render_ms": 123.29999995231628,
      "interactive_ms": 884.1999999284744,
      "long_task_ms": 612.0,
      "pointer_delay_ms": 0.0,
      "memory_delta_bytes": 103039963.0,
      "render_success": true,
      "feature_count_match": true,
      "extent_match": true,
      "worker_process_ms": 0.0,
      "feature_convert_ms": 116.10000002384186,
      "first_visible_ms": 643.7999999523163,
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
      "fetch_ms": 0.09999990463256836,
      "parse_ms": 0.0,
      "render_ms": 51.10000002384186,
      "interactive_ms": 8662.299999952316,
      "long_task_ms": 306.0,
      "pointer_delay_ms": 0.0,
      "memory_delta_bytes": 46495162.0,
      "render_success": true,
      "feature_count_match": true,
      "extent_match": true,
      "worker_process_ms": 0.0,
      "feature_convert_ms": 0.0,
      "first_visible_ms": 8542.0,
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
          "fetch_ms": 86.60000002384186,
          "parse_ms": 8.0,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 34.5,
          "render_ms": 54.10000002384186,
          "first_visible_ms": 217.39999997615814,
          "interactive_ms": 358.2000000476837,
          "long_task_ms": 335.0,
          "pointer_delay_ms": 1.100000023841858,
          "memory_delta_bytes": 38555734.0
        },
        "p95": {
          "fetch_ms": 86.60000002384186,
          "parse_ms": 8.0,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 34.5,
          "render_ms": 54.10000002384186,
          "first_visible_ms": 217.39999997615814,
          "interactive_ms": 358.2000000476837,
          "long_task_ms": 335.0,
          "pointer_delay_ms": 1.100000023841858,
          "memory_delta_bytes": 38555734.0
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
          "parse_ms": 9.599999904632568,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 41.300000071525574,
          "render_ms": 57.89999997615814,
          "first_visible_ms": 246.20000004768372,
          "interactive_ms": 382.89999997615814,
          "long_task_ms": 487.0,
          "pointer_delay_ms": 1.0,
          "memory_delta_bytes": 38493702.0
        },
        "p95": {
          "fetch_ms": 96.70000004768372,
          "parse_ms": 9.599999904632568,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 41.300000071525574,
          "render_ms": 57.89999997615814,
          "first_visible_ms": 246.20000004768372,
          "interactive_ms": 382.89999997615814,
          "long_task_ms": 487.0,
          "pointer_delay_ms": 1.0,
          "memory_delta_bytes": 38493702.0
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
          "fetch_ms": 104.20000004768372,
          "parse_ms": 9.699999928474426,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 47.60000002384186,
          "render_ms": 65.0,
          "first_visible_ms": 265.2000000476837,
          "interactive_ms": 421.7000000476837,
          "long_task_ms": 544.0,
          "pointer_delay_ms": 1.399999976158142,
          "memory_delta_bytes": 38983194.0
        },
        "p95": {
          "fetch_ms": 104.20000004768372,
          "parse_ms": 9.699999928474426,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 47.60000002384186,
          "render_ms": 65.0,
          "first_visible_ms": 265.2000000476837,
          "interactive_ms": 421.7000000476837,
          "long_task_ms": 544.0,
          "pointer_delay_ms": 1.399999976158142,
          "memory_delta_bytes": 38983194.0
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
          "fetch_ms": 87.60000002384186,
          "parse_ms": 8.5,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 45.60000002384186,
          "render_ms": 54.39999997615814,
          "first_visible_ms": 232.19999992847443,
          "interactive_ms": 343.60000002384186,
          "long_task_ms": 394.0,
          "pointer_delay_ms": 22.0,
          "memory_delta_bytes": 38886106.0
        },
        "p95": {
          "fetch_ms": 87.60000002384186,
          "parse_ms": 8.5,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 45.60000002384186,
          "render_ms": 54.39999997615814,
          "first_visible_ms": 232.19999992847443,
          "interactive_ms": 343.60000002384186,
          "long_task_ms": 394.0,
          "pointer_delay_ms": 22.0,
          "memory_delta_bytes": 38886106.0
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
          "fetch_ms": 70.10000002384186,
          "parse_ms": 7.400000095367432,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 23.40000009536743,
          "render_ms": 35.89999997615814,
          "first_visible_ms": 161.60000002384186,
          "interactive_ms": 252.5,
          "long_task_ms": 270.0,
          "pointer_delay_ms": 0.8000000715255737,
          "memory_delta_bytes": 38734450.0
        },
        "p95": {
          "fetch_ms": 70.10000002384186,
          "parse_ms": 7.400000095367432,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 23.40000009536743,
          "render_ms": 35.89999997615814,
          "first_visible_ms": 161.60000002384186,
          "interactive_ms": 252.5,
          "long_task_ms": 270.0,
          "pointer_delay_ms": 0.8000000715255737,
          "memory_delta_bytes": 38734450.0
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
          "fetch_ms": 59.90000009536743,
          "parse_ms": 0.0,
          "worker_process_ms": 156.60000002384186,
          "feature_convert_ms": 9.399999976158142,
          "render_ms": 68.5,
          "first_visible_ms": 218.80000007152557,
          "interactive_ms": 306.5,
          "long_task_ms": 203.0,
          "pointer_delay_ms": 0.7999999523162842,
          "memory_delta_bytes": 42130435.0
        },
        "p95": {
          "fetch_ms": 59.90000009536743,
          "parse_ms": 0.0,
          "worker_process_ms": 156.60000002384186,
          "feature_convert_ms": 9.399999976158142,
          "render_ms": 68.5,
          "first_visible_ms": 218.80000007152557,
          "interactive_ms": 306.5,
          "long_task_ms": 203.0,
          "pointer_delay_ms": 0.7999999523162842,
          "memory_delta_bytes": 42130435.0
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
          "fetch_ms": 107.5,
          "parse_ms": 16.40000009536743,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 54.699999928474426,
          "render_ms": 66.29999995231628,
          "first_visible_ms": 293.2999999523163,
          "interactive_ms": 406.0,
          "long_task_ms": 384.0,
          "pointer_delay_ms": 0.0,
          "memory_delta_bytes": 48523224.0
        },
        "p95": {
          "fetch_ms": 107.5,
          "parse_ms": 16.40000009536743,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 54.699999928474426,
          "render_ms": 66.29999995231628,
          "first_visible_ms": 293.2999999523163,
          "interactive_ms": 406.0,
          "long_task_ms": 384.0,
          "pointer_delay_ms": 0.0,
          "memory_delta_bytes": 48523224.0
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
          "fetch_ms": 99.30000007152557,
          "parse_ms": 0.0,
          "worker_process_ms": 199.89999997615814,
          "feature_convert_ms": 9.0,
          "render_ms": 97.79999995231628,
          "first_visible_ms": 240.10000002384186,
          "interactive_ms": 396.90000009536743,
          "long_task_ms": 198.0,
          "pointer_delay_ms": 0.0,
          "memory_delta_bytes": 45829797.0
        },
        "p95": {
          "fetch_ms": 99.30000007152557,
          "parse_ms": 0.0,
          "worker_process_ms": 199.89999997615814,
          "feature_convert_ms": 9.0,
          "render_ms": 97.79999995231628,
          "first_visible_ms": 240.10000002384186,
          "interactive_ms": 396.90000009536743,
          "long_task_ms": 198.0,
          "pointer_delay_ms": 0.0,
          "memory_delta_bytes": 45829797.0
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
          "fetch_ms": 363.0,
          "parse_ms": 61.5,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 152.20000004768372,
          "render_ms": 140.5,
          "first_visible_ms": 856.2999999523163,
          "interactive_ms": 1054.2999999523163,
          "long_task_ms": 800.0,
          "pointer_delay_ms": 0.0,
          "memory_delta_bytes": 110792778.0
        },
        "p95": {
          "fetch_ms": 363.0,
          "parse_ms": 61.5,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 152.20000004768372,
          "render_ms": 140.5,
          "first_visible_ms": 856.2999999523163,
          "interactive_ms": 1054.2999999523163,
          "long_task_ms": 800.0,
          "pointer_delay_ms": 0.0,
          "memory_delta_bytes": 110792778.0
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
          "fetch_ms": 281.3000000715256,
          "parse_ms": 0.0,
          "worker_process_ms": 661.1000000238419,
          "feature_convert_ms": 10.100000023841858,
          "render_ms": 84.70000004768372,
          "first_visible_ms": 450.7000000476837,
          "interactive_ms": 1136.3000000715256,
          "long_task_ms": 365.0,
          "pointer_delay_ms": 0.0,
          "memory_delta_bytes": 139413064.0
        },
        "p95": {
          "fetch_ms": 281.3000000715256,
          "parse_ms": 0.0,
          "worker_process_ms": 661.1000000238419,
          "feature_convert_ms": 10.100000023841858,
          "render_ms": 84.70000004768372,
          "first_visible_ms": 450.7000000476837,
          "interactive_ms": 1136.3000000715256,
          "long_task_ms": 365.0,
          "pointer_delay_ms": 0.0,
          "memory_delta_bytes": 139413064.0
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
          "fetch_ms": 267.10000002384186,
          "parse_ms": 45.60000002384186,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 118.69999992847443,
          "render_ms": 128.0,
          "first_visible_ms": 674.7000000476837,
          "interactive_ms": 938.8999999761581,
          "long_task_ms": 648.0,
          "pointer_delay_ms": 0.0,
          "memory_delta_bytes": 110641291.0
        },
        "p95": {
          "fetch_ms": 267.10000002384186,
          "parse_ms": 45.60000002384186,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 118.69999992847443,
          "render_ms": 128.0,
          "first_visible_ms": 674.7000000476837,
          "interactive_ms": 938.8999999761581,
          "long_task_ms": 648.0,
          "pointer_delay_ms": 0.0,
          "memory_delta_bytes": 110641291.0
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
          "fetch_ms": 261.1999999284744,
          "parse_ms": 0.0,
          "worker_process_ms": 648.8999999761581,
          "feature_convert_ms": 8.599999904632568,
          "render_ms": 107.39999997615814,
          "first_visible_ms": 450.7999999523163,
          "interactive_ms": 1062.7999999523163,
          "long_task_ms": 310.0,
          "pointer_delay_ms": 0.0,
          "memory_delta_bytes": 115252404.0
        },
        "p95": {
          "fetch_ms": 261.1999999284744,
          "parse_ms": 0.0,
          "worker_process_ms": 648.8999999761581,
          "feature_convert_ms": 8.599999904632568,
          "render_ms": 107.39999997615814,
          "first_visible_ms": 450.7999999523163,
          "interactive_ms": 1062.7999999523163,
          "long_task_ms": 310.0,
          "pointer_delay_ms": 0.0,
          "memory_delta_bytes": 115252404.0
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
          "fetch_ms": 256.0,
          "parse_ms": 45.09999990463257,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 116.10000002384186,
          "render_ms": 123.29999995231628,
          "first_visible_ms": 643.7999999523163,
          "interactive_ms": 884.1999999284744,
          "long_task_ms": 612.0,
          "pointer_delay_ms": 0.0,
          "memory_delta_bytes": 103039963.0
        },
        "p95": {
          "fetch_ms": 256.0,
          "parse_ms": 45.09999990463257,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 116.10000002384186,
          "render_ms": 123.29999995231628,
          "first_visible_ms": 643.7999999523163,
          "interactive_ms": 884.1999999284744,
          "long_task_ms": 612.0,
          "pointer_delay_ms": 0.0,
          "memory_delta_bytes": 103039963.0
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
          "fetch_ms": 0.09999990463256836,
          "parse_ms": 0.0,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 0.0,
          "render_ms": 51.10000002384186,
          "first_visible_ms": 8542.0,
          "interactive_ms": 8662.299999952316,
          "long_task_ms": 306.0,
          "pointer_delay_ms": 0.0,
          "memory_delta_bytes": 46495162.0
        },
        "p95": {
          "fetch_ms": 0.09999990463256836,
          "parse_ms": 0.0,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 0.0,
          "render_ms": 51.10000002384186,
          "first_visible_ms": 8542.0,
          "interactive_ms": 8662.299999952316,
          "long_task_ms": 306.0,
          "pointer_delay_ms": 0.0,
          "memory_delta_bytes": 46495162.0
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
