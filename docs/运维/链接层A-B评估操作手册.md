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
