# GeoJSON 渲染 A/B 性能报告

> 本报告只接受实际浏览器采样结果，不预填性能数字。

- 生成时间：`2026-08-27T20:01:15.703415+00:00`
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
| direct-4999 | A | 1 | 247.60000002384186 | 247.60000002384186 | 1.0 | 1.0 | 1.0 |
| direct-4999 | B | 1 | 351.6999999284744 | 351.6999999284744 | 1.0 | 1.0 | 1.0 |
| direct-5000 | A | 1 | 239.70000004768372 | 239.70000004768372 | 1.0 | 1.0 | 1.0 |
| direct-5000 | B | 1 | 250.30000007152557 | 250.30000007152557 | 1.0 | 1.0 | 1.0 |
| worker-5001 | A | 1 | 260.10000002384186 | 260.10000002384186 | 1.0 | 1.0 | 1.0 |
| worker-5001 | B | 1 | 310.2999999523163 | 310.2999999523163 | 1.0 | 1.0 | 1.0 |
| worker-10000 | A | 1 | 511.59999990463257 | 511.59999990463257 | 1.0 | 1.0 | 1.0 |
| worker-10000 | B | 1 | 448.0 | 448.0 | 1.0 | 1.0 | 1.0 |
| worker-29999 | A | 1 | 909.3000000715256 | 909.3000000715256 | 1.0 | 1.0 | 1.0 |
| worker-29999 | B | 1 | 1010.8000000715256 | 1010.8000000715256 | 1.0 | 1.0 | 1.0 |
| worker-30000 | A | 1 | 1052.3999999761581 | 1052.3999999761581 | 1.0 | 1.0 | 1.0 |
| worker-30000 | B | 1 | 1232.0 | 1232.0 | 1.0 | 1.0 | 1.0 |
| mvt-30001 | A | 1 | 1004.7999999523163 | 1004.7999999523163 | 1.0 | 1.0 | 1.0 |
| mvt-30001 | B | 1 | 8106.699999928474 | 8106.699999928474 | 1.0 | 1.0 | 1.0 |

## A/B 变化

> 变化率为 B 相对 A 的 median：正数表示 B 更慢，负数表示 B 更快。没有两组真实样本时不生成比较行。

