# 清水投研 — 架构铁律（2026-10-12 owner 确认：全量落位 chemagent，剥离云端；Agent 第一版 = 本地）

> 形态细节见 `docs/superpowers/specs/2026-09-23-chemagent-worker-deployment-design.md`（worker/GPU 部分）
> 与 `docs/运维/2026-10-12-chemagent-full-migration.md`（存储面迁移实录）。
> 本节替代 2026-09-23 版（云端存储/调度 + chemagent 处理的两地分工）。
> **2026-10-12 owner 补充决策**：第一版 Agent 为**本机形态**——dsh web 跑本地 Mac，
> chemagent 只做数据构建层；灾备 dump 自动化暂缓；云端待 chemagent 侧全部验证结束后下线。

## 角色分工（铁律，任何改动不得违背）

1. **H 集群 chemagent = 数据构建层（唯一生产数据面）**
   - **存储/队列**：MongoDB、PostgreSQL、Qdrant、Redis 以 docker compose 跑在开发机
     `lwm-server-chemagent`，数据一律落 `/data/qingshui/`（编排文件：
     `deploy/chemagent/docker-compose.yml`）；宿主端口只绑 `127.0.0.1`。
   - **调度/服务**：同 compose 起 `backend`（API :8001）、`scheduler`
     （`python -m app.data_pipeline.scheduler`，采集全量在此）、`data-mcp`（:8100）。
     chemagent 经实验室 HTTP 代理访问外网（数据源拉取），无公网入向。
   - **worker**：systemd 托管 `qingshui-worker`（link/vector）与 `qingshui-pdf-worker`，
     一律经 `KNOWLEDGE_API_URL=http://127.0.0.1:8001` 走本机 API，不直连库。
   - **GPU 推理**：`rjob` @ `chemagent_gpu_pool`（H200），bind `0.0.0.0:23456`（bge-m3）
     / `:23457`（Qwen），开发机经集群内网直连。
   - **不承担用户交互面**：chemagent 上不起面向用户的 web 服务。
2. **本地 Mac = Agent 交互层（第一版，owner 2026-10-12 决策）**
   - dsh web + `plugins/qingshui` 跑在本机，用户只在本机使用。
   - Mac → chemagent 的唯一通道：**SSH 端口转发**（如
     `ssh -N -L 8100:127.0.0.1:8100 lwm-server-chemagent`），访问 Data MCP / Knowledge API。
   - 本条是 Mac 常驻通道的**唯一豁免**（Mac 是用户终端而非生产中转）。
   - **与 MatDiscovery 的 dsh 完全解耦（owner 2026-10-13）**：独立 `DSH_HOME=~/.dsh-qingshui`
     （会话/配置/凭据互不可见）、各自仓库独立 dsh submodule pin（清水侧 2026-10-14 起
     worktree 全部并回，唯一 checkout=主仓 `/Users/lwm/code/QingshuiYanTou`）、固定端口 **8399**；
     禁止共享 `~/.dsh`。LLM 凭据经 `~/.dsh-qingshui/.credentials.yaml` 软链复用
     `~/.dsh` 凭据库（免手工配 key）。
3. **云服务器（124.221.188.38）= 只读存量快照，待下线**
   - 2026-10-12 起云端不再接收任何写入（worker 已切本机、云端 scheduler/cron 已停）。
   - 云侧 data-mcp / dsh web 仅作只读快照保留，**待 chemagent 侧全部验证结束后整体下线**
     （owner 2026-10-12）；**禁止**再向云端库写入或在云端新增任何服务。
4. **消费模型 = 拉取（pull）**
   - worker 轮询领取本机 `kg_extraction_jobs` pending 队列；幂等（upsert / PK 冲突
     do-nothing）+ 已处理标记 = 断点续跑。
   - 孤儿租约回收在本机：`/data/qingshui/ops/recover_leases.sh`（crontab 每 10 分钟）。
5. **联通铁律：生产数据通道不得依赖本地 Mac**
   - chemagent 侧任何常驻进程（worker/scheduler/backend）不得经 Mac 中转；
     Mac 仅作用户终端（条目 2）与一次性运维操作（scp/ssh）。
   - GPU 节点断网：不装公网依赖、不下载权重；推理进程只 bind 内网 `ip:port`。
