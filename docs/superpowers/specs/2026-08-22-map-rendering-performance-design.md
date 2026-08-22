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

本设计覆盖地图数据传输、前端渲染、任务执行边界、后端缓存和大数据格式。PostGIS 全量迁移和多人协作属于后续项目，但生产任务不能继续依赖 Django 进程内线程。

## 2. 设计原则

- **MapSpec 是唯一渲染输入**：OpenLayers 和 Matplotlib 都消费同一份规范化地图配置。
- **SSE 传事件，HTTP 传数据**：SSE 不携带完整 GeoJSON 或瓦片二进制。
- **按规模选择渲染器**：不让小图层承担瓦片服务的复杂度，也不让大图层走完整 GeoJSON。
- **版本优先于时序**：所有地图、图层和数据响应都带版本；过期响应必须丢弃。
- **数据与状态分离**：地图规格、图层数据、生成成果和实时事件分别管理。
- **渐进式改造**：默认先保持 GeoJSON 兼容，再按功能开关启用 Worker、MVT 和 PMTiles。

## 3. 统一数据模型

现有 `gis_mapping_agent/specs/map_spec.py` 的 `MapSpec` 作为领域模型基础，扩展为前后端传输规范。字段名称需要从 Matplotlib 风格逐步归一化，兼容期内由后端适配旧字段。MapSpecSnapshot 是地图配置的唯一持久化来源；`MapRequest.map_config` 只作为兼容期读取镜像，不能再作为第二个事实来源。

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
  "data_url": "/mapping/api/map-requests/23/snapshots/4/layers/beijing-boundary/"
}
```

`render_mode` 的合法值为 `geojson`、`geojson-worker`、`mvt` 和 `pmtiles`。后端依据配置阈值和数据元信息决定模式，前端只执行模式，不自行猜测。

### 3.4 持久化和版本

当前 SQLite 继续作为 P1 的本地持久化介质，但必须建立明确的事实来源：

```text
MapRequest              用户需求和当前运行引用
MapRun                  Django 主数据库中的一次 Agent 执行、状态、错误和幂等键
MapSpecSnapshot         某个地图版本的完整 MapSpec JSON
LayerManifest           该快照的图层元数据、哈希和渲染模式
GeneratedMap/Artifact   绑定 MapSpec 版本的成果文件
```

`map_states` 追加 `schema_version`、`spec_json`、`spec_hash`、`source_fingerprints` 和 `latest_event_seq`；`layers` 追加 `data_hash`、`feature_count`、`extent`、`render_mode` 和 `data_url`。Django 主数据库新增 `MapRun`，至少包含 request、status、idempotency_key、map_version、attempt、heartbeat_at、started_at、finished_at 和 error_code。`MapRequest.map_config` 在兼容期只同步摘要，历史数据读取时转换为 MapSpecSnapshot。

保存地图版本时必须在一个事务内完成快照和图层清单写入，提交成功后才发布 SSE。成果文件先写入临时文件并原子重命名，再保存 Artifact 记录。Artifact 至少记录 `map_version`、`source_fingerprints`、文件大小、SHA-256、MIME 类型和相对路径。

### 3.5 任务执行边界

生产环境不允许由 Django Web 进程创建后台线程执行 Agent。使用 Redis + Celery 独立 Worker：

```text
Django API -> Celery/Redis -> map-worker -> MapRun/MapSpec/Artifact
```

初始 Worker 并发设为 1，避免 Matplotlib、GeoPandas 和现有 Agent 全局状态互相影响。MapRun 必须有超时、心跳、重试次数、取消请求和失败状态。Web 进程重启不应丢失任务；Worker 启动时将超时且无心跳的运行标记为失败或重新排队。

## 4. 分级渲染策略

| 数据规模 | 方式 | 说明 |
| --- | --- | --- |
| 小于 5,000 要素 | GeoJSON | 主线程直接加载，链路简单 |
| 5,000 至 30,000 | GeoJSON + Worker | Worker 解析、过滤、简化和计算范围 |
| 超过 30,000 | MVT | 按视口和缩放级别加载，不再返回完整 GeoJSON |
| 超大静态图层 | PMTiles | 适合发布型、低变更数据 |

阈值通过环境配置控制：

```text
MAP_GEOJSON_LIMIT=5000
MAP_WORKER_LIMIT=100000
MAP_MVT_ENABLED=true
MAP_PM_TILES_ENABLED=true
```

最终 PNG 始终使用后端原始或高精度派生数据，不使用前端低精度预览结果。

## 5. RESTful API 与通信协议

### 5.1 资源模型

`MapRequest` 是现有业务资源，直接作为制图任务资源使用，`job_id` 不另建一套 ID。一次用户请求可以产生多个 `MapRun`，每次继续对话或重试都创建新的运行记录。

```text
MapRequest
  ├── messages
  ├── runs
  │    └── events
  ├── snapshots
  │    └── layers
  │         └── data / tiles
  └── artifacts
