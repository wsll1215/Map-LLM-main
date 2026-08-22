# 地图渲染性能改造设计

## 1. 背景与目标

当前工作台使用 React + OpenLayers 渲染实时地图，后端使用 GeoPandas/Matplotlib 生成最终 PNG。实时事件由 Django SSE 发布，经 Redis 中转。现有实现适合小规模图层，但存在三个性能瓶颈：

1. SSE 事件会重复携带受限 GeoJSON，造成网络、Redis 和浏览器内存浪费。
2. OpenLayers 在主线程解析 GeoJSON，并在每次状态变化时清空和重建图层。
3. 前端 OpenLayers 和后端 Matplotlib 各自解释样式、CRS 和范围，长期存在结果不一致风险。

本次改造采用分级混合方案，目标是：

- 使用一份地图规格驱动实时预览和最终导出。
- SSE 只传任务状态和版本变化，空间数据通过 HTTP 按需获取。
- 小数据保持 GeoJSON 的简单链路，中等数据使用 Web Worker，大数据使用 MVT，静态超大图层支持 PMTiles。
- 图层样式、CRS、范围和版本更新采用增量策略，避免无意义重建。
- 保持现有 Agent 和最终 PNG 能力，分阶段上线并可回退。

本设计只覆盖地图数据传输、前端渲染、后端缓存和大数据格式。Agent 调度迁移到 Celery/RQ、PostGIS 全量迁移和多人协作属于后续项目。

## 2. 设计原则

- **MapSpec 是唯一渲染输入**：OpenLayers 和 Matplotlib 都消费同一份规范化地图配置。
- **SSE 传事件，HTTP 传数据**：SSE 不携带完整 GeoJSON 或瓦片二进制。
- **按规模选择渲染器**：不让小图层承担瓦片服务的复杂度，也不让大图层走完整 GeoJSON。
- **版本优先于时序**：所有地图、图层和数据响应都带版本；过期响应必须丢弃。
- **数据与状态分离**：地图规格、图层数据、生成成果和实时事件分别管理。
- **渐进式改造**：默认先保持 GeoJSON 兼容，再按功能开关启用 Worker、MVT 和 PMTiles。

## 3. 统一数据模型

现有 `gis_mapping_agent/specs/map_spec.py` 的 `MapSpec` 作为领域模型基础，扩展为前后端传输规范。字段名称需要从 Matplotlib 风格逐步归一化，兼容期内由后端适配旧字段。

### 3.1 MapSpec

```json
{
  "schema_version": 1,
  "map_id": "map_23",
  "version": 4,
  "title": "北京市行政区划图",
  "crs": "EPSG:4326",
  "display_crs": "EPSG:3857",
  "extent": [115.4, 39.4, 117.5, 41.1],
  "background": "#ffffff",
  "layers": [],
  "annotations": [],
  "decorations": {
    "legend": true,
    "scalebar": true,
    "north_arrow": true
  }
}
```

MapSpec 只存配置和数据引用，不存完整 FeatureCollection、OpenLayers 对象、Matplotlib Figure 或数据库连接对象。

### 3.2 统一样式

```json
{
  "fill": "#dcefe4",
  "stroke": "#166534",
  "stroke_width": 2,
  "opacity": 0.9,
  "line_dash": [],
  "point_radius": 5,
  "label": {
    "field": "name",
    "font_family": "Microsoft YaHei",
    "font_size": 12,
    "color": "#172033"
  }
}
```

实现两个适配器：

- `MapSpecStyle -> OpenLayers Style`
- `MapSpecStyle -> Matplotlib Style`

两端可以存在抗锯齿、字体和布局差异，但必须共享颜色、透明度、线宽、图层顺序、标注字段、CRS 和 extent 规则。

### 3.3 LayerManifest

```json
{
  "id": "beijing-boundary",
  "version": 3,
  "name": "北京市行政区划",
  "geometry_type": "Polygon",
  "feature_count": 16,
  "extent": [115.4, 39.4, 117.5, 41.1],
  "data_hash": "sha256:...",
  "render_mode": "geojson",
  "data_url": "/mapping/api/jobs/23/layers/beijing-boundary/"
}
```

`render_mode` 的合法值为 `geojson`、`geojson-worker`、`mvt` 和 `pmtiles`。后端依据配置阈值和数据元信息决定模式，前端只执行模式，不自行猜测。

## 4. 分级渲染策略

| 数据规模 | 方式 | 说明 |
| --- | --- | --- |
| 小于 5,000 要素 | GeoJSON | 主线程直接加载，链路简单 |
| 5,000 至 50,000 | GeoJSON + Worker | Worker 解析、过滤、简化和计算范围 |
| 50,000 至 100,000 | 简化 GeoJSON + Worker | 必须限制数据大小并分批回传 |
| 超过 100,000 | MVT | 按视口和缩放级别加载 |
| 超大静态图层 | PMTiles | 适合发布型、低变更数据 |

阈值通过环境配置控制：

```text
MAP_GEOJSON_LIMIT=5000
MAP_WORKER_LIMIT=100000
MAP_MVT_ENABLED=true
MAP_PM_TILES_ENABLED=true
```

