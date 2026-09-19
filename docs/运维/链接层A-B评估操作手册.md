# 链接层 A/B 评估操作手册（2026-09-18 部署执行版）

> 状态：代码与数据库迁移已落地，全量回填后台进行中（~2 天）。本手册为运维一步-by-一步操作与当日现实记录。

## 1. 数据库迁移（已执行 ✅）

```bash
ssh root@124.221.188.38
cd /home/lwm/code/QingShuiTouYan/backend
/home/lwm/code/QingShuiTouYan/.venv/bin/python -m alembic upgrade head   # 生产库 stamp 026 后已执行 027/028，current=028
/home/lwm/code/QingShuiTouYan/.venv/bin/python -m alembic current
```

注意：生产库原本无 alembic 版本记录（历史表结构在迁移体系外演化），因此先 `stamp 026` 再 `upgrade head`。

## 2. gold set 回填（已执行 ✅，持续扩充中）

`backend/eval/gold_set_v1.json` 中的 `expected_evidence_ids` 必须是 Mongo `kg_evidence` 里的真实 `evidence_id`。

协议：从 `minishare_announcements` 池选真实公司 → `db.kg_evidence.find({subject_hint.ts_code: <ts_code>})` 挑选真实 evidence_id → 人工确认相关性后填入。
当前已填 2 条（timeline / cross_section 各一）；theme 类条目待向量通道修复后重填。

## 3. 链接层回填（进行中）

```bash
cd /home/lwm/code/QingShuiTouYan/backend
# 干跑
/home/lwm/code/QingShuiTouYan/.venv/bin/python -m scripts.backfill_keyword_links --dry-run --sample 10
# 精准回填（gold set / 单条修复）
#   --refresh 强制重跑 LLM 提取（忽略缓存）——若未来加该参数；当前单条重置缓存可用 mongosh $unset
/home/lwm/code/QingShuiTouYan/.venv/bin/python -m scripts.backfill_keyword_links            # 全量（含 LLM）
/home/lwm/code/QingShuiTouYan/.venv/bin/python -m scripts.backfill_keyword_links --skip-llm # 只建词典层（网关不可用/省额度）
```

- 断点续跑键：`kg_evidence.keyword_extraction` 缓存（LLM 成功才写入，缓存 miss 即续跑）
- 幂等：link PK 冲突 do-nothing；重复执行安全
- 词典层（subject/stage/dimension + subject_hint 权威锚点）零 LLM，分钟级可全量重算

## 4. A/B 双跑与验收口径

```bash
cd /home/lwm/code/QingShuiTouYan/backend
/home/lwm/code/QingShuiTouYan/.venv/bin/python -m scripts.eval_retrieval --backend semantic --k 20   # 基线（需 embedding 服务）
/home/lwm/code/QingShuiTouYan/.venv/bin/python -m scripts.eval_retrieval --backend link     --k 20
```

验收：timeline / cross_section 条目上 **link ≥ semantic**；theme 条目为向量通道职责，不计入链接层验收。

**2026-09-18 实测（真实证据条目）**：timeline **1.00**，cross_section **1.00**（semantic 基线因 d-cluster 隧道断而不可测，见遗留 1）。

## 5. LLM 网关现实（2026-09-18 切换）

- 生产 `.env` 已从付费中转 tianxuncloud（额度耗尽 403）**切回 pjlab 免费网关** `token.pjlab.org.cn`（备份：`.env.bak-20260918-pre-pjlab-swap`）
- 抽取模型：`Qwen3.6-35B-A3B-FP8`（owner 指定）；对话主力暂代 `glm-5.3`（pjlab 无 deepseek-v4-pro-0813）

## 6. 生产切换（等待验收后执行）

```text
1. 云端 backend/.env 加 ENABLE_KG_EXTRACTION=false
2. docker compose --env-file backend/.env build backend && up -d backend
3. 重建 evidence worker 容器（server_start.sh，EVIDENCE_JOB_TYPES 含 link）
4. systemctl restart qingshui-scheduler.service
5. d 集群 tar 同步（GitHub 云端不可达，改走 bundle over SSH）
```

## 7. 遗留事项

