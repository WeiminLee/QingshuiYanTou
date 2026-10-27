# chemagent 部署资产

H 集群 chemagent 形态的运维脚本与编排。**2026-10-12 起 chemagent 为唯一生产面**
（存储 + 调度 + worker + GPU 推理），云端只读冻结待下线。迁移实录见
`docs/运维/2026-10-12-chemagent-full-migration.md`。

## 拓扑

```
lwm-server-chemagent（开发机，唯一枢纽）
├── docker compose（/data/qingshui/docker-compose.yml，数据全落 /data）
│   ├── mongo :27018(127.0.0.1)      postgres :5433(127.0.0.1)
│   ├── qdrant :6333(127.0.0.1)      redis :6379(127.0.0.1)
│   ├── backend :8001(127.0.0.1)     data-mcp :8100(127.0.0.1)
│   └── scheduler（采集全家桶，出网走实验室代理）
├── systemd
│   ├── qingshui-worker.service（link/vector，supervisor 跟随 GPU 漂移）
│   └── qingshui-pdf-worker.service
├── crontab：*/10 recover_leases.sh（本机孤儿租约回收）
└── 内网直连 → rjob on H200：:23456 bge-m3 / :23457 Qwen（断网，权重在共享存储）
```

**不变量**：GPU 断网只暴露内网 API；DB 端口只绑 127.0.0.1；worker 一律走
`KNOWLEDGE_API_URL=http://127.0.0.1:8001`，不直连库；无 Mac 常驻通道。

## 文件

| 文件 | 位置（运行时） | 职责 |
|---|---|---|
| `docker-compose.yml` | `/data/qingshui/docker-compose.yml` | 全栈编排（mongo/pg/qdrant/redis/backend/data-mcp/scheduler） |
| `serve.sh` | shared storage，rjob 里执行 | 单卡双服务：`:23457` Qwen3.6 / `:23456` bge-m3；写 `endpoints.json` |
| `worker_supervisor.py` | shared storage，systemd 托管 | 常驻守护 knowledge_worker（link/vector/signal），自动跟随 GPU 节点漂移。**代码路径 = `/root/code/QingShuiYanTou/backend`**（2026-10-21 起，此前指向陈旧的 `/root/wq/backend`）。**密钥不在仓内**：由 `qingshui-worker.service` 的 `EnvironmentFile=` 或既有的 `$M/worker.env` 提供 `KNOWLEDGE_API_KEY`，缺失即拒绝启动 |
| `status.sh` | shared storage | 全栈状态一览 |
| `restore_qdrant.sh` | `/data/migration/` | qdrant 集合目录恢复（doc_chunks 用；kg_entities/kg_relations 2026-10-12 补迁同法） |

### scheduler 的 LLM 端点

`scheduler` 启动时执行 `backend/scripts/scheduler_entrypoint.py`：

1. 读 `endpoints.json`，连接 `<node_ip>:23457/v1`，确认 `Qwen3.6-35B-A3B` 在 `/v1/models` 中；
2. 命中则覆盖 `LLM_BASE_URL` / `LLM_MODEL` / `LLM_EXTRACTION_MODEL` 为自部署 GPU；
3. GPU 不可达时保持网关配置，并按 `LLM_EXTRACTION_FALLBACK_ORDER`（默认 `flash,minimax,*`）
   从网关 `/v1/models` 选一个仍可用的抽取模型，避免模型下架后 scheduler 静默空转。

解析只在容器启动时做一次：rjob 重调度导致 `node_ip` 变化后，需
`docker compose restart scheduler` 跟随新节点。worker 侧由 `worker_supervisor.py` 轮询自动跟随。

## GPU 推理部署（不变）

```bash
M=/mnt/shared-storage-user/liweimin/qingshui
rjob submit --name=qingshui-infer-1gpu --charged-group=chemagent_gpu_pool \
  --private-machine=group --image=registry.h.pjlab.org.cn/ailab/vllm-openai:v0.28.0 \
  --gpu=1 --cpu=16 --memory=128000 --auto-restart=true \
  --mount=gpfs://gpfs1/liweimin:/mnt/shared-storage-user/liweimin \
  -- bash $M/serve.sh
```

## 关键约束（踩坑定稿）

| 项 | 值/说明 |
|---|---|
| 推理镜像 | `registry.h.pjlab.org.cn/ailab/vllm-openai:v0.28.0`（不自建） |
| 必加参数 | `--language-model-only`（0.19.1 或漏此参数会挂死） |
| 单卡显存 | LLM `0.62`（KV 47.6GiB / 62× 并发）+ embedding `0.03` |
| thinking 关闭 | vLLM 须 `chat_template_kwargs.enable_thinking=False`；DeepSeek 格式无效（差 14 倍） |
| `no_proxy` | httpx 不识别 CIDR，GPU 节点 IP 必须**字面**写入 |
| worker 并发 | 24/24（GPU 可撑 62；本地 PG 池不再是瓶颈，待观察上调） |
| Python | 3.13（3.10 缺 `datetime.UTC`） |
| pip 源 | PyPI 直连经代理（内网镜像大 wheel 硬 504） |
| 缓存持久化 | `TRITON_CACHE_DIR`/`DG_JIT_CACHE_DIR`/`VLLM_CACHE_ROOT`/`TORCH_EXTENSIONS_DIR` → shared storage |

## 自愈能力

| 事件 | 行为 |
|---|---|
| worker 崩溃 | supervisor 重启 |
| GPU 节点漂移 | supervisor 比对 `endpoints.json` → 重启 worker |
| GPU 不可用 | supervisor 停子进程等待 |
| rjob 被 kill | 平台 `--auto-restart` 重拉，缓存命中后秒级 |
| dev 机重启 | systemd `enabled` 自启；docker `unless-stopped` 自起 |
| 孤儿租约 | 本机 crontab 每 10 分钟回收 running > 5min（`/data/qingshui/ops/`） |

## 已知缺口（2026-10-12）

- Neo4j 未部署（backend env 残留 `NEO4J_URL`，相关功能不可用）。
- `/data` 随工作空间销毁：**灾备 dump 未自动化**（mongo/pg/qdrant 需定期导出）。
- worker venv / PDF 暂存仍在 shared storage，待迁 `/data`。
- 对外访问入口未定（chemagent 无公网；dsh web 部署位置待定）。
- `/root/code/QingShuiYanTou` 是非 git 的代码副本，后续更新需建立同步机制。
