# chemagent 全量迁移实录（2026-10-12）

> 背景：owner 确认方向 B —— 全部落位 chemagent，剥离云端。10-12 白天已完成存储面
> 搬运（见 /data/migration/ 时间线 12:30–16:52），本文记录当日收尾的切流、对账与缺口。

## 当日时间线

| 时间(HKT) | 事件 |
|---|---|
| 12:30 | 开始从云端拉取 dump（/data/migration/pull.log） |
| 13:04 | mongo_qingshui.gz 落盘（1.7G）；13:30 pg_qingshui.dump（602M） |
| 14:26 | doc_chunks.tgz（2.3G，qdrant 集合目录）；14:45 backend 镜像构建完 |
| 15:33 | 最终增量 final_ev.gz / final_jobs.gz 落盘（mongorestore 的 98 万 E11000 为增量叠全量的正常重复键） |
| 16:52 | mongo 数据目录收尾，compose 全栈 up |
| 17:02 | **worker 切本机**：worker_supervisor.py / pdf_worker.env 的 `KNOWLEDGE_API_URL` 由 `http://124.221.188.38:8080` 改 `http://127.0.0.1:8001`，重启两个 service；backend 日志确认 claim 打在本机 |
| 17:05 | **scheduler 接管采集**：compose 新增 `scheduler` 服务（`python -m app.data_pipeline.scheduler` + 实验室代理 env），云端此时 scheduler 本就没开、cron 脚本早已失效（脚本文件不存在） |
| 17:10 | **云端停写**：注释云端 4 条 cron（tushare/akshare/bulletins/cls_news，均为死脚本）；确认云端无 scheduler 进程、无其他写入方 |
| 17:20 | **PG 增量对账**：云端在 13:04–17:02 窗口的写入并入 chemagent（见下） |
| 17:25 | 本机孤儿租约回收上线：`/data/qingshui/ops/recover_leases.sh` + crontab */10（沿用云端 recover_cron.js 逻辑） |
| 17:45 | compare_metric 挂死根因修复：pg_restore 后统计失真 + trgm 索引 invalid → `ANALYZE link_links/link_keywords` + 重建索引；同查询 3000 亿 cost → 3.4s |
| 18:22 | qdrant `kg_entities` / `kg_relations` 补迁完成（3.96G 集合目录经 Mac 一次性中转）；semantic_search entities 道复测 200（0.46s 冷启 → 0.04s 热） |
| 18:33 | **P0 冒烟全绿**：semantic / compare / readiness / links-history / kline / MCP-health(9 工具) 全过 |

## 数据对账（切流时刻）

| 对象 | 云端 | chemagent | 结论 |
|---|---|---|---|
| mongo kg_evidence | 353,768 | 353,768 | ✅ 一致（15:33 增量后云端零写入） |
| mongo kg_extraction_jobs | 983,642 | 983,642 | ✅ 一致 |
| pg link_links | 13,072,998 | +1,394 并入 | ✅ 已补 |
| pg link_keywords | 1,158,199 | +21 并入 | ✅ 已补 |
| pg observations | 2,503,876 | +399 并入 | ✅ 已补（serial id 碰撞，按 obs_id 去重重映射） |
| pg signals | 2,128,777 | +227 并入 | ✅ 已补（同上，signal_id 去重） |
| pg watermarks | 1,896,281 | +279 upsert | ✅ 已补（ON CONFLICT DO UPDATE） |
| qdrant doc_chunks | 371,877（**red**） | 371,958 green | ✅ chemagent 为健康副本，且本地 worker 已在追加向量 |
| qdrant kg_entities / kg_relations | 402,900 / 551,079 green | **缺失** | ⚠️ 补迁中（首迁被标"退役"但代码仍在用，见下） |

### PG 增量并库要点（复用价值）