| # | 事项 | 依赖 |
|---|---|---|
| 1 | **d-cluster 隧道修复**（9-17 起断）：daemon 机上重启 `qingshui-embed-tunnel.sh`，云端验证 `curl http://172.18.0.1:11434/health` | 内网 ssh 权限 |
| 2 | 全量回填完成核对（`keyword_extraction` 缓存口径 × 316k evidence） | 时间 |
| 3 | 词表治理例会：scope 候选 ~2 条/证据增长，周期性 `merge_keyword` 归并 | 运营例程 |
| 4 | collation version mismatch `ALTER DATABASE qingshui REFRESH COLLATION VERSION`（需评估索引重建） | 择期 |
| 5 | flag 未翻前新证据仍会入队 combined（量小）；可重跑 `/tmp/mark_combined_skipped.js` 批量清理 | flip 前 |

## 8. 事故记录（2026-09-19）

**09-18 事故**：云机 8G 内存被回填并发（concurrency=4 + 新增 2 进程）打穿（available 从 426MB 起步），sshd 卡 banner，owner 云端重启恢复。

**修正**：
- 回填并发胃口以 `free -m` available > 2G 为水位线开闸；当前采用 `--concurrency 2`（重启后 available 5,492MB 起步）
- 全量回填按 evidence 剩余 ~312k、实测 ~30/min（LLM 延迟主导）估算，完成需 ~7 天；如需提速：a) 升配云机至 16G；b) 等台式机恢复后续把 backfill 移到台式机跑（资源体量大两个数量级）
- 设备优先序的重申：embedding 通道修复（d-cluster）优先于一切回填调参
- vector worker（`qingshui-vector-worker.service`，owner 原有 systemd 单元）在 embedding 修复前会持续把 pending vector 任务置 failed：**隧道修复后需批量 `failed → pending` 回收**（mongosh updateMany）

## 9. 遗留事项 1 收口（2026-09-19 三通道 A/B 终版）

**embedding 通道**：d-cluster（sensecore pod，root@10.140.158.130:49190）bge-m3 GPU 服务 `sembed_server.py` 绑 127.0.0.1:11434 + 反向隧道 `-R 172.18.0.1:11434→127.0.0.1:11434`，云端 `curl http://172.18.0.1:11434/health` → 200。生产 `.env` 已指向 172.18.0.1:11434/v1，vector worker / eval 全链路复通。模型缓存在 pod `/root/hf-cache`，venv `/root/wq/venv`（必带 `MACA_PATH=/opt/maca`）。

**gold set 扩到 3 条**（backend/eval/gold_set_v1.json，commit 972214d）：
- 新增 `theme-ai-copper-foil-001`（博威合金 601137.SH 压延铜箔 IRM，expected EV:b147cb8d…）；theme 按设计走 **semantic** 通道（queries.py scan_dimension 对 dimension=None 返回空）。

**eval 语义基线口径修正**（`scripts/eval_retrieval.py`）：retrieve_semantic 改为 **doc_chunks 单通道** top-k 直查。原先误用 hybrid_vector_search（RRF 四集合合并），entities/relations 的结果 payload 无 evidence_id、永不命中，却挤占 global top-k，系统性低估基线。

**终版数字（k=20）**：

| 通道 | timeline | cross_section | theme | mean | hit rate |
|---|---|---|---|---|---|
| link | 1.00 | 1.00 | —（设计内走向量） | **1.000** | **1.000** |
| semantic（chunks lane） | 0.67 | 0.00 | 1.00 | 0.556 | 0.667 |

结论不变且更扎实：横截面（跨公司毛利率对比）semantic 基线全灭（长年报 chunk 稀释 + 稠密跨文本对齐弱），正是链接层价值主张的实证。

**vector 数据修复（当日完成）**：
1. `kg_extraction_jobs` 里 vector/failed 3,999 条 → 批量 reset pending（vector worker 已全部消费回 done）
2. 池内 evidence vs doc_chunks 索引精确 diff（uuid5 批检索）→ **48,471 条缺向量**（无任务可走，纯入池时 embedding 断供遗留）→ `/tmp/build_gap_v3.py`（求差集）+ `/tmp/repair_gap_v1.py`（并发 3 直写 upsert_evidence_chunk_vector，断点 `/tmp/vector_repair_done.txt`，日志 `/tmp/vector-repair.out`），实测 ~20/s，ETA ~40min
3. **company_aliases.json** 缺失：`backend/data/` 是 gitignore 的部署时产物，需在云端从 `stocks` 表生成（`/tmp/build_aliases.py`，7,972 条；dict_match 有 stocks 兜底但告警噪音大）——若换机部署必须重建

## 10. 架构铁律与回填迁移 d 集群（2026-09-19 owner 定调）

**铁律**（详见仓库根 `AGENTS.md`）：evidence 处理代码一律在 d 集群以 worker 拉取任务消费；云机只做存储（Mongo/PG/Qdrant/Neo4j）与调度面。云侧不再新增/扩容 evidence 处理 worker。

