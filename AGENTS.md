# 清水投研 — 架构铁律（2026-10-12 owner 确认：全量落位 chemagent，剥离云端）

> 形态细节见 `docs/superpowers/specs/2026-09-23-chemagent-worker-deployment-design.md`（worker/GPU 部分）
> 与 `docs/运维/2026-10-12-chemagent-full-migration.md`（存储面迁移实录）。
> 本节替代 2026-09-23 版（云端存储/调度 + chemagent 处理的两地分工）。

## 角色分工（铁律，任何改动不得违背）

1. **H 集群 chemagent = 唯一生产面**（存储 + 调度 + evidence 处理 + GPU 推理）
   - **存储/队列**：MongoDB、PostgreSQL、Qdrant、Redis 以 docker compose 跑在开发机
     `lwm-server-chemagent`，数据一律落 `/data/qingshui/`（编排文件：
     `deploy/chemagent/docker-compose.yml`）；宿主端口只绑 `127.0.0.1`。
   - **调度/服务**：同 compose 起 `backend`（API :8001）、`scheduler`
     （`python -m app.data_pipeline.scheduler`，采集全量在此）、`data-mcp`（:8100）。
   - **worker**：systemd 托管 `qingshui-worker`（link/vector）与 `qingshui-pdf-worker`，
     一律经 `KNOWLEDGE_API_URL=http://127.0.0.1:8001` 走本机 API，不直连库。
   - **GPU 推理**：`rjob` @ `chemagent_gpu_pool`（H200），bind `0.0.0.0:23456`（bge-m3）
     / `:23457`（Qwen），开发机经集群内网直连。
2. **云服务器（124.221.188.38）= 只读存量快照，待下线**
   - 2026-10-12 起云端不再接收任何写入（worker 已切本机、云端 scheduler/cron 已停）。
   - 云侧 data-mcp / dsh web 仅作只读快照短暂保留，验证完成后整体下线；
     **禁止**再向云端库写入或在云端新增任何服务。
3. **消费模型 = 拉取（pull）**
   - worker 轮询领取本机 `kg_extraction_jobs` pending 队列；幂等（upsert / PK 冲突
     do-nothing）+ 已处理标记 = 断点续跑。
   - 孤儿租约回收在本机：`/data/qingshui/ops/recover_leases.sh`（crontab 每 10 分钟）。
4. **联通铁律：任何常驻通道不得依赖本地 Mac**
   - chemagent 出网只有实验室 HTTP 代理（数据源拉取用）；Mac 仅允许一次性运维操作
     （scp/ssh），不得作为常驻隧道或中转。
   - GPU 节点断网：不装公网依赖、不下载权重；推理进程只 bind 内网 `ip:port`。
5. **部署纪律**
   - GPU 推理：`rjob` + `--auto-restart`（平台托管自愈），**禁止 nohup/setsid 游离进程**。
   - 开发机常驻：docker 容器 + restart 策略；worker 用 systemd。
   - 依赖安装只取最小集合；装包走内网源或预置到 `/data`。
   - sensecore pod（lwm-server-d）已作废；禁止再启用。
6. **持久化铁律（2026-10-12 owner 更新）**：模型权重、PDF、Mongo/PG/Qdrant 数据等
   **不可重建**数据一律落 **`/data`（500Gi 数据盘 `lwm-server-chemagent-data`）**，
   **不再使用 shared storage（`/mnt/shared-storage-user/liweimin`）**。
   ⚠️ `/data` 为工作空间级卷，随工作空间销毁而消失：机器/工作空间回收前必须先
   `mongodump` / `pg_dump` / qdrant 快照导出迁出；日常保持定期 dump 习惯作为灾备
   （**目前灾备 dump 尚未自动化，是已知缺口**）。
   ⚠️ 历史遗留：worker venv 与 PDF 暂存仍在 shared storage，待迁 `/data`。
7. **新增 evidence 处理需求的默认落位**：chemagent worker 池 / scheduler，不得回云端。

## 现状对照（2026-10-12 实测）

| 组件 | 位置 | 状态 |
|---|---|---|
| Mongo / PG / Qdrant / Redis | chemagent docker（数据在 `/data`） | ✅ 已迁移并对账（kg_evidence 353,768 / link_links 1307 万+） |
| backend API | chemagent :8001 | ✅ 运行中 |
| scheduler（采集全家桶） | chemagent compose 服务 | ✅ 2026-10-12 接管，ingestion 积压 881 消化中 |
| Data MCP（只读 P0×9） | chemagent :8100 | ✅ 健康检查通过 |
| knowledge_worker / pdf_worker | chemagent systemd | ✅ 已切本机 API（17:02） |
| bge-m3 / Qwen 推理 | H200 rjob | ✅ 运行中，本机内网直连，无 Mac |
| Neo4j | 未迁移 | ⚠️ chemagent 未部署；backend env 残留 NEO4J_URL 待清理或补装 |
| 对外访问入口 | 未定 | ⚠️ chemagent 无公网，用户访问方案待定 |
| 云端整套栈 | 124.221.188.38 | ❄️ 只读冻结，验证期后下线 |
| Mac 隧道 / sensecore pod | — | ❌ 已退出关键路径 |
