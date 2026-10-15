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
- Data MCP `/health` 返回 9 个 P0 工具（**截至 2026-10-12 实测值**；2026-10-13 落 P0.5 后
  已扩为 21 个只读工具）：fetch_evidence / semantic_search / compare_metric /
  pull_history / lookup_players / lookup_products / get_kline / get_stock_profile / data_readiness。
- 冒烟实测（18:33 全绿）：semantic ✅（entities 带分返回）、compare（带 scope）✅ 3.4s、
  links/history ✅、market/kline ✅、MCP /health 9 工具 ✅。
- scheduler 接管后 ingestion_jobs pending 881 开始消化（*/5min × 20；18:40 已至 846）。
- kg_extraction_jobs pending = 0（存量抽取队列早已排空，worker 空转为正常）。
- readiness 仍显示 degraded：`research_report` 硬门禁已在 10-09 修复中放宽，
  当前残留为 Mongo announcement 最新日查询偶发 `MaxTimeMSExpired`（缺索引，监控精度问题，不阻塞）。

## 已知缺口 / 后续（2026-10-12 晚 owner 决策后）

1. **Agent 交互层 = 本地 Mac（第一版已定）**：dsh web + plugins/qingshui 跑本机，
   经 SSH 转发访问 chemagent Data MCP/后端；chemagent 只做数据构建层。**已搭建** ✅
   （2026-10-13：`scripts/start-local-dsh-web.sh`，`DSH_HOME=~/.dsh-qingshui`
   与 MatDiscovery 完全解耦——独立会话/配置/凭据，端口 8399）。
2. **Neo4j 未部署**：backend env 残留 `NEO4J_URL=bolt://localhost:7687`；
   若图功能已弃用应摘 env，否则需补容器。
3. **灾备 dump：owner 决策暂缓**；注意 `/data` 随工作空间销毁，回收机器前必须
   手工 `mongodump`/`pg_dump`/qdrant 快照导出。
4. **云端下线时机：待 chemagent 侧全部验证结束后**再停容器、最终 dump 归档、释放机器。
   （2026-10-13：过夜采集验证已通过——news/irm 今日均本机自采成功。）
5. **worker venv / PDF 暂存仍在 shared storage**，按 10-12 铁律待迁 `/data`。
6. **`/root/code/QingShuiYanTou` 为非 git 代码副本**；2026-10-13 起热修方式 =
   worktree 改码 → scp 到 chemagent → `docker cp` 进容器 + 重启（已用于
   drain limit 5→20 与 readiness 修复）。后续建议 git clone 正规化。
7. ~~Mongo announcement 最新日查询偶发 MaxTimeMSExpired~~ 与 readiness 误报
   → 2026-10-13 已修（见下"10-13 追加"）。

## 10-13 追加（迁移次日）

- **dsh 完全解耦**：`DSH_HOME=~/.dsh-qingshui`；启动脚本自举装插件；验证无
  MatDiscovery 会话/品牌残留（双轨分支 `509563a`）。
- **ingestion drain 提速**：drain limit 5→20 补丁 cherry-pick 到双轨分支
  （`0450c3c`）并热部到 scheduler 容器；积压 1004 → 回落中。
- **readiness 误报修复**（`8c54683`）：merge 的 latest_failure 不再计历史失败
  （只认最近成功之后的失败）；删除 9-24 残留的一条 irm all_market 失败 checkpoint
  与 100 条 Mac 时代 reports 失败记录。readiness 现 **overall: fresh**。
- **semantic_search chunk 字段补全热修**（双轨分支 worktree `agent-mcp-dsh`，未提交）：
  `_shape_chunk`（`backend/app/knowledge/api/agent_search.py`）在原 5 字段外按
  payload 可选补 `publish_date`、`title`（`subject_hint.title` → `metadata.title`
  兜底）、`pdf_url`（`source_ref.pdf_url`，仅公告类有）；缺失即省略不报错。
  热部照旧：worktree 改码 → scp → `docker cp` 进 `qingshui_backend:/app/app/knowledge/api/`
  → 重启容器（未动其他容器）。验证：`pytest tests/test_agent_search_api.py` 6/6
  （新增 2 例钉住新字段与省略行为）；容器内对 doc_chunks 真实 payload 跑
  `_shape_chunk`：公告类三字段齐、IRM 类仅 `publish_date`（省略语义正确）。
  ⚠️ 附带发现：**`qingshui-infer-1gpu` rjob 处于 Stopped**（bge-m3/Qwen 推理下线，
  `100.103.242.214:23456` 不可达），embedding 超时导致 semantic_search 实时检索
  暂不可用，HTTP 端到端验证待 rjob 恢复后补。→ **已于当日下午恢复并验证通过，
  见下条**。
