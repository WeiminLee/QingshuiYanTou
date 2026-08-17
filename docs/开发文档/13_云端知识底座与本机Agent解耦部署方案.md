# 云端知识底座与本机 Agent 解耦部署方案

> 日期：2026-08-17
> 背景：本机可能关机，知识采集、Evidence 构建、抽取和索引不能依赖本机常驻运行。

## 一、结论

推荐采用“云端知识底座 + 本机 Agent 运行侧”的半解耦部署。

```text
腾讯云服务器
  持续运行：数据采集、Evidence 构建、抽取 worker、知识存储、知识查询 API

本机电脑
  可开可关：Agent runtime、前端开发、调试工具、实验性推理流程
```

这个方案优先解决持续运行问题，不立即拆成多个仓库或完整微服务。当前项目仍保持单仓库、模块分层，通过部署 profile 和环境变量区分云端知识侧与本机 Agent 侧。

## 二、服务器约束

当前腾讯云服务器规格：

```text
CPU: 4 核
内存: 8GB
系统盘: SSD 云硬盘 120GB
流量包: 1500GB/月
带宽: 10Mbps
```

这台机器适合承载小规模持续知识构建，但不适合高并发、全量重建或本地大模型服务。

必须避免：

- 本地部署 embedding 模型。
- Evidence worker 高并发运行。
- 多个 data job-worker 副本常驻。
- 白天执行全量 PDF 解析、全量向量重建、全量图谱重建。
- 将 PostgreSQL、MongoDB、Neo4j、Qdrant 端口直接暴露公网。

## 三、职责切分

### 3.1 云端知识底座

云端负责所有需要持续运行和持久沉淀的能力：

- PostgreSQL：股票、行情、公告索引、业务表、同步状态。
- MongoDB：Evidence、extraction jobs、Agent 运行辅助状态。
- Neo4j：Entity、Relation、StructuredFact、图谱关系。
- Qdrant：Evidence chunk、实体、关系向量索引。
- Backend Knowledge API：知识包、图谱查询、Evidence 追溯、readiness。
- Data Scheduler：低频数据同步、采集任务入队。
- Evidence Worker：消费抽取任务，写 Neo4j / Qdrant / MongoDB。
- Ingestion Job Worker：消费数据采集 job。

### 3.2 本机 Agent 侧

本机负责可开可关的交互和实验能力：

- Agent runtime。
- 前端开发环境。
- 推理链路调试。
- 工具适配层开发。
- 临时脚本和实验任务。

本机关闭后，云端仍继续同步数据、构建 Evidence、处理抽取任务和更新知识存储。

## 四、推荐架构

```text
                    ┌──────────────────────────────┐
                    │          本机电脑              │
                    │  Agent runtime / frontend dev │
                    └──────────────┬───────────────┘
                                   │
                 Tailscale / WireGuard / ZeroTier
                                   │
                    ┌──────────────▼───────────────┐
                    │          腾讯云服务器          │
                    │  Backend Knowledge API        │
                    │  Scheduler / Workers          │
                    │  PostgreSQL / MongoDB         │
                    │  Neo4j / Qdrant               │
                    └──────────────────────────────┘
```

优先使用内网隧道访问云端服务。本机 Agent 第一阶段可以直接调用云端 backend API；后续再收敛为只调用知识查询 API，不直连数据库。

## 五、分阶段落地

### Phase 1：云端持续运行基础

目标：电脑关机后，数据同步和知识构建仍能继续。

云端启动：

- `postgres`
- `mongo`
- `neo4j`
- `qdrant`
- `backend`
- `scheduler`
- `job-worker` 1 个
- `evidence worker` 1 个，低并发

云端配置：

```text
ENABLE_API_SCHEDULER=false
EMBEDDING_BACKEND=openai
EMBEDDING_BASE_URL=<外部 embedding API>
EMBEDDING_DIMENSION=<与当前索引一致>
```

资源建议：