最终 PNG 始终使用后端原始或高精度派生数据，不使用前端低精度预览结果。

## 5. API 与通信协议

### 5.1 接口

```text
POST /mapping/api/jobs/
GET  /mapping/api/jobs/{id}/events/
GET  /mapping/api/jobs/{id}/snapshot/
GET  /mapping/api/jobs/{id}/layers/{layer_id}/
GET  /mapping/api/jobs/{id}/layers/{layer_id}/tiles/{z}/{x}/{y}.pbf
GET  /mapping/api/jobs/{id}/artifacts/
```

创建任务立即返回 `job_id`、`snapshot_url` 和 `events_url`。快照返回 MapSpec 与 LayerManifest，不返回大体量几何。

### 5.2 SSE 事件

```json
{
  "event": "layer_updated",
  "job_id": 23,
  "map_version": 4,
  "layer_id": "beijing-boundary",
  "layer_version": 3,
  "snapshot_version": 4
}
```

事件类型包括：`job_started`、`job_progress`、`map_spec_updated`、`layer_added`、`layer_updated`、`layer_removed`、`validation_warning`、`artifact_created`、`job_completed` 和 `job_failed`。

SSE 禁止携带完整 GeoJSON、重复的全量图层和二进制成果。前端收到事件后通过 HTTP 获取快照或指定图层。

### 5.3 一致性规则

- 每个任务、MapSpec 和图层都有递增版本。
- 前端只接受不低于当前版本的响应。
- 数据请求使用 AbortController；新版本到达时取消旧请求。
- SSE 断线后先恢复 snapshot，再从 Last-Event-ID 继续接收事件。
- 重复事件按 `event_id + version` 幂等处理。

## 6. Web Worker 设计

新增：

```text
frontend/src/workers/geojsonParser.worker.ts
frontend/src/map/workerProtocol.ts
frontend/src/hooks/useMapData.ts
```

Worker 负责纯数据操作：JSON 解析、空几何过滤、几何简化、坐标转换、extent 计算和分批返回。Worker 不创建 OpenLayers Map、Layer、Style 或 DOM 对象。

主线程接收可序列化几何数据后创建 OpenLayers Feature。中间结果按批次返回，避免一次性阻塞主线程。可以传输的 `ArrayBuffer` 必须使用 Transferable Object，避免结构化复制。

Worker 生命周期：

1. 地图组件初始化时创建。
2. 新图层版本到达时取消旧任务。
3. 页面卸载时 `terminate()`。
4. 超时、解析异常和版本过期都返回明确错误。
5. 只接受当前 `layerVersion` 的结果。

## 7. 前端模块边界

```text
frontend/src/workers/geojsonParser.worker.ts
frontend/src/map/layerRegistry.ts
frontend/src/map/mapDataLoader.ts
frontend/src/map/renderPolicy.ts
frontend/src/map/styleAdapter.ts
frontend/src/hooks/useMapData.ts
frontend/src/hooks/useMapBuildStream.ts
frontend/src/hooks/useOpenLayersMap.ts
```

- `useMapBuildStream`：只负责 SSE 连接、重连和事件派发。
- `useMapData`：负责 HTTP 图层数据、缓存、取消和 Worker 调度。
- `renderPolicy`：根据 LayerManifest 选择渲染模式。
- `layerRegistry`：保存图层运行时对象、版本、哈希和加载状态。
- `useOpenLayersMap`：只管理地图实例、图层实例、样式、显隐和顺序。
- `styleAdapter`：把统一 MapSpec 样式转换为 OpenLayers 样式。

地图实例和拖动中的临时数据放入 `useRef`。日志、任务状态和图层控制拆分，避免日志更新触发地图重渲染。`MapCanvas`、图层控制组件和昂贵的结果组件使用 `React.memo`，保持现有的动态加载。

## 8. OpenLayers 增量更新

图层不存在时创建 Layer 和 Source；图层版本改变时重新加载几何；仅修改样式时调用 `setStyle`；仅修改显隐时调用 `setVisible`；仅修改顺序时调整 `zIndex`。

不再对每次状态变化执行 `source.clear()`、`readFeatures()` 和 `fit()`。自动适应范围只在首次加载、切换全新地图或用户主动点击“适应地图”时执行。用户拖动或缩放后，后续图层更新不能重置视图。

每个图层运行时状态至少包括：`layerId`、`version`、`dataHash`、`loaded`、`loading`、`failed`、`extent` 和 `featureCount`。

## 9. 后端数据处理、简化与缓存

当前 `DataLoader` 的路径缓存升级为基于文件内容的缓存。缓存键包含：文件路径、文件大小、mtime、文件哈希、目标 CRS、简化等级、输出格式和图层版本。

处理管线：

```text
读取源数据
  ↓
CRS 校验与标准化
  ↓
几何有效性检查
  ↓
按缩放级别简化
  ↓
生成 GeoJSON / MVT / PMTiles
  ↓
写入磁盘缓存
  ↓
生成 LayerManifest
```

