# chemagent Worker 部署形态设计（2026-09-23）

> 状态：owner 已确认形态，待评审 spec → 转实施计划
> 取代：sensecore pod（lwm-server-d / lwm-server-ai4chem）+ Mac 持隧道的旧形态

## 1. 背景

旧形态把 evidence 处理侧放在 sensecore GPU pod（MetaX C550），用 **Mac 本地持有的 SSH 隧道**连云端数据库，并按 sensecore 平台特性制定了"前台 + 外部持有会话、禁 nohup/setsid"的部署纪律。

本次改为 H 集群（上海智算）：

- 新开发机 `lwm-server-chemagent`（项目 `ailab-chemagent`，账号 `liweimin`）
- 新配额组 `chemagent_gpu_pool`（H200）
- 旧机 `lwm-server-ai4chem` 已删除，`chemagent_gpu_pool` 之外的组（如 `ai4chem_gpu_pool`）不再使用

## 2. 现状问题（必须解决）

| # | 问题 | 证据 |
|---|---|---|
| P1 | **Mac 单点**：隧道与回填会话由本地 Mac 持有，Mac 关机即断 | `docs/运维/链接层A-B评估操作手册.md` §10/§12.2 |
| P2 | **云端 DB 直连不可达**：H 集群只有实验室 HTTP 代理→云端 `:8080` 一条路；`:22` 与 DB 端口全闭 | 实测：代理 200 / 直连 000 / 22·5433·27018·6333 全 closed |
| P3 | **PDF / 模型落在易失盘** | `/`(rbd0) 与 `/data`(rbd1) 为工作空间级 RBD，工作空间删除即丢 |
| P4 | **GPU 节点断网**：无外网、无代理、连不到云端 | 实测：github/hf/modelscope/cloud 全 000；仅 `token.pjlab.org.cn` 401 可达 |
| P5 | **纪律过时**：§4 的"前台持有会话"是 sensecore 特性，H 集群另有平台托管形态（rjob） | `AGENTS.md` §4 |
| P6 | **只有 combined 有远端通路**：link/vector/signal 直连 DB | `app/knowledge/evidence_worker.py:129-207` |

## 3. 终版拓扑

```
                    腾讯云 124.221.188.38
        ┌───────────────────────────────────────────────┐
        │ Mongo · PG · Qdrant · Neo4j · Redis（存储面）  │
        │ Knowledge API ←── 唯一对外通道（X-API-Key）     │
        │ Scheduler（入队 kg_extraction_jobs）           │
        └───────────────────────────────────────────────┘
                 ▲ HTTP（仅经实验室代理）
                 │
   ┌─────────────┴──────────────────────────────────────┐
   │ lwm-server-chemagent（开发机，worker 宿主）          │
   │  · knowledge_worker：link / vector / signal         │
   │  · pdf_download_worker：PDF → shared storage        │
   │  · 出网：仅 实验室HTTP代理 → 云端API                 │
   │  · 持久卷：/mnt/shared-storage-user/liweimin        │
   └─────────────┬──────────────────────────────────────┘
                 │ 集群内 ip:port（实测 200 / 4ms）
                 ▼
        rjob on H200（chemagent_gpu_pool，断网）
        · :23456  bge-m3 embedding（/v1/embeddings）
        · :23457  vLLM Qwen3.6-35B-A3B（/v1/chat/completions）
        · 权重/venv 读 shared storage；写 endpoints.json 供发现

   Mac = 仅开发/运维终端，不在关键路径
```

**角色表**

| 角色 | 位置 | 职责 | 依赖 |
|---|---|---|---|
| 存储+调度面 | 腾讯云 | DB / 队列 / API / 入队 | — |
| Worker 宿主 | `lwm-server-chemagent` | link / vector / signal / PDF 下载 | 代理→API；GPU `ip:port` |
| 推理面 | rjob @ H200 | embedding + LLM 抽取 | shared storage 权重 |
| 终端 | Mac | 开发、看日志 | 可随时关机 |