```text
Neo4j heap: 512m - 1g
Evidence worker max_concurrency: 1 - 2
Data job-worker replicas: 1
Backend uvicorn workers: 1
```

本机使用：

- 本机 Agent 通过内网地址访问云端 `backend`。
- 本机前端开发环境可指向云端 API。
- 本机不再承担定时同步和抽取 worker。

### Phase 2：Agent 与知识查询接口解耦

目标：本机 Agent 不再直连云端数据库，只通过 HTTP 工具访问云端知识层。

Agent 工具访问方式从本地存储调用逐步迁移为：

- `/api/v1/knowledge/...`
- `/api/v1/data/...`
- `/api/v1/readiness/...`
- `/api/v1/signals/...`

保留本地直连数据库作为开发 fallback，但生产路径以 HTTP API 为准。

### Phase 3：云端任务分级和运维加固

目标：让 4C/8G 服务器稳定长期运行。

需要补齐：

- Docker Compose profiles：`cloud-knowledge`、`local-agent`。
- Worker 并发和任务类型分级。
- 夜间重任务窗口。
- 健康检查和告警。
- 数据备份与恢复脚本。
- 数据库端口默认只监听内网。
- API Key、数据库密码、LLM Key 全部通过服务器 `.env` 管理。

## 六、安全策略

禁止公网暴露：

- PostgreSQL `5432/5433`
- MongoDB `27017/27018`
- Neo4j Bolt `7687`
- Qdrant `6333/6334`

允许公网暴露的入口应尽量只有：

- HTTPS 前端入口。
- Backend API HTTPS 入口，必须带 API Key 或登录态。

推荐访问方式：

```text
本机 -> Tailscale/WireGuard -> 云端内网 IP -> backend/database
```

如果短期必须暴露管理端口，应限制安全组来源 IP，只允许本机固定出口 IP 访问。

## 七、资源控制建议

在 8GB 内存机器上，应优先保证数据库和 backend 存活，worker 宁可慢一点。

建议默认策略：

- Backend 单进程运行。
- Scheduler 单实例运行。
- Ingestion job worker 单实例运行。
- Evidence worker 单实例运行。
- LLM 抽取并发从 1 开始，确认稳定后再提高到 2。
- Neo4j heap 最大不超过 1GB。
- 不在云端运行本地 embedding 模型。
- Qdrant 只保存必要 collection，历史重建任务手动执行。

当出现 OOM、swap 明显增长、API 响应慢时，优先暂停 Evidence worker，而不是停止数据库。

## 八、备份策略

最低要求：

- PostgreSQL 每日备份。
- MongoDB 每日备份。
- Neo4j 每周备份或在批量重建前备份。
- Qdrant 定期 snapshot。
- `.env` 不进仓库，单独保存到密码管理器或服务器安全目录。

备份优先级：

1. PostgreSQL 和 MongoDB。
2. Neo4j。
3. Qdrant。

Qdrant 可以通过 Evidence 重新向量化恢复，但成本较高；MongoDB Evidence 丢失则会破坏追溯链路。

## 九、后续代码调整方向

后续可以在不拆仓库的前提下做部署解耦：

- 新增 `docker-compose.cloud.yml` 或 compose profiles。
- 新增 `backend/.env.cloud.example` 和 `backend/.env.local-agent.example`。
- 为 Evidence worker 增加独立 compose service。
- 将 `job-worker` 默认副本从 2 调整为云端小规格可控配置。
- 增加云端 health check 脚本。
- 增加本机 Agent 访问云端 Knowledge API 的工具适配层。

## 十、最终建议

当前最务实的方案是：

```text
腾讯云：storage + scheduler + evidence worker + backend knowledge API
本机：agent runtime + frontend/dev tools
连接：Tailscale/WireGuard 内网访问
```

不要立刻拆成两个项目，也不要把所有 Agent 能力都迁到服务器。先让云端承接“必须持续运行”的知识构建和知识存储，本机保留高频开发和推理实验能力。