| scenario | metric | B 相对 A |
| --- | --- | ---: |
| direct-4999 | first_visible_ms | 61.1% |
| direct-4999 | interactive_ms | 42.0% |
| direct-4999 | long_task_ms | 47.3% |
| direct-5000 | first_visible_ms | 7.1% |
| direct-5000 | interactive_ms | 4.4% |
| direct-5000 | long_task_ms | 9.0% |
| worker-5001 | first_visible_ms | 30.1% |
| worker-5001 | interactive_ms | 19.3% |
| worker-5001 | long_task_ms | -12.4% |
| worker-10000 | first_visible_ms | -17.1% |
| worker-10000 | interactive_ms | -12.4% |
| worker-10000 | long_task_ms | -48.2% |
| worker-29999 | first_visible_ms | -38.6% |
| worker-29999 | interactive_ms | 11.2% |
| worker-29999 | long_task_ms | -52.2% |
| worker-30000 | first_visible_ms | -42.3% |
| worker-30000 | interactive_ms | 17.1% |
| worker-30000 | long_task_ms | -58.0% |
| mvt-30001 | first_visible_ms | 963.1% |
| mvt-30001 | interactive_ms | 706.8% |
| mvt-30001 | long_task_ms | -57.3% |

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
      "fetch_ms": 65.5,
      "parse_ms": 6.5,
      "render_ms": 32.700000047683716,
      "interactive_ms": 247.60000002384186,
      "long_task_ms": 220.0,
      "pointer_delay_ms": 0.7999999523162842,
      "memory_delta_bytes": 39186519.0,
      "render_success": true,
      "feature_count_match": true,
      "extent_match": true,
      "worker_process_ms": 0.0,
      "feature_convert_ms": 22.0,
      "first_visible_ms": 149.70000004768372
    },
    {
      "scenario": "direct-4999",
      "variant": "B",
      "feature_count": 4999,
      "fetch_ms": 105.59999990463257,
      "parse_ms": 11.5,
      "render_ms": 47.199999928474426,
      "interactive_ms": 351.6999999284744,
      "long_task_ms": 324.0,
      "pointer_delay_ms": 0.8999999761581421,
      "memory_delta_bytes": 38851447.0,
      "render_success": true,
      "feature_count_match": true,
      "extent_match": true,
      "worker_process_ms": 0.0,
      "feature_convert_ms": 42.89999997615814,
      "first_visible_ms": 241.09999990463257
    },
    {
      "scenario": "direct-5000",
      "variant": "A",
      "feature_count": 5000,
      "fetch_ms": 61.299999952316284,
      "parse_ms": 6.800000071525574,
      "render_ms": 33.799999952316284,
      "interactive_ms": 239.70000004768372,
      "long_task_ms": 255.0,
      "pointer_delay_ms": 0.8000000715255737,
      "memory_delta_bytes": 38621351.0,
      "render_success": true,
      "feature_count_match": true,
      "extent_match": true,
      "worker_process_ms": 0.0,
      "feature_convert_ms": 23.699999928474426,
      "first_visible_ms": 148.5
    },
    {
      "scenario": "direct-5000",
      "variant": "B",
      "feature_count": 5000,
      "fetch_ms": 62.89999997615814,
      "parse_ms": 7.0,
      "render_ms": 41.700000047683716,
      "interactive_ms": 250.30000007152557,
      "long_task_ms": 278.0,
      "pointer_delay_ms": 0.8999999761581421,
      "memory_delta_bytes": 38629067.0,
      "render_success": true,
      "feature_count_match": true,
      "extent_match": true,
      "worker_process_ms": 0.0,
      "feature_convert_ms": 23.200000047683716,
      "first_visible_ms": 159.10000002384186
    },
    {
      "scenario": "worker-5001",
      "variant": "A",
      "feature_count": 5001,
      "fetch_ms": 70.0,
      "parse_ms": 7.200000047683716,
      "render_ms": 37.5,
      "interactive_ms": 260.10000002384186,
      "long_task_ms": 266.0,
      "pointer_delay_ms": 0.8999999761581421,
      "memory_delta_bytes": 38464887.0,
      "render_success": true,
      "feature_count_match": true,
      "extent_match": true,
      "worker_process_ms": 0.0,
      "feature_convert_ms": 28.899999976158142,
      "first_visible_ms": 167.5
    },
    {
      "scenario": "worker-5001",
      "variant": "B",
      "feature_count": 5001,
      "fetch_ms": 62.5,
      "parse_ms": 0.0,
      "render_ms": 83.60000002384186,
      "interactive_ms": 310.2999999523163,
      "long_task_ms": 233.0,
      "pointer_delay_ms": 0.7999999523162842,
      "memory_delta_bytes": 36927556.0,
      "render_success": true,
      "feature_count_match": true,
      "extent_match": true,
      "worker_process_ms": 153.5,
      "feature_convert_ms": 8.900000095367432,
      "first_visible_ms": 217.89999997615814
    },
    {
      "scenario": "worker-10000",
      "variant": "A",
      "feature_count": 10000,
      "fetch_ms": 119.0,
      "parse_ms": 15.600000023841858,
      "render_ms": 80.60000002384186,
      "interactive_ms": 511.59999990463257,
      "long_task_ms": 483.0,
      "pointer_delay_ms": 0.0,
      "memory_delta_bytes": 48178598.0,
      "render_success": true,
      "feature_count_match": true,
      "extent_match": true,
      "worker_process_ms": 0.0,
      "feature_convert_ms": 72.60000002384186,
      "first_visible_ms": 346.59999990463257
    },
    {
      "scenario": "worker-10000",
      "variant": "B",
      "feature_count": 10000,
      "fetch_ms": 113.30000007152557,
      "parse_ms": 0.0,
      "render_ms": 127.80000007152557,
      "interactive_ms": 448.0,
      "long_task_ms": 250.0,
      "pointer_delay_ms": 0.0,
      "memory_delta_bytes": 46491458.0,
      "render_success": true,
      "feature_count_match": true,
      "extent_match": true,
      "worker_process_ms": 224.0,
      "feature_convert_ms": 9.799999952316284,
      "first_visible_ms": 287.40000009536743
    },
    {
      "scenario": "worker-29999",
      "variant": "A",
      "feature_count": 29999,
      "fetch_ms": 270.0,
      "parse_ms": 47.199999928474426,
      "render_ms": 119.59999990463257,
      "interactive_ms": 909.3000000715256,
      "long_task_ms": 613.0,
      "pointer_delay_ms": 0.0,
      "memory_delta_bytes": 110807499.0,
      "render_success": true,
      "feature_count_match": true,
      "extent_match": true,
      "worker_process_ms": 0.0,
      "feature_convert_ms": 136.30000007152557,
      "first_visible_ms": 682.8999999761581
    },
    {
      "scenario": "worker-29999",
      "variant": "B",
      "feature_count": 29999,
      "fetch_ms": 263.7000000476837,
      "parse_ms": 0.0,
      "render_ms": 70.10000002384186,
      "interactive_ms": 1010.8000000715256,
      "long_task_ms": 293.0,
      "pointer_delay_ms": 0.0,
      "memory_delta_bytes": 125976641.0,
      "render_success": true,
      "feature_count_match": true,
      "extent_match": true,
      "worker_process_ms": 551.2999999523163,
      "feature_convert_ms": 9.600000023841858,
      "first_visible_ms": 419.2000000476837
    },
    {
      "scenario": "worker-30000",
      "variant": "A",
      "feature_count": 30000,
      "fetch_ms": 324.1999999284744,
      "parse_ms": 63.0,
      "render_ms": 132.10000002384186,
      "interactive_ms": 1052.3999999761581,
      "long_task_ms": 765.0,
      "pointer_delay_ms": 0.0,
      "memory_delta_bytes": 110954316.0,
      "render_success": true,
      "feature_count_match": true,
      "extent_match": true,
      "worker_process_ms": 0.0,
      "feature_convert_ms": 154.19999992847443,
      "first_visible_ms": 818.7999999523163
    },
    {
      "scenario": "worker-30000",
      "variant": "B",
      "feature_count": 30000,
      "fetch_ms": 255.69999992847443,
      "parse_ms": 0.0,
      "render_ms": 125.29999995231628,
      "interactive_ms": 1232.0,
      "long_task_ms": 321.0,
      "pointer_delay_ms": 0.0,
      "memory_delta_bytes": 126467469.0,
      "render_success": true,
      "feature_count_match": true,
      "extent_match": true,
      "worker_process_ms": 751.0,
      "feature_convert_ms": 10.0,
      "first_visible_ms": 472.09999990463257
    },
    {
      "scenario": "mvt-30001",
      "variant": "A",
      "feature_count": 30001,
      "fetch_ms": 267.6999999284744,
      "parse_ms": 48.90000009536743,
      "render_ms": 163.89999997615814,
      "interactive_ms": 1004.7999999523163,
      "long_task_ms": 702.0,
      "pointer_delay_ms": 0.0,
      "memory_delta_bytes": 111161364.0,
      "render_success": true,
      "feature_count_match": true,
      "extent_match": true,
      "worker_process_ms": 0.0,
      "feature_convert_ms": 135.80000007152557,
      "first_visible_ms": 751.1000000238419
    },
    {
      "scenario": "mvt-30001",
      "variant": "B",
      "feature_count": 30001,
      "fetch_ms": 0.19999992847442627,
      "parse_ms": 0.0,
      "render_ms": 59.89999997615814,
      "interactive_ms": 8106.699999928474,
      "long_task_ms": 300.0,
      "pointer_delay_ms": 0.0,
      "memory_delta_bytes": 46490495.0,
      "render_success": true,
      "feature_count_match": true,
      "extent_match": true,
      "worker_process_ms": 0.0,
      "feature_convert_ms": 0.0,
      "first_visible_ms": 7984.599999904633
    }
  ],
  "summaries": {
    "direct-4999": {
      "A": {
        "sample_count": 1,
        "median": {
          "fetch_ms": 65.5,
          "parse_ms": 6.5,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 22.0,
          "render_ms": 32.700000047683716,
          "first_visible_ms": 149.70000004768372,
          "interactive_ms": 247.60000002384186,
          "long_task_ms": 220.0,
          "pointer_delay_ms": 0.7999999523162842,
          "memory_delta_bytes": 39186519.0
        },
        "p95": {
          "fetch_ms": 65.5,
          "parse_ms": 6.5,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 22.0,
          "render_ms": 32.700000047683716,
          "first_visible_ms": 149.70000004768372,
          "interactive_ms": 247.60000002384186,
          "long_task_ms": 220.0,
          "pointer_delay_ms": 0.7999999523162842,
          "memory_delta_bytes": 39186519.0
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
          "fetch_ms": 105.59999990463257,
          "parse_ms": 11.5,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 42.89999997615814,
          "render_ms": 47.199999928474426,
          "first_visible_ms": 241.09999990463257,
          "interactive_ms": 351.6999999284744,
          "long_task_ms": 324.0,
          "pointer_delay_ms": 0.8999999761581421,
          "memory_delta_bytes": 38851447.0
        },
        "p95": {
          "fetch_ms": 105.59999990463257,
          "parse_ms": 11.5,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 42.89999997615814,
          "render_ms": 47.199999928474426,
          "first_visible_ms": 241.09999990463257,
          "interactive_ms": 351.6999999284744,
          "long_task_ms": 324.0,
          "pointer_delay_ms": 0.8999999761581421,
          "memory_delta_bytes": 38851447.0
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
          "fetch_ms": 61.299999952316284,
          "parse_ms": 6.800000071525574,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 23.699999928474426,
          "render_ms": 33.799999952316284,
          "first_visible_ms": 148.5,
          "interactive_ms": 239.70000004768372,
          "long_task_ms": 255.0,
          "pointer_delay_ms": 0.8000000715255737,
          "memory_delta_bytes": 38621351.0
        },
        "p95": {
          "fetch_ms": 61.299999952316284,
          "parse_ms": 6.800000071525574,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 23.699999928474426,
          "render_ms": 33.799999952316284,
          "first_visible_ms": 148.5,
          "interactive_ms": 239.70000004768372,
          "long_task_ms": 255.0,
          "pointer_delay_ms": 0.8000000715255737,
          "memory_delta_bytes": 38621351.0
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
          "fetch_ms": 62.89999997615814,
          "parse_ms": 7.0,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 23.200000047683716,
          "render_ms": 41.700000047683716,
          "first_visible_ms": 159.10000002384186,
          "interactive_ms": 250.30000007152557,
          "long_task_ms": 278.0,
          "pointer_delay_ms": 0.8999999761581421,
          "memory_delta_bytes": 38629067.0
        },
        "p95": {
          "fetch_ms": 62.89999997615814,
          "parse_ms": 7.0,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 23.200000047683716,
          "render_ms": 41.700000047683716,
          "first_visible_ms": 159.10000002384186,
          "interactive_ms": 250.30000007152557,
          "long_task_ms": 278.0,
          "pointer_delay_ms": 0.8999999761581421,
          "memory_delta_bytes": 38629067.0
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
          "fetch_ms": 70.0,
          "parse_ms": 7.200000047683716,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 28.899999976158142,
          "render_ms": 37.5,
          "first_visible_ms": 167.5,
          "interactive_ms": 260.10000002384186,
          "long_task_ms": 266.0,
          "pointer_delay_ms": 0.8999999761581421,
          "memory_delta_bytes": 38464887.0
        },
        "p95": {
          "fetch_ms": 70.0,
          "parse_ms": 7.200000047683716,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 28.899999976158142,
          "render_ms": 37.5,
          "first_visible_ms": 167.5,
          "interactive_ms": 260.10000002384186,
          "long_task_ms": 266.0,
          "pointer_delay_ms": 0.8999999761581421,
          "memory_delta_bytes": 38464887.0
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
          "fetch_ms": 62.5,
          "parse_ms": 0.0,
          "worker_process_ms": 153.5,
          "feature_convert_ms": 8.900000095367432,
          "render_ms": 83.60000002384186,
          "first_visible_ms": 217.89999997615814,
          "interactive_ms": 310.2999999523163,
          "long_task_ms": 233.0,
          "pointer_delay_ms": 0.7999999523162842,
          "memory_delta_bytes": 36927556.0
        },
        "p95": {
          "fetch_ms": 62.5,
          "parse_ms": 0.0,
          "worker_process_ms": 153.5,
          "feature_convert_ms": 8.900000095367432,
          "render_ms": 83.60000002384186,
          "first_visible_ms": 217.89999997615814,
          "interactive_ms": 310.2999999523163,
          "long_task_ms": 233.0,
          "pointer_delay_ms": 0.7999999523162842,
          "memory_delta_bytes": 36927556.0
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
          "fetch_ms": 119.0,
          "parse_ms": 15.600000023841858,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 72.60000002384186,
          "render_ms": 80.60000002384186,
          "first_visible_ms": 346.59999990463257,
          "interactive_ms": 511.59999990463257,
          "long_task_ms": 483.0,
          "pointer_delay_ms": 0.0,
          "memory_delta_bytes": 48178598.0
        },
        "p95": {
          "fetch_ms": 119.0,
          "parse_ms": 15.600000023841858,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 72.60000002384186,
          "render_ms": 80.60000002384186,
          "first_visible_ms": 346.59999990463257,
          "interactive_ms": 511.59999990463257,
          "long_task_ms": 483.0,
          "pointer_delay_ms": 0.0,
          "memory_delta_bytes": 48178598.0
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
          "fetch_ms": 113.30000007152557,
          "parse_ms": 0.0,
          "worker_process_ms": 224.0,
          "feature_convert_ms": 9.799999952316284,
          "render_ms": 127.80000007152557,
          "first_visible_ms": 287.40000009536743,
          "interactive_ms": 448.0,
          "long_task_ms": 250.0,
          "pointer_delay_ms": 0.0,
          "memory_delta_bytes": 46491458.0
        },
        "p95": {
          "fetch_ms": 113.30000007152557,
          "parse_ms": 0.0,
          "worker_process_ms": 224.0,
          "feature_convert_ms": 9.799999952316284,
          "render_ms": 127.80000007152557,
          "first_visible_ms": 287.40000009536743,
          "interactive_ms": 448.0,
          "long_task_ms": 250.0,
          "pointer_delay_ms": 0.0,
          "memory_delta_bytes": 46491458.0
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
          "fetch_ms": 270.0,
          "parse_ms": 47.199999928474426,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 136.30000007152557,
          "render_ms": 119.59999990463257,
          "first_visible_ms": 682.8999999761581,
          "interactive_ms": 909.3000000715256,
          "long_task_ms": 613.0,
          "pointer_delay_ms": 0.0,
          "memory_delta_bytes": 110807499.0
        },
        "p95": {
          "fetch_ms": 270.0,
          "parse_ms": 47.199999928474426,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 136.30000007152557,
          "render_ms": 119.59999990463257,
          "first_visible_ms": 682.8999999761581,
          "interactive_ms": 909.3000000715256,
          "long_task_ms": 613.0,
          "pointer_delay_ms": 0.0,
          "memory_delta_bytes": 110807499.0
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
          "fetch_ms": 263.7000000476837,
          "parse_ms": 0.0,
          "worker_process_ms": 551.2999999523163,
          "feature_convert_ms": 9.600000023841858,
          "render_ms": 70.10000002384186,
          "first_visible_ms": 419.2000000476837,
          "interactive_ms": 1010.8000000715256,
          "long_task_ms": 293.0,
          "pointer_delay_ms": 0.0,
          "memory_delta_bytes": 125976641.0
        },
        "p95": {
          "fetch_ms": 263.7000000476837,
          "parse_ms": 0.0,
          "worker_process_ms": 551.2999999523163,
          "feature_convert_ms": 9.600000023841858,
          "render_ms": 70.10000002384186,
          "first_visible_ms": 419.2000000476837,
          "interactive_ms": 1010.8000000715256,
          "long_task_ms": 293.0,
          "pointer_delay_ms": 0.0,
          "memory_delta_bytes": 125976641.0
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
          "fetch_ms": 324.1999999284744,
          "parse_ms": 63.0,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 154.19999992847443,
          "render_ms": 132.10000002384186,
          "first_visible_ms": 818.7999999523163,
          "interactive_ms": 1052.3999999761581,
          "long_task_ms": 765.0,
          "pointer_delay_ms": 0.0,
          "memory_delta_bytes": 110954316.0
        },
        "p95": {
          "fetch_ms": 324.1999999284744,
          "parse_ms": 63.0,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 154.19999992847443,
          "render_ms": 132.10000002384186,
          "first_visible_ms": 818.7999999523163,
          "interactive_ms": 1052.3999999761581,
          "long_task_ms": 765.0,
          "pointer_delay_ms": 0.0,
          "memory_delta_bytes": 110954316.0
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
          "fetch_ms": 255.69999992847443,
          "parse_ms": 0.0,
          "worker_process_ms": 751.0,
          "feature_convert_ms": 10.0,
          "render_ms": 125.29999995231628,
          "first_visible_ms": 472.09999990463257,
          "interactive_ms": 1232.0,
          "long_task_ms": 321.0,
          "pointer_delay_ms": 0.0,
          "memory_delta_bytes": 126467469.0
        },
        "p95": {
          "fetch_ms": 255.69999992847443,
          "parse_ms": 0.0,
          "worker_process_ms": 751.0,
          "feature_convert_ms": 10.0,
          "render_ms": 125.29999995231628,
          "first_visible_ms": 472.09999990463257,
          "interactive_ms": 1232.0,
          "long_task_ms": 321.0,
          "pointer_delay_ms": 0.0,
          "memory_delta_bytes": 126467469.0
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
          "fetch_ms": 267.6999999284744,
          "parse_ms": 48.90000009536743,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 135.80000007152557,
          "render_ms": 163.89999997615814,
          "first_visible_ms": 751.1000000238419,
          "interactive_ms": 1004.7999999523163,
          "long_task_ms": 702.0,
          "pointer_delay_ms": 0.0,
          "memory_delta_bytes": 111161364.0
        },
        "p95": {
          "fetch_ms": 267.6999999284744,
          "parse_ms": 48.90000009536743,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 135.80000007152557,
          "render_ms": 163.89999997615814,
          "first_visible_ms": 751.1000000238419,
          "interactive_ms": 1004.7999999523163,
          "long_task_ms": 702.0,
          "pointer_delay_ms": 0.0,
          "memory_delta_bytes": 111161364.0
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
          "fetch_ms": 0.19999992847442627,
          "parse_ms": 0.0,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 0.0,
          "render_ms": 59.89999997615814,
          "first_visible_ms": 7984.599999904633,
          "interactive_ms": 8106.699999928474,
          "long_task_ms": 300.0,
          "pointer_delay_ms": 0.0,
          "memory_delta_bytes": 46490495.0
        },
        "p95": {
          "fetch_ms": 0.19999992847442627,
          "parse_ms": 0.0,
          "worker_process_ms": 0.0,
          "feature_convert_ms": 0.0,
          "render_ms": 59.89999997615814,
          "first_visible_ms": 7984.599999904633,
          "interactive_ms": 8106.699999928474,
          "long_task_ms": 300.0,
          "pointer_delay_ms": 0.0,
          "memory_delta_bytes": 46490495.0
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