## 4. 数据流

1. 云端 scheduler 入队 `kg_extraction_jobs`（`vector` / `link` / `signal`）。
2. chemagent worker 经代理 `POST /api/v1/knowledge/jobs/claim` 领任务，`GET /api/v1/knowledge/evidence/{id}` 取正文。
3. worker 调 GPU 推理：
   - `link` → Qwen 关键词抽取（`linklayer/llm_extract.extract_keywords`）
   - `vector` → bge-m3 embedding
4. worker 把**计算结果** `POST` 回云端新端点，云端落 PG / Qdrant。
5. `pdf_download`：领任务 → 下载 → 存 shared storage → API upsert evidence（通路已存在）。

## 5. 接口契约

### 5.1 云端已有（复用）

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/api/v1/knowledge/jobs/claim` | 领 `kg_extraction_jobs` |
| POST | `/api/v1/knowledge/jobs/{id}/success` `failure` | 回写任务状态 |
| POST | `/api/v1/knowledge/evidence/jobs/claim` | 领提取任务 |
| POST | `/api/v1/knowledge/evidence/jobs/{id}/success` `failure` | 回写 |
| GET | `/api/v1/knowledge/evidence/{evidence_id}` | 取 evidence |
| POST | `/api/v1/knowledge/evidence/upsert` | evidence 入库 |
| POST | `/api/v1/knowledge/kg/ingest` | KG 结构化结果入库（combined 用） |

全部 `X-API-Key` 鉴权（`app/knowledge/api/worker_jobs.py`）。

### 5.2 云端新增（B 方案核心）

均 `X-API-Key` 鉴权、幂等（PK 冲突 do-nothing / upsert）。

| 方法 | 路径 | 载荷 | 落库 |
|---|---|---|---|
| POST | `/api/v1/knowledge/vector/upsert` | `{evidence_id, vector: float[], payload: {...}}` | Qdrant `doc_chunks` |
| POST | `/api/v1/knowledge/link/upsert` | `{evidence_id, actions: [{layer, norm_text, source, span_start, span_end, published_at?, dimension?, level?}]}` | PG link/keyword 表 + 台账管线 |

设计约束：

- 端点做**校验 + 落库**；唯一例外是 `/link/upsert` 在落 link 行后**立即运行机械台账管线**
  （候选观察 → 雷达信号 → 水位线推进）。该管线需读 PG（link 行、watermark），无法在断网
  worker 侧完成，故随落库在云端执行；它是零 LLM 的机械派生，不引入抽取算力。
- 幂等键沿用现有 PK 语义，重复提交不产生重复记录。
- 载荷走批量（单条 evidence 的全部行一次提交），减少代理往返。
- **`signal` 端点不在本期范围**：生产 `ENABLE_KG_EXTRACTION=false`，活动任务仅 `vector` + `link`；
  `signal` 计算依赖 Neo4j 读取（`KGPathProvider`），需单独设计（见 §11 R6）。

### 5.3 worker 侧改造点

| 文件 | 现状 | 改造 |
|---|---|---|
| `app/knowledge/evidence_worker.py:197-205` | `JOB_LINK` 直连 `async_session` + `ingest_evidence` | 拆出远端分支：计算本地、落库 POST `/link/upsert`（台账管线随落库在云端执行） |
| `app/knowledge/evidence_worker.py:185-192` | `JOB_VECTOR` 直连 Qdrant | 远端分支：算向量后 POST `/vector/upsert` |
| `app/knowledge/evidence_worker.py:193-196` | `JOB_SIGNAL` 直连 PG | **本期不做**（见 §5.2 注 / §11 R6） |
| `app/knowledge/linklayer/ingest.py:21` | `ingest_evidence(evidence_id, *, _session)`，内部自建 `EvidenceService` 直读 Mongo | 拆成「计算 → 行集合」与「持久化」两段；计算段接收 evidence dict（已由 API 取得），持久化段可选 DB / HTTP |
| `app/knowledge/linklayer/candidates.py` | `generate/persist_candidates`、`emit_radar_signals` 绑 session | **不拆分**：候选需读 PG（link 行/水位线），整条管线随 `/link/upsert` 在云端运行 |
| `app/knowledge/vector_client.py` | `upsert_evidence_chunk_vector(evidence)` 一体 | 拆出「生成 vector + payload」与「写入」 |
| `app/knowledge/worker_api_client.py` | 已有 `KnowledgeApiClient` | 增补 2 个新端点（vector/link）的调用方法 |

判定模式：沿用现有约定——设置了 `KNOWLEDGE_API_URL` + `KNOWLEDGE_API_KEY` 即走远端。

## 6. 配置契约（dev 机 worker）

```ini
# 云端通道
KNOWLEDGE_API_URL=http://124.221.188.38:8080
KNOWLEDGE_API_KEY=<cloud key>

