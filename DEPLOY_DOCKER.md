# Docker 部署说明

## 1. 准备环境

1. 安装 Docker 和 Docker Compose。
2. 准备好项目数据目录 `data/`。
3. 在项目根目录创建 `.env`，不要沿用仓库里的明文密钥。

## 2. 环境变量

至少需要这些值：

```env
DJANGO_SECRET_KEY=your-secret-key
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,your-domain.com
NEO4J_USER=neo4j
NEO4J_PASSWORD=your-neo4j-password
NEO4J_URI=bolt://host.docker.internal:7687
NEO4J_URL=bolt://host.docker.internal:7687
REDIS_URL=redis://redis:6379/0
DEEPSEEK_API_KEY=your-key
ZHIPUAI_API_KEY=your-key
DATA_DIRECTORY_BASE=/app/data
OUTPUT_DIR=/app/outputs
```

## 3. 启动

```bash
docker compose up -d --build
```

本机 Neo4j 模式:

```bash
docker compose up -d --build web redis nginx
```

如果要改回容器内 Neo4j，把 `.env` 中的 `NEO4J_URL` 改成 `bolt://neo4j:7687`，再执行:

```bash
docker compose up -d --build
```

如果你希望把图数据真正导入到 `map2-neo4j` 容器里，而不是只访问本机 Neo4j，需要再执行一次:

```bash
docker compose --profile init run --rm -e NEO4J_URI=bolt://neo4j:7687 neo4j-init
```

如果是第一次导入知识图谱数据，再执行一次：

```bash
docker compose --profile init run --rm neo4j-init
```

第一次启动后，系统会：

1. 拉起 Neo4j。
2. 启动 Django Web 服务。
3. 执行数据库迁移。
4. 收集静态文件。
5. 启动 Redis，供地图 SSE 事件流（Redis Streams）使用。

如果需要单独导入 Neo4j 数据，可以进入 `web` 容器后执行：

```bash
python -m xy_neo4j.import_neo4j_data
```

## 4. 访问

- Web 页面：`http://localhost`
- Neo4j Browser：`http://localhost:7474`

## 5. 目录挂载

- `data/`：知识图谱与 GIS 数据
- `generated_maps/`：生成地图文件
- `outputs/`：运行状态和输出结果

## 6. 生产建议

1. 把 `nginx` 放在公网入口。
2. 用自己的域名和 HTTPS 证书。
3. 不要把 `.env` 提交到仓库。
4. Neo4j 密码和 Django `SECRET_KEY` 每个客户单独配置。