6. **部署纪律**
   - GPU 推理：`rjob` + `--auto-restart`（平台托管自愈），**禁止 nohup/setsid 游离进程**。
   - 开发机常驻：docker 容器 + restart 策略；worker 用 systemd。
   - 依赖安装只取最小集合；装包走内网源或预置到 `/data`。
   - sensecore pod（lwm-server-d）已作废；禁止再启用。
7. **持久化铁律（2026-10-12 owner 更新）**：模型权重、PDF、Mongo/PG/Qdrant 数据等
   **不可重建**数据一律落 **`/data`（500Gi 数据盘 `lwm-server-chemagent-data`）**，
   **不再使用 shared storage（`/mnt/shared-storage-user/liweimin`）**。
   ⚠️ `/data` 为工作空间级卷，随工作空间销毁而消失：机器/工作空间回收前必须先
   `mongodump` / `pg_dump` / qdrant 快照导出迁出。
   （owner 2026-10-12：灾备 dump 自动化**暂缓**，回收机器前手工导出。）
   ⚠️ 历史遗留：worker venv 与 PDF 暂存仍在 shared storage，待迁 `/data`。
8. **新增 evidence 处理需求的默认落位**：chemagent worker 池 / scheduler，不得回云端。

## 现状对照（2026-10-12 实测）

| 组件 | 位置 | 状态 |
|---|---|---|
| Mongo / PG / Qdrant / Redis | chemagent docker（数据在 `/data`） | ✅ 已迁移并对账（kg_evidence 353,768 / link_links 1307 万+ / 三集合向量齐） |
| backend API | chemagent :8001 | ✅ 运行中 |
| scheduler（采集全家桶） | chemagent compose 服务 | ✅ 2026-10-12 接管，ingestion 积压消化中 |
| Data MCP（只读 P0×9） | chemagent :8100 | ✅ 冒烟全绿 |
| knowledge_worker / pdf_worker | chemagent systemd | ✅ 已切本机 API（17:02） |
| bge-m3 / Qwen 推理 | H200 rjob | ✅ 运行中，本机内网直连 |
| Agent 交互层（dsh web） | 本地 Mac | ✅ 已搭建（主仓根目录直接运行，`scripts/start-local-dsh-web.sh`，金标 3/3 通过；2026-10-14 worktree 全部并回主目录） |
| Neo4j | 已除役 | ❌ 2026-10-13 代码面整体删除（旧三元组管线一并退役）；四活进程/金标零依赖，读侧语义检索保留 Qdrant 冻结集合。决策与证据见 `docs/开发文档/16_Neo4j除役记录.md` |
| 云端整套栈 | 124.221.188.38 | ❄️ 只读冻结，chemagent 验证结束后下线 |
| sensecore pod / 生产链路经 Mac | — | ❌ 已退出关键路径 |

## Agent 运行时（2026-10-13）

**唯一**投研 Agent 入口：DeepSeek harness（dsh）+ `plugins/qingshui` + 只读 Data MCP。  
旧 LangChain `/api/v1/agent/*` 与 `backend/app/reasoning/**` 旧运行时已删除（2026-10-13）。见 `docs/superpowers/specs/2026-10-10-agent-mcp-deepseek-harness-design.md` 与 `deploy/mcp/DUAL_TRACK_RUNBOOK.md`。

- **工具面**：只读 Data MCP 21 工具 + Knowledge HTTP（`knowledge/{search,metrics,agent,links,market,sources,ledger}`）。
  **判断沉淀**：write_observation/write_finding 只经 HTTP+插件写面（MCP 不注册写工具），
  见 `docs/开发文档/15_findings台账工具面落地.md`。
- **金标与门禁**：`backend/eval/expected_gap_cases_v2.json`（十案）+ `eval_dual_track.py --gate/--history`
  （连续 3 轮达标零回归 = GATE-STABLE-3，才具备切流/上新判定条件）。