建议缓存目录：

```text
outputs/cache/map-data/
outputs/cache/geojson/
outputs/cache/mvt/
outputs/cache/pmtiles/
```

Redis 只存缓存索引、任务锁、实时事件和短期元数据，不存大体量 GeoJSON 或永久成果。

## 10. MVT 与 PMTiles

第一阶段兼容当前文件系统：后端根据 GeoDataFrame 生成并缓存 MVT 瓦片，Django 返回 `.pbf`。第二阶段迁移 PostGIS，使用空间索引和 `ST_AsMVT` 生成瓦片。

PMTiles 只用于静态、低变更、超大图层。动态编辑图层和频繁变更图层继续使用 GeoJSON 或 MVT，不直接使用 PMTiles。

## 11. 校验与错误反馈

生成 LayerManifest 前必须校验：文件存在、CRS 存在且可转换、几何有效、bbox 合理、feature_count 正确、图层类型匹配以及数据是否超限。

错误和警告通过 SSE 发送，并在快照中持久化：

```json
{
  "event": "validation_warning",
  "layer_id": "roads",
  "code": "INVALID_GEOMETRY",
  "message": "道路图层存在 238 个无效几何，已跳过"
}
```

前端需要展示加载中、空图层、解析失败、Worker 超时、瓦片失败和最终成果失败，不能让用户无反馈等待。

## 12. 存储和成果

地图配置、图层数据和成果分离：

```text
MapSpec       配置和版本
LayerData     GeoJSON、MVT、PMTiles 或源数据引用
Artifact      PNG、PDF、SVG、GeoJSON、GeoTIFF
Event         任务实时事件
```

成果接口返回文件类型、URL、大小、版本和 SHA-256。现有 `generated_maps` 文件结构保持兼容，新增成果清单字段，避免数据库显示成功但文件已经不存在。

## 13. 实施阶段

### P1.1 协议和增量更新

1. 扩展 MapSpec，定义 LayerManifest。
2. 增加 snapshot 和 layer data API。
3. SSE 删除完整 GeoJSON。
4. 前端增加版本、哈希和图层缓存。
5. 禁止样式、显隐更新触发几何重建。
6. 禁止普通更新强制 fit。

### P1.2 Web Worker

1. 实现 Worker 协议和取消机制。
2. 实现 `useMapData`。
3. 对中等规模 GeoJSON 使用 Worker。
4. 增加超时、过期版本丢弃和分批 Feature 加载。

### P1.3 MVT

1. 增加 MVT 生成与磁盘缓存。
2. 增加 OpenLayers VectorTileLayer。
3. 根据 LayerManifest 切换 MVT。
4. 测试北京道路大图层和多图层叠加。

### P1.4 PMTiles 和压测

1. 为静态超大图层增加 PMTiles 生成流程。
2. 增加瓦片缓存清理和版本失效机制。
3. 完成真实数据浏览器压测和灰度开关。

## 14. 测试与验收

### 功能测试

- snapshot 与 LayerManifest 版本一致。
- SSE 不包含完整 GeoJSON。
- Worker 能解析、分批返回并取消任务。
- 旧版本响应不会覆盖新版本。
- 样式和显隐变化不重新请求数据。
- MVT 图层能拖动、缩放和切换显隐。
- 最终 PNG 和 MapSpec 的图层清单一致。

### 性能目标

| 指标 | 目标 |
| --- | --- |
| 5,000 要素首屏显示 | 小于 500ms |
| 50,000 要素显示 | 小于 2s |
| 100,000 以上要素 | 不返回完整 GeoJSON |
| 单个 SSE 事件 | 小于 16KB |
| 主线程长任务 | 不超过 100ms |
| 地图交互 | 50 FPS 以上 |
| 样式更新 | 不重新解析几何 |
| 用户拖动后更新图层 | 视图不跳动 |
| 过期 Worker | 100% 可取消 |

### 真实数据场景

- 北京行政区划图。
- 北京道路图层。
- 11 万条道路图层。
- 多图层叠加。
- 连续修改样式。
- 快速拖动和滚轮缩放。
- SSE 断线重连。
- 页面刷新后恢复快照。
- 图层和瓦片加载失败。

## 15. 上线和回退

功能开关：

```text
MAP_RENDER_MODE=hybrid
MAP_WORKER_ENABLED=true
MAP_MVT_ENABLED=false
MAP_PM_TILES_ENABLED=false
```

默认先开启 `geojson + worker`，MVT 和 PMTiles 逐步灰度。渲染失败时按以下顺序回退：

```text
MVT -> geojson-worker -> geojson -> 最终 PNG 预览
```

回退只影响前端实时预览，不影响 Agent 状态和最终成果生成。

## 16. 非目标

本阶段不包括：

- 立即迁移 PostgreSQL/PostGIS。
- 立即迁移 Celery/RQ。
- 重写 Agent 工具体系。
- 多用户协同编辑。
- 全国级底图生产服务。
- 替换 OpenLayers 为 MapLibre。

这些事项可以在 P1 验证完成后作为独立 P2 项目推进。