```

### 5.2 接口

```text
POST   /mapping/api/map-requests/
GET    /mapping/api/map-requests/{request_id}/
PATCH  /mapping/api/map-requests/{request_id}/
DELETE /mapping/api/map-requests/{request_id}/
POST   /mapping/api/map-requests/{request_id}/messages/
GET    /mapping/api/map-requests/{request_id}/messages/
POST   /mapping/api/map-requests/{request_id}/runs/
GET    /mapping/api/map-requests/{request_id}/runs/{run_id}/
PATCH  /mapping/api/map-requests/{request_id}/runs/{run_id}/
GET    /mapping/api/map-requests/{request_id}/runs/{run_id}/events/
GET    /mapping/api/map-requests/{request_id}/snapshots/current/
GET    /mapping/api/map-requests/{request_id}/snapshots/{version}/
GET    /mapping/api/map-requests/{request_id}/snapshots/{version}/layers/{layer_id}/
GET    /mapping/api/map-requests/{request_id}/snapshots/{version}/layers/{layer_id}/tiles/{z}/{x}/{y}.pbf
GET    /mapping/api/map-requests/{request_id}/artifacts/
```

创建 `MapRequest` 只负责保存用户需求；创建 `Run` 才触发一次 Agent 执行。响应返回资源 URL、当前状态和 `run_id`。所有接口都要求认证，并校验资源属于当前用户。快照返回 MapSpec 与 LayerManifest，不返回大体量几何。

### 5.3 HTTP 语义

- `POST /map-requests/` 创建制图请求，成功返回 `201 Created`。
- `POST /messages/` 创建用户消息，可选地创建关联 Run，成功返回 `201 Created`。
- `POST /runs/` 创建一次执行，使用 `Idempotency-Key` 防止重复运行。
- `GET` 只读，不触发 Agent 或生成副作用。
- `PATCH /runs/{run_id}/` 只允许状态转换，例如 `cancel_requested`；不允许客户端伪造 `completed`。
- `DELETE /map-requests/{request_id}/` 删除请求及其私有成果，使用 `204 No Content`。
- 资源不存在返回 `404`，无权访问返回 `404` 以避免泄露资源是否存在。
- 处理中的重复创建返回现有 Run 或 `409 Conflict`，不重复启动任务。

消息、运行记录和成果列表使用 `limit`、`cursor` 分页。快照、GeoJSON 和瓦片响应提供 `ETag`、`Last-Modified` 和 `Cache-Control: private`。用户私有数据不能使用公共 CDN 缓存。瓦片路径只接受经过校验的整数 z/x/y，不直接拼接用户提供的文件路径。

### 5.4 SSE 事件

```json
{
  "event": "layer_updated",
  "request_id": 23,
  "run_id": 8,
  "map_version": 4,
  "layer_id": "beijing-boundary",
  "layer_version": 3,
  "snapshot_version": 4
}
```

事件类型包括：`job_started`、`job_progress`、`map_spec_updated`、`layer_added`、`layer_updated`、`layer_removed`、`validation_warning`、`artifact_created`、`job_completed` 和 `job_failed`。

SSE 禁止携带完整 GeoJSON、重复的全量图层和二进制成果。前端收到事件后通过 HTTP 获取快照或指定图层。

### 5.5 一致性和重同步规则

- 每个 Run、MapSpec 和图层都有递增版本；事件同时带 `run_id`、`map_version` 和 `event_seq`。
- 前端只接受不低于当前版本的响应。
- 数据请求使用 AbortController；新版本到达时取消旧请求。
- SSE 断线后先读取 current snapshot，再从 Last-Event-ID 继续接收事件。
- 重复事件按 `event_id + version` 幂等处理。
- Redis Stream 被 trim 导致游标不可用时，服务端发送 `resync_required`；前端重新读取 snapshot，不尝试补发已经过期的事件。
- Snapshot 返回 `latest_event_seq`，前端可以判断是否已经追上事件流。

## 6. Web Worker 设计

新增：

```text
frontend/src/workers/geojsonParser.worker.ts
frontend/src/map/workerProtocol.ts
frontend/src/hooks/useMapData.ts
```

Worker 负责纯数据操作：JSON 解析、空几何过滤、几何简化、extent 计算和分批返回。后端 GeoJSON 统一输出 EPSG:4326，前端 OpenLayers 统一负责转换到 EPSG:3857，Worker 不重复执行 CRS 转换。Worker 不创建 OpenLayers Map、Layer、Style 或 DOM 对象。

主线程接收可序列化几何数据后创建 OpenLayers Feature。中间结果按批次返回，避免一次性阻塞主线程。Worker 只用于 5,000 至 30,000 要素的过渡区间；超过该范围直接使用 MVT，避免主线程最终创建海量 Feature。可以传输的 `ArrayBuffer` 必须使用 Transferable Object，避免结构化复制。

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

缓存写入使用临时文件、`fsync` 和原子 rename；同一个缓存键使用 Redis 分布式锁，避免多个 Worker 重复生成。缓存必须支持按用户或项目隔离、最大容量、TTL、LRU 清理、失败文件清理和版本失效。文件指纹优先使用大小与 mtime，后台再计算 SHA-256；计算指纹不能阻塞用户请求。

图层数据、瓦片和成果接口都必须先校验 `request_id` 属于当前用户，再校验 snapshot、layer 和 artifact 的归属。相对路径只能从服务端生成，禁止使用请求参数直接拼接本地路径。

## 10. MVT 与 PMTiles

第一阶段兼容当前文件系统：在 Run 完成图层校验后，使用明确锁定版本的 `mapbox-vector-tile` 生成指定缩放级别的 `.pbf`，按 `source_hash + layer_version + zoom_range` 写入磁盘缓存。禁止在每次瓦片请求中重新读取完整 Shapefile；请求只读取已生成的瓦片文件。第二阶段迁移 PostGIS，使用空间索引和 `ST_AsMVT` 按请求生成瓦片。

MVT 接入前必须完成技术验证：使用真实的 11 万条道路数据预生成瓦片，测量生成时间、单瓦片响应、冷/热缓存、内存、并发和 OpenLayers 交互；验证通过后才打开 `MAP_MVT_ENABLED`。如果预生成文件数量或时间不可接受，本阶段只上线 Worker 和简化 GeoJSON，不假装 MVT 已达到生产标准。

PMTiles 只用于静态、低变更、超大图层。PMTiles 必须由离线构建流程生成并记录源数据哈希、生成工具版本和 zoom 范围；前端需要明确的 PMTiles 读取依赖和错误回退。动态编辑图层和频繁变更图层继续使用 GeoJSON 或 MVT，不直接使用 PMTiles。

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

MVT 的回退不能回到完整大 GeoJSON。正确链路为：

```text
MVT 失败
  ↓