**回填迁移记录（当日）**：
- pod 实底：1,507GB RAM / 255 核 / 出网 pjlab 200；venv Python 3.12
- 停云端 `backfill_keyword_links`（PID 8287）防双跑
- pod 装最小依赖（aliyun 镜像：tuna 缺 sqlalchemy 2.0.36）：sqlalchemy/asyncpg/motor/pydantic-*/openai/tiktoken/httpx —— **numpy 1.26.4 与 torch 2.8.0+metax 完好**（装包前后均验证）
- 配置：pod 持有锁，直接 `ssh cloud 'cat backend/.env' > /root/wq/backend/.env`（云端 PG=5433 / Mongo=27018 非标端口）
- 正向隧道：`ssh -N -L 127.0.0.1:5433 -L 127.0.0.1:27018 root@124.221.188.38`（由本地 Mac 持有，disable_timeout）
- 连通验证：PG `select 1` ✅ / Mongo `kg_evidence` 计数 ✅
- 试跑：`--limit 200 --concurrency 4`，观察吞吐与 pjlab 429，再定全量并发（目标 8~12、1~2 天跑完 312k 池）

**Pod worker 运维三条**：
1. worker/隧道必须前台持有式挂起（Mac 后台 bash disable_timeout，86400s 上限需每日重挂，幂等断点无损失）
2. 断点 = Mongo `keyword_extraction` 缓存标记，重启即续
3. 音量协调：云端 knowledge_worker（新证据 link 消费）仍共享 pjlab 网关，试跑期并发 4 起步，防 429 连坐

## 11. 生产 flip 完成记录（2026-09-19 14:31 检查点自动执行）

**前置全绿**：
- 48k 向量直写修复收官：48,471/48,471，**零失败**（10:53→14:11，实测 ~190/min）
- gold 六点抽验（uuid5 直查）：**6/6 全 200**
- 终跑 eval：link **1.000**（2/2）；semantic **0.556**（timeline 0.67 / cross 0.00 / theme 1.00），与 12:10 结果逐位一致

**flip 动作链**：
1. `backend/.env`：`ENABLE_KG_EXTRACTION=false`（grep 守卫幂等）
2. compose 发现漏键：**docker-compose.yml 原本没有 CONsumed 这两个环境键的声明**——`up` 后容器 env 里查无此旗。已在 backend/scheduler/job-worker 三个 service 的 environment 段补 `ENABLE_KG_EXTRACTION=${VAR:-false}` 与 `LLM_DISABLE_THINKING=${VAR:-false}`（compose default 即 flip 态），重建 backend 容器后 `docker inspect` 确认两旗在场
3. `systemctl restart qingshui-scheduler`
4. d 集群代码同步：git archive(HEAD) → **Mac 中继** scp → pod /root/wq 解包（云→pod 无法直连，方向永远 pod→引干线/云，Mac 是唯一双向跳板）；pod 补生成 company_aliases.json（7,972 条）
5. 云仓库与 GitHub 对齐：**bundle 中继**（cloud 3ce6432 → 本地 4f62ad5）。教训：云端 git 树长期落后于 origin，任何以 cloud 为源的 archive/tar 都可能缺近几日 commit——**发布前必须比对 `git log -1`**

**效果**：旧三元组 combined 抽取管道停止入队（存量 150,973 skipped 保持不动，690 failed 已 Frozen）；新证据只走 vector + link 两条任务;链接层成为唯一知识层。

## 12. LLM thinking 事故与修复（2026-09-19，迁移排障记录）

**现象**：迁移到 d 集群后回填实测仅 14.5/min（压测同池可达 68~100）。
**根因**：`LLM_DISABLE_THINKING` 从未在任何 .env 设置（默认 False），chat_async 只对 deepseek/minimax 显式关 thinking。Qwen3.6-35B-A3B-FP8 为推理模型，长年报证据"想"到 180s 流总超时（A/B 实测：ON 133.6s 均值，一半撞墙；OFF 2~4s）。
**修复**：pod + cloud .env 双加 `LLM_DISABLE_THINKING=true`；compose 三 service 补键（同 §11）；实测回填 24 槽 **101/min**（14.5 → 101，约 7 倍）。
**教训（换模型必查清单）**：① thinking 流费与该模型推理属性；② chat_async 是否 stream + 总超时兜底值；③ 网关无 429 时以"长尾卡死"形态限流，压测表不呈线性——按 p95 观察而非并发峰值。