- **pg_restore 后必须立刻 `ANALYZE` 全库 + 检查 invalid 索引**。本次迁移后
  `compare_metric`（带 scope）挂死 >60s，根因有二：① 统计信息失真 → 执行计划
  cost 3000 亿（逐行评估百万级子计划）；② `idx_link_keywords_norm_trgm` 因
  `CREATE INDEX CONCURRENTLY` 中断残留 **invalid**（pg_indexes 里看得见但
  `indisvalid=false`，查询用不上）。修复后同查询 3.4s。检查：
  `SELECT indexrelid::regclass FROM pg_index WHERE NOT indisvalid;`
- **客户端断开不会取消 PG 查询**：curl 超时/进程被杀后服务端继续跑，本次 29 个
  僵尸查询打满 PG。排查先 `pg_stat_activity` 清场再下结论。
- 窗口切法：`created_at >= '2026-10-12 04:00+00'`（覆盖 pg_dump 全程），watermarks 用 `last_updated_at`。
- **serial id 碰撞**：快照后两端各自分配同段 id（chemagent 17:02 起本地新写）。
  observations/signals 不可按 id 覆盖插，须按业务唯一键（obs_id / signal_id）
  `WHERE NOT EXISTS` 去重、id 交给本地序列重新分配，事后
  `setval(pg_get_serial_sequence(...), max(id))` 校正。
- 外键顺序：link_links.keyword_id → link_keywords，必须先并 keywords 再并 links。
- 传输路径：云端 →（ssh 管道经 Mac 一次性中转，非常驻）→ chemagent `/tmp`。

## 验证

- 本机 readiness API 正常（kline fresh 至最近交易日）。
- Data MCP `/health` 返回 9 个 P0 工具：fetch_evidence / semantic_search / compare_metric /
  pull_history / lookup_players / lookup_products / get_kline / get_stock_profile / data_readiness。
- 冒烟实测（18:33 全绿）：semantic ✅（entities 带分返回）、compare（带 scope）✅ 3.4s、
  links/history ✅、market/kline ✅、MCP /health 9 工具 ✅。
- scheduler 接管后 ingestion_jobs pending 881 开始消化（*/5min × 20；18:40 已至 846）。
- kg_extraction_jobs pending = 0（存量抽取队列早已排空，worker 空转为正常）。
- readiness 仍显示 degraded：`research_report` 硬门禁已在 10-09 修复中放宽，
  当前残留为 Mongo announcement 最新日查询偶发 `MaxTimeMSExpired`（缺索引，监控精度问题，不阻塞）。

## 已知缺口 / 后续

1. **Neo4j 未部署**：backend env 残留 `NEO4J_URL=bolt://localhost:7687`；
   若图功能已弃用应摘 env，否则需补容器。
2. **灾备 dump 未自动化**：`/data` 随工作空间销毁，mongo/pg/qdrant 定期导出待做。
3. **对外入口未定**：chemagent 无公网，dsh web / 用户访问方案待定（云端 dsh/data-mcp
   现仅作只读快照短暂保留）。
4. **worker venv / PDF 暂存仍在 shared storage**，按 10-12 铁律待迁 `/data`。
5. **`/root/code/QingShuiYanTou` 为非 git 代码副本**，后续更新需建立同步机制
   （建议 git clone + checkout 分支，compose build context 随之切换）。
6. **Mongo announcement 最新日查询偶发 MaxTimeMSExpired**（readiness 监控精度，
   需补索引）。
7. 云端下线前最后一步：确认无外部依赖（用户书签、监控 webhook）后停容器、
   最终 dump 归档，再释放机器。

## 关键操作回滚

- worker 回云端：supervisor / pdf_worker.env 的 `KNOWLEDGE_API_URL` 改回
  `http://124.221.188.38:8080` 并重启（备份文件 `*.bak-20261012` 在同目录）。
- compose 回滚：`/data/qingshui/docker-compose.yml.bak-20261012`（无 scheduler 版）。