# GPU 推理（IP 由 endpoints.json 发现，见 §8）
EMBEDDING_BASE_URL=http://<gpu-node-ip>:23456/v1
EMBEDDING_API_KEY=<local dummy>
LLM_BASE_URL=http://<gpu-node-ip>:23457/v1
LLM_API_KEY=<local dummy>
LLM_MODEL=Qwen3.6-35B-A3B
LLM_DISABLE_THINKING=true

# 持久化
PDF_STORAGE_ROOT=/mnt/shared-storage-user/liweimin/qingshui-pdfs

WORKER_CONCURRENCY=2
WORKER_POLL_INTERVAL=30
```

外网经实验室代理：`http_proxy/https_proxy=http://httpproxy-headless.kubebrain.svc.pjlab.local:3128`，`no_proxy` 含 `10/8`、`100.96/12`、`.pjlab.org.cn`（保证 GPU `ip:port` 与云端 API 分流正确）。

> 注意：云端 API 是公网 IP，走代理；GPU `ip:port` 是内网，走 no_proxy。

## 7. 持久化与重启

| 资源 | 位置 | dev 机重启 | 工作空间删除 | rjob 重调度 |
|---|---|---|---|---|
| 云端 DB/API | 腾讯云 | ✅ | ✅ | ✅ |
| 模型权重 / PDF | shared storage | ✅ | ✅ | ✅ |
| GPU 推理进程 | rjob | 平台自愈 | 重新提交 | 自动重拉 |
| dev 机 worker | docker + restart 策略 | ✅ | 需重建容器 | — |

- `/`(rbd0) 与 `/data`(rbd1) 仅放**可重建**内容（代码、临时目录）。
- 模型与 PDF 一律落 shared storage；shared storage 配额 100G，需评估（见 §11）。

## 8. GPU 推理服务设计（rjob）

**提交骨架**

```bash
rjob submit \
  --name=qingshui-infer \
  --charged-group=chemagent_gpu_pool \
  --private-machine=group \
  --image=registry.h.pjlab.org.cn/ailab/pytorch2.7.0-cuda12.8-cudnn9:v5 \
  --gpu=2 --cpu=16 --memory=64000 \
  --auto-restart=true \
  --mount=gpfs://gpfs1/liweimin:/mnt/shared-storage-user/liweimin \
  -- bash /mnt/shared-storage-user/liweimin/qingshui/serve.sh
```

**启动脚本职责**（`serve.sh`，放 shared storage）

1. 从 shared storage 读模型权重（bge-m3、Qwen3.6-35B-A3B）。
2. 起 bge-m3 embedding 服务，bind `0.0.0.0:23456`，暴露 OpenAI 兼容 `/v1/embeddings`。
   候选实现（P1 实测择一）：① vLLM `--task embed` 直接服务 `BAAI/bge-m3`；② 复用仓库内
   `backend/scripts/embedding_server.py` 的 HTTP 形态，把后端换成 H200 上的 transformers/torch。
   输出维度须与云端 `EMBEDDING_DIMENSION`（当前 2560）一致。
