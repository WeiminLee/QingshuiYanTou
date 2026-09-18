# 链接层 A/B 评估操作手册（2026-09-18 现实版补记）

> 本文为《链接层A-B评估操作手册》的运维补记，记录 2026-09-18 部署执行后的实际状态与增量操作。
> 全量回填仍在进行（后台），本页状态以当日为准。

## 已执行完毕（2026-09-18）

| 步骤 | 状态 |
|---|---|
| 生产库 alembic 历史 | 生产库此前无 alembic 版本记录 → `stamp 026` 后执行 **027/028**（current=028） |
| 代码同步 | GitHub 直连不可达 → **bundle over SSH**：`git bundle create /tmp/x.bundle <from>..main` + `git pull /tmp/x.bundle main`（云端仓库 `/home/lwm/code/QingShuiTouYan`） |
| LLM 网关 | 生产 `.env` 曾被切到付费中转 tianxuncloud（额度耗尽 403）→ **已切回 pjlab 免费网关**；抽取模型 `Qwen3.6-35B-A3B-FP8`（owner 指定）；对话主力模型暂代 `glm-5.3`（pjlab 无 deepseek-v4-pro-0813） |
| combined 积压 | **150,107 条 pending/running 已批量置 skipped**（可逆：置回 pending 即恢复） |
| link 进程 | `knowledge_worker --job-type link`（daemon，增量）+ `backfill_keyword_links`（全量）均在后台跑 |

## 关键运维脚本（2026-09-18 新增）

| 脚本 | 用途 |
|---|---|
| `scripts/ingest_evidence_ids.py` | 按 evidence_id 精准回填（gold set/单条修复） |
| `scripts/merge_keyword.py` | 字表变体归并（LLM 提议、词典裁决闭环；链接迁移 + merged 标记，可逆幂等） |

词表治理用法示例：`python -m scripts.merge_keyword --layer scope 抛光硅片 外延硅片 --to 硅片`

## A/B 评估当前结果（真实证据条目）

| 查询 | 类型 | link Recall@20 |
|---|---|---|
| 中晶科技产线递进链 | timeline | **1.00** |
| 硅片厂商毛利率对比 | cross_section | **1.00** |
| 主题类（占位） | theme | —（向量通道修复后重填） |

theme 类查询依赖 semantic 基线，被 **d-cluster bge-m3 隧道（9-17 起断）** 阻塞；隧道修复后补回 theme gold 条目重测。

## 遗留事项（按依赖顺序）

1. **d-cluster 隧道修复**（需内网 ssh）：重启 `qingshui-embed-tunnel.sh`，验证 `curl http://172.18.0.1:11434/health`。
2. **全量回填完成**（~2 天，后台自走）；完成后按 `keyword_extraction` 缓存口径核对覆盖数。
3. **生产切换**（binary flip）：`.env` 加 `ENABLE_KG_EXTRACTION=false` → 后端容器 build + 重启、evidence worker 容器重建（`server_start.sh`）、`systemctl restart qingshui-scheduler.service`、d 集群 tar 同步。注意：flag 未翻前，新证据仍会入队 combined（量小，可定期重跑 skip 批处理：`/tmp/mark_combined_skipped.js`）。
4. **词表治理例会**：scope 候选增长 ~2 条/证据，需周期性 merge（工具已就绪）；中期优化方向：prompt 直接请求已知规范键。
5. collation version mismatch（PG 警告）：glibc 升级遗留元数据，择期 `ALTER DATABASE qingshui REFRESH COLLATION VERSION`（需评估索引重建）。
