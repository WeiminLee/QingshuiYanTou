# 清水投研 — 架构铁律（2026-09-19 owner 确认）

## 角色分工（铁律，任何改动不得违背）

1. **d 集群（sensecore GPU pod）= 唯一的 evidence 处理/消费侧**
   - 所有"处理 evidence"的工作负载（LLM 关键词抽取、向量化/embedding、链接构建等）
     一律以 **worker 拉取任务**的方式跑在 d 集群。
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
4. **d 集群部署纪律（sensecore 平台会清理游离后台进程）**
   - 常驻进程一律"前台 + 由外部持有会话"挂起（如本地机器 ssh 直持），
     禁止依赖 nohup/setsid 存活。
   - 依赖安装只取最小集合；**禁止在 pod venv 全量安装 requirements.txt**
     （会覆盖 MetaX torch / numpy，连带打掉 bge-m3 服务）。
   - pod → 云端已有免密钥与隧道形态：反向隧道（embedding -R 11434）与
     正向隧道（PG 5433 / Mongo 27018 -L），新 worker 复用同一把钥匙。
5. **新增 evidence 处理需求的默认落位**：d 集群 worker 池；云侧只加队列与存储。

## 现状对照（2026-09-19）

| 组件 | 位置 | 状态 |
|---|---|---|
| bge-m3 embedding 服务 | d 集群 GPU | ✅ 唯一合规形态（-R 隧道回云端） |
| backfill_keyword_links | d 集群（试跑中） | ✅ 迁移中：云端旧进程已停 |
| knowledge_worker（link 消费） | 云端 systemd | ⚠️ 计划迁 d 集群 |
| evidence vector worker | 云端 systemd | ⚠️ 计划迁 d 集群（本地 embed + 隧道写 Qdrant） |
| scheduler / API backend | 云端 | ✅ 属于编排面，留云 |