3. 起 vLLM OpenAI 兼容服务，bind `0.0.0.0:23457`。
4. 写 `/mnt/shared-storage-user/liweimin/qingshui/endpoints.json`：
   `{"node_ip": "...", "embedding": "http://ip:23456/v1", "llm": "http://ip:23457/v1", "updated_at": "..."}`
5. 前台守护两个子进程（rjob 托管，勿用 nohup 游离）。

**端点发现**：dev 机 worker 轮询 `endpoints.json`，不硬编码 IP。

**版本要点**：基础镜像 `torch 2.7.0+cu128`，无 vllm/transformers/fastapi，需在镜像内或共享 venv 安装；GPU 节点无外网，安装须走内网源或预置到 shared storage。

## 9. 纪律修订（AGENTS.md §4）

按集群分开写：

| 集群 | 常驻形态 | 禁止 |
|---|---|---|
| H 集群（chemagent） | GPU：rjob + `--auto-restart`；dev 机：docker + restart 策略 | 依赖 Mac 持会话 |
| sensecore（存量过渡） | 前台 + 外部持有会话 | 全量装 requirements.txt |

并明确：**任何常驻通道不得依赖 Mac**。

## 10. 分期实施

| 期 | 内容 | 前置 |
|---|---|---|
| P0 | 基础设施验证 | ✅ 已完成 |
| P1 | 权重→shared storage；rjob 起 bge-m3 + vLLM；endpoints.json | 验证 Qwen3.6-35B-A3B 的 vLLM 支持 |
| P2 | 云侧 2 个写入端点（vector/link）+ worker 远端分支（vector 优先） | 改云侧代码 |
| P3 | dev 机 worker 容器化 + link 接入 + 生成/同步 `company_aliases.json` | P2 |
| P4 | PDF 下载 worker + shared storage 落盘 | — |
| P5 | 切流、下线 pod/隧道、修订 AGENTS.md | P1–P4 |

## 11. 风险与待决

| # | 风险 | 处置 |
|---|---|---|
| R1 | Qwen3.6-35B-A3B 为 `qwen3_5_moe` 架构，vLLM 可能不认（MetaX 已翻车） | P1 第一步验证；不通过则回落 Qwen3-32B-AWQ / Qwen2.5-14B |
| R2 | shared storage 仅 100G，PDF 全量 + 模型（≈40G）可能顶格 | 估算用量；不足则申请扩容 |
| R3 | 代理带宽：link 每条 evidence 多次 API 往返 | P2 后压测 p95，必要时批量载荷 |
| R4 | `ingest_evidence` 计算/持久化耦合较深，拆解有回归风险 | 先 vector（最小面），link 随后；补单测 |
| R5 | GPU 节点 IP 浮动 | endpoints.json + 启动时校验 |
| R6 | `signal` 计算依赖 Neo4j 读取，无法在断网 worker 完成 | 本期不做（生产未启用该 job type）；单独立项，候选方案：云端提供 `/signal/ingest`（收 evidence_id，云端算+写） |
| R7 | 远端 link 不写 `keyword_extraction` 缓存（无 DB），与 `backfill_keyword_links` 的"无缓存即待处理"断点口径不一致 | 已让远端路径不再触碰 DB（`extract_keywords(persist=False)`）并回传 `llm_used`；**缓存写入待补**：云端新增缓存写入（`/link/upsert` 载荷字段或独立端点）。影响仅为池扫描路径的重复 LLM 成本，非正确性 |
| R8 | `company_aliases.json` 是 gitignore 的部署产物，不在仓库 | 远端 worker 字典层公司匹配依赖它；已在空表时告警。**部署时必须生成/同步该文件到 worker**（P3 步骤） |

## 12. 验收标准

- dev 机 worker 在 Mac 关机状态下持续消费 `vector`/`link` 任务，无中断。
- GPU 推理服务在 rjob 重调度后自动恢复，worker 经 endpoints.json 重新连上。
- PDF 落 shared storage，dev 机工作空间删除重建后文件仍在。
- 重复提交 link/vector 结果幂等，无重复记录。
- 全链路不出现任何依赖 Mac 的常驻会话。