- **GPU 推理 rjob 停机恢复 + Qdrant HNSW 修复**（2026-10-13 下午）：
  - **停机原因**：日志显示 10-13 10:38 平台侧 SIGTERM（`signal: terminated`，
    疑似抢占/回收，events 无更多记录）；`--auto-restart` 只自愈失败副本，
    对 job 级 Stopped 不生效，故未自动拉起。
  - **恢复**：按 `deploy/chemagent/README.md` 原样重提交 → 新 job
    `qingshui-infer-1gpu-73168281`，调度到**新节点 H200-0097，IP 变为
    `100.102.89.71`**（旧 100.103.242.214）。bge-m3/Qwen 约 3 分钟内先后就绪
    （shared storage 缓存热），`endpoints.json` 已自动更新，worker supervisor
    自动跟随无需干预。
  - **IP 漂移处置**：`/root/code/QingShuiYanTou/backend/.env:57`
    `EMBEDDING_BASE_URL` 改新 IP；`/data/qingshui/docker-compose.yml` 两处
    `extra_hosts gpu-node` 同步改（备份 `*.bak-20261013`）；`docker compose up -d
    backend` 仅重建 backend。
  - **⚠️ 踩坑：compose recreate 会丢 docker cp 热补丁**（容器可写层被换）——
    上述 semantic chunk 热修一度被冲掉，重新 `docker cp` + restart 恢复，并已
    `docker compose build backend` 把补丁烧进镜像（构建上下文
    `/root/code/QingShuiYanTou/backend` 已含补丁，md5 三方一致）。
    **教训：热修后要么尽快 build 镜像，要么避免 recreate。**
  - **⚠️ 附带发现 2：Qdrant 三集合 HNSW 全被禁用**（`hnsw_config: null`，
    从云端目录拷贝继承）：doc_chunks 39 万 / kg_entities 40 万 / kg_relations 55 万
    点全部暴力全扫，单查 17~29s > qdrant-client 默认 5s 超时——这才是 rjob 恢复后
    semantic 仍持续 `RETRIEVE-FAIL: timed out` 的根因（昨 18:33 冒烟能过是因当时
    集合小/缓存热）。已对三集合 `PATCH {"hnsw_config":{"m":16,"ef_construct":100}}`，
    索引后台重建完成后查询降至 **毫秒级**（0.003~0.35s），配置已持久化进集合
    `config.json`（重启不丢）。残留：ingestion drain 高峰期 `wait=true` 写流仍会
    偶发把单查挤出 5s 超时（~10-20% 概率，重试即过）， backlog 排空后应消失。
  - **端到端验证（本机隧道，全绿）**：`硅片 涨价` → 3 chunks 带
    `publish_date`；`甬矽电子 年度业绩预告` → 3 条公告 chunk `publish_date`/
    `title`/`pdf_url` 三字段齐（cninfo 链接）。前一日热修的 HTTP 验证缺口闭合。

## 关键操作回滚

- worker 回云端：supervisor / pdf_worker.env 的 `KNOWLEDGE_API_URL` 改回
  `http://124.221.188.38:8080` 并重启（备份文件 `*.bak-20261012` 在同目录）。
- compose 回滚：`/data/qingshui/docker-compose.yml.bak-20261012`（无 scheduler 版）。

## 部署方法补记（2026-10-13 三件套 + Neo4j 除役上线）

chemagent 侧**不是 git clone**（两处代码目录均为拷贝），标准部署流程：

1. **打包**（本地仓）：`git archive --format=tar.gz <commit> -o /tmp/bundle.tgz`
2. **上传覆盖**（两个目录都覆盖，保留各自 .env/data/logs）：
   ```bash
   # /root/code/QingShuiYanTou  → backend/data-mcp/scheduler 镜像 build 上下文
   # /root/wq                   → systemd worker 的代码目录
   cd <目标目录>
   rm -rf backend/app backend/scripts backend/tests backend/alembic backend/migrations \
          plugins scripts deploy docs
   tar -xzf /tmp/bundle.tgz -C <目标目录>
   echo <commit> > DEPLOYED_REV
   ```
3. **构建+滚动**：**编排真身在 `/data/qingshui/docker-compose.yml`（compose 项目名 qingshui）**，
   不要用仓内 deploy/chemagent 副本（会因项目名不同触发容器名冲突）。
   **构建必须带实验室代理 build-arg**——chemagent 构建容器无直连外网出口，
   裸跑会以「No matching distribution found for <任意包>」面目失败（腾讯/清华源皆如此）：
   ```bash
   cd /data/qingshui
   docker compose build \
     --build-arg http_proxy=http://httpproxy-headless.kubebrain.svc.pjlab.local:3128 \
     --build-arg https_proxy=http://httpproxy-headless.kubebrain.svc.pjlab.local:3128 \
     backend
   docker compose up -d backend data-mcp scheduler
   systemctl restart qingshui-worker.service qingshui-pdf-worker.service
   ```
4. **能力面冒烟**（本机经隧道）：`KNOWLEDGE_API_KEY=… bash scripts/smoke_capability.sh`
   （31 项断言：P0 回归 + P0.5 新面 + 台账幂等写 + MCP tools/list）。

### 已知数据缺口（通道正常、待采集；2026-10-13 实测）

- `company_profiles` 表 0 行 → `get_stock_profile` 返回空业务描述（需回填脚本/采集任务）。
- `concept_limit` 0 个交易日 → `get_top_concepts` 返回「本地数据不足」
  （需运行概念涨停同步；补涨金标案 catchup-concept-001 依赖此面）。
