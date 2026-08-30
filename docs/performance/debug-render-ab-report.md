# GeoJSON 渲染 A/B 性能报告

> 本报告只接受实际浏览器采样结果，不预填性能数字。

- 生成时间：`2026-08-27T19:59:32.175350+00:00`
- 数据：固定 seed 的合成 LineString GeoJSON
- A：强制主线程直载基线；B：按规模选择 direct/worker/mvt
- 统计：每个场景应预热 5 次、正式采样 30 次，报告 median 和 P95
- 可交互定义：地图完成绘制，并成功响应一次拖动事件

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
| direct-4999 | A | 1 | 344.7000000476837 | 344.7000000476837 | 1.0 | 1.0 | 1.0 |
| direct-4999 | B | 1 | 293.89999997615814 | 293.89999997615814 | 1.0 | 1.0 | 1.0 |
| direct-5000 | A | 1 | 387.60000002384186 | 387.60000002384186 | 1.0 | 1.0 | 1.0 |
| direct-5000 | B | 1 | 292.10000002384186 | 292.10000002384186 | 1.0 | 1.0 | 1.0 |
| worker-5001 | A | 1 | 274.7999999523163 | 274.7999999523163 | 1.0 | 1.0 | 1.0 |
| worker-5001 | B | 1 | 322.2000000476837 | 322.2000000476837 | 1.0 | 1.0 | 1.0 |
| worker-10000 | A | 1 | 376.60000002384186 | 376.60000002384186 | 1.0 | 1.0 | 1.0 |
| worker-10000 | B | 1 | 542.0 | 542.0 | 1.0 | 1.0 | 1.0 |
| worker-29999 | A | 1 | 1240.5 | 1240.5 | 1.0 | 1.0 | 1.0 |
| worker-29999 | B | 1 | 1089.2000000476837 | 1089.2000000476837 | 1.0 | 1.0 | 1.0 |
| worker-30000 | A | 1 | 987.8000000715256 | 987.8000000715256 | 1.0 | 1.0 | 1.0 |
| worker-30000 | B | 1 | 1135.0 | 1135.0 | 1.0 | 1.0 | 1.0 |
| mvt-30001 | A | 1 | 1032.5 | 1032.5 | 1.0 | 1.0 | 1.0 |
| mvt-30001 | B | 1 | 8814.600000023842 | 8814.600000023842 | 1.0 | 1.0 | 1.0 |

## A/B 变化

> 变化率为 B 相对 A 的 median：正数表示 B 更慢，负数表示 B 更快。没有两组真实样本时不生成比较行。

