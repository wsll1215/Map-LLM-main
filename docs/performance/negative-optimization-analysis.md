# Worker 与 MVT 负向结果诊断

最后更新：2026-08-28

## 结论

“优化”不是所有指标都必然下降。当前实现的目标是先让主线程可响应，再完成全部要素；因此必须同时看：首个可见结果、输入响应、完整加载耗时和 Long Task。把 `long_task_ms` 下降直接等同于端到端交互变快，会得到错误结论。

## 已确认根因

### 旧阈值实验：Worker 在 5001 个要素时变慢

Worker 只承担 `TextDecoder`、`JSON.parse`、GeoJSON 基础校验和分批，OpenLayers 的 `readFeatures`、`VectorSource.addFeatures` 以及 Canvas 绘制仍由主线程完成。代码路径见：

- `frontend/src/workers/geojsonParser.worker.ts`：Worker 在发送首批前完成整个 JSON 解码和解析。
- `frontend/src/hooks/useOpenLayersMap.ts`：主线程把批次转换为 OpenLayers Feature 并加入 VectorSource。
- `frontend/src/map/renderers.ts`：后续批次使用空闲调度，避免持续占用输入优先级。

5001 个要素时，Worker 初始化、跨线程消息复制和分批调度的固定成本，大于主线程一次性直载的成本。因此旧实验出现了 Long Task 下降但 `interactive_ms` 上升。这是该规模下的真实成本，不是可以用百分比包装掉的收益。该结果促成了阈值重新校准，当前生产策略已不再在 5001 个要素时启用 Worker。

### Worker 在 10000 个要素时的改进

此前每个批次都显式调用 `map.render()`，造成数据源变更已经会触发一次渲染的情况下又重复安排地图绘制。现已移除重复调用，并让首批使用 rAF、后续批次使用 `requestIdleCallback({ timeout: 100 })`，浏览器不支持时回退到 rAF。这样保留增量可见性，同时给 pointer/wheel 输入让出调度机会。

### MVT 旧报告变慢的原因

旧报告中的 MVT 结果不是可靠的生产结论，原因有两层：

1. 前端使用了默认瓦片粒度，导致请求级别和测试预期不一致。
2. 基准把大量合成要素集中到少数巨型瓦片，测量的是异常瓦片解码，而不是当前视口的懒加载。

当前代码显式使用 256px tile grid，基准在固定 z11 范围内按可见瓦片分布数据，并把正确性范围标记为 `visible_tiles`。因此 MVT 的 `feature_count_match` 不能解释成“全量数据已加载”，只能解释成“当前可见瓦片有有效结果”。

## 当前复测证据

已按正式配置完成 5 次预热、30 次正式采样，共 9 个规模、18 个 A/B 组、540 条样本。完整原始数据和报告：

- `tests/performance/observations-final-after-threshold.json`
- `docs/performance/render-ab-report-after-threshold.md`

| 要素数 | A 交互 median | B 交互 median | 交互变化 | Long Task 变化 | B 策略 |
|---:|---:|---:|---:|---:|---|
| 4999 | 263.7ms | 252.3ms | -4.3% | -11.5% | direct |
| 5000 | 274.3ms | 317.1ms | +15.6% | +13.8% | direct |
| 7999 | 323.2ms | 303.0ms | -6.2% | -2.0% | direct |
| 8000 | 382.6ms | 288.0ms | -24.7% | -23.1% | direct |
| 8001 | 344.4ms | 320.6ms | -6.9% | -50.1% | Worker |
| 10000 | 325.5ms | 314.8ms | -3.3% | -42.4% | Worker |
| 29999 | 1126.3ms | 647.0ms | -42.6% | -71.2% | Worker |
| 30000 | 1141.3ms | 647.0ms | -43.3% | -69.3% | Worker |
| 30001 | 1153.8ms | 344.4ms | -70.2% | -69.3% | MVT |

`render_success`、`feature_count_match`、`extent_match` 三项在 540/540 条样本中均为通过。候选实验在 7500 时仍比 direct 慢 32.5%，在 8000 时已快 12.1%；正式复测进一步确认 8000 的直载策略稳定，8001 开始启用 Worker 后交互耗时降低 6.9%，Long Task 降低 50.1%。MVT 的正确性口径仍是当前可见瓦片。

## 工程决策

- 当前固定阈值为 `<=8000` 直载、`8001-30000` Worker、`>30000` MVT；正式实验覆盖 4999、5000、7999、8000、8001、10000、29999、30000、30001。
- 生产策略不应承诺 Worker 在所有规模都降低端到端耗时；8000 是当前固定 LineString 合成数据和测试环境下的最小稳定交叉点。
- 如果产品目标是“最短完成时间”，应后续基于设备、几何复杂度、JSON 字节数和实测成本校准阈值，而不是只用 feature count。
- MVT 与全量 GeoJSON 的比较必须同时展示 `correctness_scope`，不能把懒加载的可见瓦片时间与全量加载完成时间混作同一个指标。

## 验证

- `frontend`: `npm run test -- --run`，113 passed。
- `frontend`: `npm run build`，通过。
- 后端全量测试：350 passed。
- `python manage.py check`，通过。
