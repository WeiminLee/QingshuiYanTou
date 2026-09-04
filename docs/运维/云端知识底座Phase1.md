# 云端知识底座 Phase 1 运维

腾讯云运行 API、scheduler、单实例 ingestion worker 与数据库/Qdrant 知识底座；台式机通过 WireGuard `10.20.0.2` 访问腾讯云 `10.20.0.1`，负责 PDF 下载、存储、解析、Evidence worker 与 Agent 计算。

## 实施进展（2026-09-01）

代码与配置已完成；以下仅标记已有本地证据的项目：

- Compose 配置校验通过，worker 默认并发为 1。
- PDF 下载任务、Worker、文件存储根目录和失败/跳过契约的本地测试通过。
- Docker daemon 当前可连接（Docker Desktop 29.7.2）。

以下项目仍需在真实台式机/云端环境执行并留存日志：

- WireGuard 网段 MongoDB、PostgreSQL、Qdrant 端口预检。
- Evidence worker 镜像完整构建及启动。
- LLM/Embedding 真实调用和 Qdrant 写入。
- 健康检查、陈旧任务恢复及端到端 PDF 链路。

尚未完成的验收项：

- 10/100/1000 分阶段烟雾测试尚未执行；按当前要求暂不把批量稳定性作为本阶段阻塞项。
- 需要在低并发、可观测的窗口继续完成 10 → 100 → 1000 验证，并记录成功率、失败类型、耗时和重复运行结果。
- 全量重建前仍需完成 Evidence/job 统计导出、备份和明确回滚演练。

已补充分阶段 smoke runner：`python -m scripts.knowledge_smoke_test`。该命令只消费已有
pending job，默认以并发 1 依次执行 10、100、1000，并输出每阶段的 before/after 统计、成功/失败/跳过数和耗时；可用 `--output` 保存 JSON 记录，`--repeat 2` 验证重复运行的幂等表现。建议先在低峰窗口执行：

```bash
python -m scripts.knowledge_smoke_test --limits 10 --concurrency 1 --output /tmp/evidence-smoke-10.json
python -m scripts.knowledge_smoke_test --limits 100 --concurrency 1 --output /tmp/evidence-smoke-100.json
python -m scripts.knowledge_smoke_test --limits 1000 --concurrency 1 --output /tmp/evidence-smoke-1000.json
python -m scripts.knowledge_smoke_test --limits 10 --repeat 2 --concurrency 1 --output /tmp/evidence-smoke-repeat.json
```

若某阶段失败或超时，应保留 JSON 与 worker 日志，停止 `evidence-worker` 后再按“安全与回滚”流程处理；不要直接删除或重建旧 Evidence。

## 启动

```bash
docker compose --env-file backend/.env -f docker-compose.yml -f docker-compose.cloud.yml up -d
```

台式机启动 PDF 下载与 Evidence worker：

```bash
docker compose --env-file backend/.env.local-agent -f docker-compose.yml -f docker-compose.local-agent.yml --profile local-agent up -d
```

云端 ingestion 只创建 `pdf_download` 任务；台式机 worker 直接访问来源 URL，将 PDF 写入本地 `PDF_STORAGE_ROOT`，再通过 WireGuard 直连 MongoDB/PostgreSQL/Qdrant。

Evidence worker 使用独立 `backend/.env.cloud`，并将 `PDF_STORAGE_ROOT` 挂载为只读。默认并发为 1，确认稳定后才可提高到 2。

台式机的 Embedding 请求通过 SSH 转发到腾讯云主机上的 BGE-M3 服务（腾讯云服务监听在 Docker bridge `172.18.0.1:11434`，不是 WireGuard 地址）：

```bash
ssh lwm-desktop-server 'nohup ssh -o BatchMode=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -o ExitOnForwardFailure=yes -N -L 127.0.0.1:11434:172.18.0.1:11434 124.221.188.38 >/tmp/qingshui-llm-tunnel.log 2>&1 & echo $! >/tmp/qingshui-llm-tunnel.pid'
```

隧道建立后，台式机 `.env.cloud` 的 `EMBEDDING_BASE_URL` 应为 `http://127.0.0.1:11434/v1`；停止隧道使用 `ssh lwm-desktop-server 'kill $(cat /tmp/qingshui-llm-tunnel.pid)'`。

生产启动建议使用 `python -m scripts.knowledge_worker --role evidence-extraction --preflight`，依赖预检失败时不会开始消费任务。

## 健康检查

```bash
ssh lwm-desktop-server 'cd ~/qingshui-worker && docker run --rm --network host --env-file backend/.env.cloud qingshui-worker-evidence-worker:latest python -m scripts.worker_preflight'
ssh lwm-desktop-server 'cd ~/qingshui-worker && docker run --rm --network host --env-file backend/.env.cloud qingshui-worker-evidence-worker:latest python -m scripts.knowledge_health'
ssh lwm-desktop-server 'cd ~/qingshui-worker && docker run --rm --network host --env-file backend/.env.cloud qingshui-worker-evidence-worker:latest python -m scripts.knowledge_health --recover-stale-minutes 30'
```

`worker_preflight.py` 会检查 MongoDB、PostgreSQL、Qdrant 的 VPN 地址；任一依赖不可达时返回非零状态，Worker 不应启动。

恢复命令只把超时的 `running` 任务置回 `pending`，不会删除 Evidence。正式全量重建前必须先导出旧 Evidence 和 job 统计。

## 安全与回滚

数据库、Qdrant 不直接暴露公网；密钥只存在服务器 `.env` 且权限为 `600`。Worker 异常时先停止 `evidence-worker`，保留新 Evidence 与失败日志，再恢复旧 Worker/备份，禁止直接删除旧数据。