| scenario | metric | B 相对 A |
| --- | --- | ---: |
| direct-4999 | first_visible_ms | -9.9% |
| direct-4999 | interactive_ms | -14.7% |
| direct-4999 | long_task_ms | -23.1% |
| direct-5000 | first_visible_ms | -22.0% |
| direct-5000 | interactive_ms | -24.6% |
| direct-5000 | long_task_ms | -43.5% |
| worker-5001 | first_visible_ms | 28.9% |
| worker-5001 | interactive_ms | 17.2% |
| worker-5001 | long_task_ms | -26.6% |
| worker-10000 | first_visible_ms | 17.2% |
| worker-10000 | interactive_ms | 43.9% |
| worker-10000 | long_task_ms | -38.0% |
| worker-29999 | first_visible_ms | -60.2% |
| worker-29999 | interactive_ms | -12.2% |
| worker-29999 | long_task_ms | -66.1% |
| worker-30000 | first_visible_ms | -26.7% |
| worker-30000 | interactive_ms | 14.9% |
| worker-30000 | long_task_ms | -41.7% |
| mvt-30001 | first_visible_ms | 1031.6% |
| mvt-30001 | interactive_ms | 753.7% |
| mvt-30001 | long_task_ms | -63.2% |

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
      "fetch_ms": 88.10000002384186,
      "parse_ms": 8.099999904632568,
      "render_ms": 51.799999952316284,
      "interactive_ms": 344.7000000476837,
      "long_task_ms": 420.0,
      "pointer_delay_ms": 0.8999999761581421,
      "memory_delta_bytes": 38595723.0,
      "render_success": true,
      "feature_count_match": true,
      "extent_match": true,
      "worker_process_ms": 0.0,
      "feature_convert_ms": 32.60000002384186,
      "first_visible_ms": 209.0
    },
    {
      "scenario": "direct-4999",
      "variant": "B",
      "feature_count": 4999,
      "fetch_ms": 76.39999997615814,
      "parse_ms": 13.100000023841858,
      "render_ms": 39.799999952316284,
      "interactive_ms": 293.89999997615814,
      "long_task_ms": 323.0,
      "pointer_delay_ms": 0.8999999761581421,
      "memory_delta_bytes": 38564387.0,
      "render_success": true,
      "feature_count_match": true,
      "extent_match": true,
      "worker_process_ms": 0.0,
      "feature_convert_ms": 27.300000071525574,
      "first_visible_ms": 188.29999995231628
    },
    {
      "scenario": "direct-5000",
      "variant": "A",
      "feature_count": 5000,
      "fetch_ms": 84.5,
      "parse_ms": 9.700000047683716,
      "render_ms": 57.09999990463257,
      "interactive_ms": 387.60000002384186,
      "long_task_ms": 538.0,
      "pointer_delay_ms": 1.399999976158142,
      "memory_delta_bytes": 38729963.0,
      "render_success": true,
      "feature_count_match": true,
      "extent_match": true,
      "worker_process_ms": 0.0,
      "feature_convert_ms": 45.299999952316284,
      "first_visible_ms": 239.89999997615814
    },
    {
      "scenario": "direct-5000",
      "variant": "B",
      "feature_count": 5000,
      "fetch_ms": 74.20000004768372,
      "parse_ms": 9.5,
      "render_ms": 39.60000002384186,
      "interactive_ms": 292.10000002384186,
      "long_task_ms": 304.0,
      "pointer_delay_ms": 1.1999999284744263,
      "memory_delta_bytes": 38740603.0,
      "render_success": true,
      "feature_count_match": true,
      "extent_match": true,
      "worker_process_ms": 0.0,
      "feature_convert_ms": 34.0,
      "first_visible_ms": 187.20000004768372
    },
    {
      "scenario": "worker-5001",
      "variant": "A",
      "feature_count": 5001,
      "fetch_ms": 67.69999992847443,
      "parse_ms": 7.400000095367432,
      "render_ms": 44.0,
      "interactive_ms": 274.7999999523163,
      "long_task_ms": 293.0,
      "pointer_delay_ms": 0.0,
      "memory_delta_bytes": 38592815.0,
      "render_success": true,
      "feature_count_match": true,
      "extent_match": true,
      "worker_process_ms": 0.0,
      "feature_convert_ms": 24.09999990463257,
      "first_visible_ms": 176.79999995231628
    },
    {
      "scenario": "worker-5001",
      "variant": "B",
      "feature_count": 5001,
      "fetch_ms": 66.80000007152557,
      "parse_ms": 0.0,
      "render_ms": 84.5,
      "interactive_ms": 322.2000000476837,
      "long_task_ms": 215.0,
      "pointer_delay_ms": 0.9000000953674316,
      "memory_delta_bytes": 42947916.0,
      "render_success": true,
      "feature_count_match": true,
      "extent_match": true,
      "worker_process_ms": 158.10000002384186,
      "feature_convert_ms": 11.600000023841858,
      "first_visible_ms": 227.89999997615814
    },
    {
      "scenario": "worker-10000",
      "variant": "A",
      "feature_count": 10000,
      "fetch_ms": 114.20000004768372,
      "parse_ms": 14.699999928474426,
      "render_ms": 53.40000009536743,
      "interactive_ms": 376.60000002384186,
      "long_task_ms": 382.0,
      "pointer_delay_ms": 0.0,
      "memory_delta_bytes": 48525405.0,
      "render_success": true,
      "feature_count_match": true,
      "extent_match": true,
      "worker_process_ms": 0.0,
      "feature_convert_ms": 53.40000009536743,
      "first_visible_ms": 273.8000000715256
    },
    {
      "scenario": "worker-10000",
      "variant": "B",
      "feature_count": 10000,
      "fetch_ms": 114.29999995231628,
      "parse_ms": 0.0,
      "render_ms": 146.20000004768372,
      "interactive_ms": 542.0,
      "long_task_ms": 237.0,
      "pointer_delay_ms": 0.0,
      "memory_delta_bytes": 46565102.0,
      "render_success": true,
      "feature_count_match": true,
      "extent_match": true,
      "worker_process_ms": 255.69999992847443,
      "feature_convert_ms": 10.899999976158142,
      "first_visible_ms": 320.89999997615814
    },
    {
      "scenario": "worker-29999",
      "variant": "A",
      "feature_count": 29999,
      "fetch_ms": 431.2000000476837,
      "parse_ms": 69.09999990463257,
      "render_ms": 165.79999995231628,
      "interactive_ms": 1240.5,
      "long_task_ms": 956.0,
      "pointer_delay_ms": 0.0,
      "memory_delta_bytes": 103081031.0,
      "render_success": true,
      "feature_count_match": true,
      "extent_match": true,
      "worker_process_ms": 0.0,
      "feature_convert_ms": 197.5,
      "first_visible_ms": 1043.6000000238419
    },
    {
      "scenario": "worker-29999",
      "variant": "B",
      "feature_count": 29999,
      "fetch_ms": 274.89999997615814,
      "parse_ms": 0.0,
      "render_ms": 57.5,
      "interactive_ms": 1089.2000000476837,
      "long_task_ms": 324.0,
      "pointer_delay_ms": 0.0,
      "memory_delta_bytes": 140478493.0,
      "render_success": true,
      "feature_count_match": true,
      "extent_match": true,
      "worker_process_ms": 574.6999999284744,
      "feature_convert_ms": 8.700000047683716,
      "first_visible_ms": 415.60000002384186
    },
    {
      "scenario": "worker-30000",
      "variant": "A",
      "feature_count": 30000,
      "fetch_ms": 262.3000000715256,
      "parse_ms": 45.39999997615814,
      "render_ms": 140.29999995231628,
      "interactive_ms": 987.8000000715256,
      "long_task_ms": 655.0,
      "pointer_delay_ms": 0.0,
      "memory_delta_bytes": 111100912.0,
      "render_success": true,
      "feature_count_match": true,
      "extent_match": true,
      "worker_process_ms": 0.0,
      "feature_convert_ms": 125.29999995231628,
      "first_visible_ms": 714.2000000476837
    },
    {
      "scenario": "worker-30000",
      "variant": "B",
      "feature_count": 30000,
      "fetch_ms": 326.0,
      "parse_ms": 0.0,
      "render_ms": 81.0,
      "interactive_ms": 1135.0,
      "long_task_ms": 382.0,
      "pointer_delay_ms": 0.0,
      "memory_delta_bytes": 141933977.0,
      "render_success": true,
      "feature_count_match": true,
      "extent_match": true,
      "worker_process_ms": 687.8999999761581,
      "feature_convert_ms": 12.200000047683716,
      "first_visible_ms": 523.6000000238419
    },
    {
      "scenario": "mvt-30001",
      "variant": "A",
      "feature_count": 30001,
      "fetch_ms": 262.6999999284744,
      "parse_ms": 50.200000047683716,
      "render_ms": 164.0,
      "interactive_ms": 1032.5,
      "long_task_ms": 712.0,
      "pointer_delay_ms": 0.0,
      "memory_delta_bytes": 110759316.0,
      "render_success": true,
      "feature_count_match": true,
      "extent_match": true,
      "worker_process_ms": 0.0,
      "feature_convert_ms": 147.39999997615814,
      "first_visible_ms": 768.3999999761581
    },
    {
      "scenario": "mvt-30001",
      "variant": "B",
      "feature_count": 30001,
      "fetch_ms": 0.10000002384185791,
      "parse_ms": 0.0,
      "render_ms": 49.89999997615814,
      "interactive_ms": 8814.600000023842,
      "long_task_ms": 262.0,
      "pointer_delay_ms": 0.0,
      "memory_delta_bytes": 46487987.0,
      "render_success": true,
      "feature_count_match": true,
      "extent_match": true,
      "worker_process_ms": 0.0,
      "feature_convert_ms": 0.0,
      "first_visible_ms": 8695.200000047684
    }
  ],
  "summaries": {
    "direct-4999": {
      "A": {
        "sample_count": 1,
        "median": {
          "fetch_ms": 88.10000002384186,
          "parse_ms": 8.099999904632568,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 32.60000002384186,
          "render_ms": 51.799999952316284,
          "first_visible_ms": 209.0,
          "interactive_ms": 344.7000000476837,
          "long_task_ms": 420.0,
          "pointer_delay_ms": 0.8999999761581421,
          "memory_delta_bytes": 38595723.0
        },
        "p95": {
          "fetch_ms": 88.10000002384186,
          "parse_ms": 8.099999904632568,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 32.60000002384186,
          "render_ms": 51.799999952316284,
          "first_visible_ms": 209.0,
          "interactive_ms": 344.7000000476837,
          "long_task_ms": 420.0,
          "pointer_delay_ms": 0.8999999761581421,
          "memory_delta_bytes": 38595723.0
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
          "fetch_ms": 76.39999997615814,
          "parse_ms": 13.100000023841858,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 27.300000071525574,
          "render_ms": 39.799999952316284,
          "first_visible_ms": 188.29999995231628,
          "interactive_ms": 293.89999997615814,
          "long_task_ms": 323.0,
          "pointer_delay_ms": 0.8999999761581421,
          "memory_delta_bytes": 38564387.0
        },
        "p95": {
          "fetch_ms": 76.39999997615814,
          "parse_ms": 13.100000023841858,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 27.300000071525574,
          "render_ms": 39.799999952316284,
          "first_visible_ms": 188.29999995231628,
          "interactive_ms": 293.89999997615814,
          "long_task_ms": 323.0,
          "pointer_delay_ms": 0.8999999761581421,
          "memory_delta_bytes": 38564387.0
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
          "fetch_ms": 84.5,
          "parse_ms": 9.700000047683716,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 45.299999952316284,
          "render_ms": 57.09999990463257,
          "first_visible_ms": 239.89999997615814,
          "interactive_ms": 387.60000002384186,
          "long_task_ms": 538.0,
          "pointer_delay_ms": 1.399999976158142,
          "memory_delta_bytes": 38729963.0
        },
        "p95": {
          "fetch_ms": 84.5,
          "parse_ms": 9.700000047683716,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 45.299999952316284,
          "render_ms": 57.09999990463257,
          "first_visible_ms": 239.89999997615814,
          "interactive_ms": 387.60000002384186,
          "long_task_ms": 538.0,
          "pointer_delay_ms": 1.399999976158142,
          "memory_delta_bytes": 38729963.0
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
          "fetch_ms": 74.20000004768372,
          "parse_ms": 9.5,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 34.0,
          "render_ms": 39.60000002384186,
          "first_visible_ms": 187.20000004768372,
          "interactive_ms": 292.10000002384186,
          "long_task_ms": 304.0,
          "pointer_delay_ms": 1.1999999284744263,
          "memory_delta_bytes": 38740603.0
        },
        "p95": {
          "fetch_ms": 74.20000004768372,
          "parse_ms": 9.5,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 34.0,
          "render_ms": 39.60000002384186,
          "first_visible_ms": 187.20000004768372,
          "interactive_ms": 292.10000002384186,
          "long_task_ms": 304.0,
          "pointer_delay_ms": 1.1999999284744263,
          "memory_delta_bytes": 38740603.0
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
          "fetch_ms": 67.69999992847443,
          "parse_ms": 7.400000095367432,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 24.09999990463257,
          "render_ms": 44.0,
          "first_visible_ms": 176.79999995231628,
          "interactive_ms": 274.7999999523163,
          "long_task_ms": 293.0,
          "pointer_delay_ms": 0.0,
          "memory_delta_bytes": 38592815.0
        },
        "p95": {
          "fetch_ms": 67.69999992847443,
          "parse_ms": 7.400000095367432,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 24.09999990463257,
          "render_ms": 44.0,
          "first_visible_ms": 176.79999995231628,
          "interactive_ms": 274.7999999523163,
          "long_task_ms": 293.0,
          "pointer_delay_ms": 0.0,
          "memory_delta_bytes": 38592815.0
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
          "fetch_ms": 66.80000007152557,
          "parse_ms": 0.0,
          "worker_process_ms": 158.10000002384186,
          "feature_convert_ms": 11.600000023841858,
          "render_ms": 84.5,
          "first_visible_ms": 227.89999997615814,
          "interactive_ms": 322.2000000476837,
          "long_task_ms": 215.0,
          "pointer_delay_ms": 0.9000000953674316,
          "memory_delta_bytes": 42947916.0
        },
        "p95": {
          "fetch_ms": 66.80000007152557,
          "parse_ms": 0.0,
          "worker_process_ms": 158.10000002384186,
          "feature_convert_ms": 11.600000023841858,
          "render_ms": 84.5,
          "first_visible_ms": 227.89999997615814,
          "interactive_ms": 322.2000000476837,
          "long_task_ms": 215.0,
          "pointer_delay_ms": 0.9000000953674316,
          "memory_delta_bytes": 42947916.0
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
          "fetch_ms": 114.20000004768372,
          "parse_ms": 14.699999928474426,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 53.40000009536743,
          "render_ms": 53.40000009536743,
          "first_visible_ms": 273.8000000715256,
          "interactive_ms": 376.60000002384186,
          "long_task_ms": 382.0,
          "pointer_delay_ms": 0.0,
          "memory_delta_bytes": 48525405.0
        },
        "p95": {
          "fetch_ms": 114.20000004768372,
          "parse_ms": 14.699999928474426,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 53.40000009536743,
          "render_ms": 53.40000009536743,
          "first_visible_ms": 273.8000000715256,
          "interactive_ms": 376.60000002384186,
          "long_task_ms": 382.0,
          "pointer_delay_ms": 0.0,
          "memory_delta_bytes": 48525405.0
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
          "fetch_ms": 114.29999995231628,
          "parse_ms": 0.0,
          "worker_process_ms": 255.69999992847443,
          "feature_convert_ms": 10.899999976158142,
          "render_ms": 146.20000004768372,
          "first_visible_ms": 320.89999997615814,
          "interactive_ms": 542.0,
          "long_task_ms": 237.0,
          "pointer_delay_ms": 0.0,
          "memory_delta_bytes": 46565102.0
        },
        "p95": {
          "fetch_ms": 114.29999995231628,
          "parse_ms": 0.0,
          "worker_process_ms": 255.69999992847443,
          "feature_convert_ms": 10.899999976158142,
          "render_ms": 146.20000004768372,
          "first_visible_ms": 320.89999997615814,
          "interactive_ms": 542.0,
          "long_task_ms": 237.0,
          "pointer_delay_ms": 0.0,
          "memory_delta_bytes": 46565102.0
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
          "fetch_ms": 431.2000000476837,
          "parse_ms": 69.09999990463257,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 197.5,
          "render_ms": 165.79999995231628,
          "first_visible_ms": 1043.6000000238419,
          "interactive_ms": 1240.5,
          "long_task_ms": 956.0,
          "pointer_delay_ms": 0.0,
          "memory_delta_bytes": 103081031.0
        },
        "p95": {
          "fetch_ms": 431.2000000476837,
          "parse_ms": 69.09999990463257,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 197.5,
          "render_ms": 165.79999995231628,
          "first_visible_ms": 1043.6000000238419,
          "interactive_ms": 1240.5,
          "long_task_ms": 956.0,
          "pointer_delay_ms": 0.0,
          "memory_delta_bytes": 103081031.0
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
          "fetch_ms": 274.89999997615814,
          "parse_ms": 0.0,
          "worker_process_ms": 574.6999999284744,
          "feature_convert_ms": 8.700000047683716,
          "render_ms": 57.5,
          "first_visible_ms": 415.60000002384186,
          "interactive_ms": 1089.2000000476837,
          "long_task_ms": 324.0,
          "pointer_delay_ms": 0.0,
          "memory_delta_bytes": 140478493.0
        },
        "p95": {
          "fetch_ms": 274.89999997615814,
          "parse_ms": 0.0,
          "worker_process_ms": 574.6999999284744,
          "feature_convert_ms": 8.700000047683716,
          "render_ms": 57.5,
          "first_visible_ms": 415.60000002384186,
          "interactive_ms": 1089.2000000476837,
          "long_task_ms": 324.0,
          "pointer_delay_ms": 0.0,
          "memory_delta_bytes": 140478493.0
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
          "fetch_ms": 262.3000000715256,
          "parse_ms": 45.39999997615814,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 125.29999995231628,
          "render_ms": 140.29999995231628,
          "first_visible_ms": 714.2000000476837,
          "interactive_ms": 987.8000000715256,
          "long_task_ms": 655.0,
          "pointer_delay_ms": 0.0,
          "memory_delta_bytes": 111100912.0
        },
        "p95": {
          "fetch_ms": 262.3000000715256,
          "parse_ms": 45.39999997615814,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 125.29999995231628,
          "render_ms": 140.29999995231628,
          "first_visible_ms": 714.2000000476837,
          "interactive_ms": 987.8000000715256,
          "long_task_ms": 655.0,
          "pointer_delay_ms": 0.0,
          "memory_delta_bytes": 111100912.0
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
          "fetch_ms": 326.0,
          "parse_ms": 0.0,
          "worker_process_ms": 687.8999999761581,
          "feature_convert_ms": 12.200000047683716,
          "render_ms": 81.0,
          "first_visible_ms": 523.6000000238419,
          "interactive_ms": 1135.0,
          "long_task_ms": 382.0,
          "pointer_delay_ms": 0.0,
          "memory_delta_bytes": 141933977.0
        },
        "p95": {
          "fetch_ms": 326.0,
          "parse_ms": 0.0,
          "worker_process_ms": 687.8999999761581,
          "feature_convert_ms": 12.200000047683716,
          "render_ms": 81.0,
          "first_visible_ms": 523.6000000238419,
          "interactive_ms": 1135.0,
          "long_task_ms": 382.0,
          "pointer_delay_ms": 0.0,
          "memory_delta_bytes": 141933977.0
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
          "fetch_ms": 262.6999999284744,
          "parse_ms": 50.200000047683716,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 147.39999997615814,
          "render_ms": 164.0,
          "first_visible_ms": 768.3999999761581,
          "interactive_ms": 1032.5,
          "long_task_ms": 712.0,
          "pointer_delay_ms": 0.0,
          "memory_delta_bytes": 110759316.0
        },
        "p95": {
          "fetch_ms": 262.6999999284744,
          "parse_ms": 50.200000047683716,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 147.39999997615814,
          "render_ms": 164.0,
          "first_visible_ms": 768.3999999761581,
          "interactive_ms": 1032.5,
          "long_task_ms": 712.0,
          "pointer_delay_ms": 0.0,
          "memory_delta_bytes": 110759316.0
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
          "fetch_ms": 0.10000002384185791,
          "parse_ms": 0.0,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 0.0,
          "render_ms": 49.89999997615814,
          "first_visible_ms": 8695.200000047684,
          "interactive_ms": 8814.600000023842,
          "long_task_ms": 262.0,
          "pointer_delay_ms": 0.0,
          "memory_delta_bytes": 46487987.0
        },
        "p95": {
          "fetch_ms": 0.10000002384185791,
          "parse_ms": 0.0,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 0.0,
          "render_ms": 49.89999997615814,
          "first_visible_ms": 8695.200000047684,
          "interactive_ms": 8814.600000023842,
          "long_task_ms": 262.0,
          "pointer_delay_ms": 0.0,
          "memory_delta_bytes": 46487987.0
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