请求当前视口的服务端简化 GeoJSON，且受 feature/byte 上限保护
  ↓
仍失败则保留最终 PNG 入口并展示实时图层错误
```

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

### P0.0 全栈基础

1. 以 `MapRequest.id` 作为资源 ID，新增 `MapRun` 记录，不创建重复 Job 资源。
2. 在 map-state 数据库中增加 MapSpecSnapshot、LayerManifest 和事件游标字段。
3. 用 Celery + Redis 独立 Worker 替代 Django 进程内线程，初始并发为 1。
4. 定义快照事务、成果原子写入、超时、心跳、重试和取消状态。
5. 完成所有 RESTful 接口的用户归属校验、路径安全、ETag 和私有缓存策略。
6. 定义 `resync_required` 和 `latest_event_seq`，补齐 SSE 事件丢失后的快照重同步。

### P1.1 协议和增量更新

1. 扩展 MapSpec，定义 LayerManifest。
2. 增加 RESTful snapshot 和 layer data API，保留旧接口兼容期。
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

1. 使用 11 万条道路数据完成 MVT 预生成技术验证。
2. 增加版本化 MVT 生成与磁盘缓存，不在单次瓦片请求中读取完整源文件。
3. 增加 OpenLayers VectorTileLayer。
4. 通过基准测试后，根据 LayerManifest 切换 MVT。
5. 若验证不达标，先上线服务端视口简化 GeoJSON，不打开 MVT 开关。

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

指标以 Chromium 最新稳定版、桌面端 4 核 CPU/16GB 内存、局域网、冷缓存和热缓存分别测量，报告 p50/p95、网络字节数、主线程长任务和浏览器内存。不能只报告平均 FPS。

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

并发验收还必须覆盖：2 个地图任务 Worker 进程同时生成不同任务、同一缓存键并发生成、Redis 重启、Web 进程重启、任务 Worker 重启和任务重复提交。

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
MVT -> 当前视口简化 GeoJSON -> 最终 PNG 入口并显示实时图层错误
```

回退只影响前端实时预览，不影响 Agent 状态和最终成果生成。

## 16. 非目标

本阶段不包括：

- 立即完成 PostgreSQL/PostGIS 全量迁移。
- 重写 Agent 工具体系。
- 多用户协同编辑。
- 全国级底图生产服务。
- 替换 OpenLayers 为 MapLibre。

这些事项可以在 P1 验证完成后作为独立 P2 项目推进。
