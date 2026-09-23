# 清水投研 — 架构铁律（2026-09-23 owner 确认）

> 形态细节见 `docs/superpowers/specs/2026-09-23-chemagent-worker-deployment-design.md`。
> 本节替代 2026-09-19 版（d 集群 sensecore pod + Mac 持隧道）。

## 角色分工（铁律，任何改动不得违背）

1. **H 集群 chemagent = evidence 处理/消费侧**
   - **worker 宿主**：开发机 `lwm-server-chemagent`（项目 `ailab-chemagent`），运行
     `knowledge_worker`（link / vector / signal）与 `pdf_download_worker`。
   - **GPU 推理**：`rjob` @ 配额组 `chemagent_gpu_pool`（H200），只暴露 HTTP API：
     bge-m3 embedding 与 Qwen LLM 抽取，bind `0.0.0.0:23456` / `:23457`。
   - 所有"处理 evidence"的工作负载（LLM 关键词抽取、向量化/embedding、链接构建等）
     一律以 **worker 拉取任务**的方式跑在这里。
   - 云服务器不得新增或扩容 evidence 处理 worker；云侧遗留 worker 仅作存量过渡。
2. **云服务器 = 存储与调度面**
   - MongoDB（evidence 池 + 任务队列）、PostgreSQL（keywords/links/判断台账）、
     Qdrant（向量库）、Neo4j、Redis 都在云上。
   - 云侧只做存取与编排（API 服务、scheduler 入队），不承担抽取算力。
3. **消费模型 = 拉取（pull）**
   - worker 轮询领取任务：`kg_extraction_jobs` 的 pending 队列，或"无
     `keyword_extraction` 缓存标记"等待处理池位；处理完把结果写回云上存储。
   - 幂等（upsert / PK 冲突 do-nothing）+ 已处理标记 = 断点续跑：worker 死亡后
     重启即自动续，不丢进度、不重复入链。
4. **联通铁律：任何常驻通道不得依赖本地 Mac**
   - H 集群 worker 的云端通道 = **实验室 HTTP 代理 → 云端 Knowledge API**
     （`/api/v1/knowledge/*`，`X-API-Key`）。H 集群到云端 SSH/DB 端口均不可达，
     不得再引入 Mac 中转隧道。
   - GPU 节点断网：不装公网依赖、不下载权重；推理进程只 bind 内网 `ip:port`，
     由开发机经集群内网直连（实测 200）。
5. **部署纪律（按集群分写）**
   - **H 集群**
     - GPU 推理：`rjob` + `--auto-restart`（平台托管自愈），**禁止 nohup/setsid 游离进程**。
     - 开发机常驻：docker 容器 + restart 策略。
     - 依赖安装只取最小集合；装包走内网源或预置到 shared storage。
   - **sensecore（存量过渡，逐步下线）**
     - 常驻进程前台 + 由外部持有会话，禁止 nohup/setsid 存活。
     - **禁止在 pod venv 全量安装 requirements.txt**（会覆盖 MetaX torch / numpy）。
6. **持久化铁律**：模型权重、PDF 等**不可重建**数据一律落
   `shared storage（/mnt/shared-storage-user/liweimin）`；工作空间级 `/`、`/data`
   只放可重建内容。
7. **新增 evidence 处理需求的默认落位**：H 集群 chemagent worker 池；云侧只加队列与存储。

## 现状对照（2026-09-23）

| 组件 | 位置 | 状态 |
|---|---|---|
| bge-m3 embedding 服务 | H 集群 H200（rjob） | ⚠️ P1 待部署（旧 sensecore pod 形态作废） |
| Qwen 抽取服务 | H 集群 H200（vLLM） | ⚠️ P1 待部署 |
| knowledge_worker（link/vector/signal） | H 集群开发机 | ⚠️ P3 待接入（需云侧 API 端点，P2） |
| pdf_download_worker | H 集群开发机 | ⚠️ P4 待迁移（PDF 落 shared storage） |
| scheduler / API backend | 云端 | ✅ 属于编排面，留云 |
| sensecore pod（lwm-server-d） | sensecore | ❌ 作废，待下线 |
| Mac 持隧道 / 回填会话 | 本地 | ❌ 作废，禁止再依赖 |