---

## 13. 落地记录（2026-09-23 实装完成）

### 13.1 终版拓扑（已验证）

```
云端 124.221.188.38                      dev 机 lwm-server-chemagent        H200 rjob (单卡)
┌──────────────────────┐                ┌─────────────────────────┐       ┌──────────────────┐
│ Mongo/PG/Qdrant/Neo4j│◀── HTTP/代理 ──│ worker_supervisor.py     │       │ vllm-openai:v0.28│
│ Knowledge API :8080  │   (拉任务/回写) │  ├ knowledge_worker link │─内网─▶│ :23457 Qwen3.6   │
│ scheduler(采集/入队)  │                │  └ knowledge_worker vector│       │ :23456 bge-m3    │
└──────────────────────┘                └─────────────────────────┘       └──────────────────┘
         ▲                                                                         │
         └───────────────── 云端与 GPU 之间【零连接】─────────────────────────────┘
```

**关键不变量**：云端连不到 GPU（实测 CLOSED）；dev 机是唯一枢纽；GPU 断网只暴露内网 API。

### 13.2 部署要点（踩坑后定稿）

| 项 | 结论 |
|---|---|
| 推理镜像 | `registry.h.pjlab.org.cn/ailab/vllm-openai:v0.28.0`（租户公共，**不自建**） |
| 必加参数 | `--language-model-only`（否则多模态 encoder 画像挂死）；0.19.1 会静默挂死 |
| 单卡双服务 | LLM `--gpu-memory-utilization 0.62`（KV 47.6GiB / 62× 并发）+ embedding `0.03` |
| 权重来源 | ModelScope（HF 经代理 0 字节卡死）；bge-m3 4.3G + Qwen FP8 35G |
| 缓存持久化 | `TRITON_CACHE_DIR`/`DG_JIT_CACHE_DIR`/`VLLM_CACHE_ROOT`/`TORCH_EXTENSIONS_DIR` → shared storage |
| **thinking 关闭** | vLLM 须 `extra_body.chat_template_kwargs.enable_thinking=False`（DeepSeek 格式无效，差 14 倍） |
| **no_proxy** | httpx 不识别 CIDR，GPU 节点 IP 必须**字面**写入 |
| worker venv | Python 3.13（3.10 缺 `datetime.UTC`）；PyPI 直连经代理（内网镜像大 wheel 硬 504） |
| worker 形态 | dev 机直跑（无 docker）；systemd + supervisor 常驻 |

### 13.3 自愈能力（已验证）

| 事件 | 行为 |
|---|---|
| worker 子进程崩溃 | supervisor 检测并重启 |
| GPU 节点漂移 | supervisor 比对 `endpoints.json` → 自动重启 worker（实测通过） |
| GPU 不可用 | supervisor 停子进程等待，不刷失败 |
| dev 机重启 | systemd `enabled`，开机自启 |
| rjob 被 kill | 平台 `--auto-restart` 重拉，缓存命中后秒级就绪 |

### 13.4 性能与质量

- **吞吐**：37.4 条/分钟（thinking 修复前 2.5）；单条 link 0.7–1.0s、vector 0.7–0.9s
- **质量**（对照生产 kw_v2 缓存，40 条样本）：company 0.856 / product 0.770 / metric 0.859 / **总体 0.828**，零解析失败，优于历史本地最优（Qwen3-32B-AWQ 0.731）
- **端到端**：6/6 jobs done，PG `link_links` 29/29/11 行、Qdrant 344,167 点、observations 231,713、signals 410,416

### 13.5 运维入口

- 状态总览：`bash /mnt/shared-storage-user/liweimin/qingshui/status.sh`
- worker 服务：`systemctl {status,restart} qingshui-worker.service`
- GPU 服务：`rjob list` / `rjob submit ... serve.sh`
