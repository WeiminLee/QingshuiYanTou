# 链接层 A/B 评估操作手册

对知识层重构（Evidence 链接层 + 判断台账，见 `docs/superpowers/specs/2026-09-18-knowledge-layer-redesign-design.md`）执行检索层 A/B 评估：语义向量基线（semantic）vs 链接层（link），验收标准对应 spec 迁移路径 P2。

**前置条件**：需要可访问的 PostgreSQL、MongoDB（kg_evidence 真源）、Qdrant 和 LLM gateway（Embedding / flash 浅提取）。gold set（`backend/eval/gold_set_v1.json`）中的 expected_evidence_ids 当前为占位符，**未回填前 Recall 数字无意义**——必须先完成第 2 步的数据收集协议，评估才有意义。

**当前状态（2026-09-18）**：代码已全部落地；本手册编写时无部署环境（PG/Mongo/Qdrant/LLM gateway 均不可用），A/B 评估尚未实际执行，无任何已产出的评估数字。以下步骤须在有真实数据的环境按序执行。

## 1. 数据库迁移（链接层 + 台账建表）

迁移 027（`link_keywords` / `link_links`）和 028（`observations` / `findings` / `watermarks`）尚未在任何环境执行过，评估前先升库：

```bash
cd backend && uv run --no-sync python -m alembic upgrade head
```

可用 `uv run --no-sync python -m alembic current` 确认版本到 `028`。

## 2. 回填 gold set（数据收集协议）

完整协议见 `backend/scripts/eval_retrieval.py` 模块 docstring，此处为操作摘要：

1. gold set 中 `expected_evidence_ids` / `hard_negative_evidence_ids` 目前是两类占位：`"<真实evidence_id_N>"`（worked example 占位）和 `"EV:<64位hex>"`（格式样例 ID，非真实数据）；
2. 在 Mongo 中按公司检索候选证据：`db.kg_evidence.find({"subject_hint.ts_code": "<ts_code>"})`，可再按 `text_excerpt` / `source_name` 关键词过滤（如"产线""毛利率"）；
3. 逐条人工确认相关性（时间线类看演进覆盖，横截面类看跨公司命中），将真实 `evidence_id`（`"EV:" + sha256`，见 `app/knowledge/evidence.py` 的 `stable_evidence_id`）替换进 `expected_evidence_ids`；
4. `hard_negative_evidence_ids` 可选，预留后续精细评估，暂不参与 Recall@k。

## 3. 回填链接层

先 dry-run 确认待回填规模，再实际写入：

```bash
cd backend && uv run --no-sync python -m scripts.backfill_keyword_links --dry-run
cd backend && uv run --no-sync python -m scripts.backfill_keyword_links
```

说明：

- 回填 = 逐条 evidence 走 LLM 浅提取（Company/Product/Metric）+ 词典匹配（subject 兜底 / dimension / stage），幂等写入 `link_keywords` / `link_links`；
- 断点续跑：只处理尚无 `keyword_extraction` 缓存的 evidence，中断后直接重跑即可；
- 全量约 27.6 万条，LLM 限速 22 RPM 下约 9 天；可先用 `--limit 100` 小批试跑，抽人审链接质量后再放量。

## 4. 跑基线（semantic backend）

现有 Qdrant 向量检索（chunks 通道）：

```bash
cd backend && uv run --no-sync python -m scripts.eval_retrieval --backend semantic --k 20
```

## 5. 跑链接层（link backend）

```bash
cd backend && uv run --no-sync python -m scripts.eval_retrieval --backend link --k 20
```

## 6. 验收标准（spec P2）

**链接层在 timeline / cross_section 类条目上的 mean Recall@k 不低于 semantic 基线。**

- 比较口径：只取 `type` 为 `timeline` / `cross_section` 的 query（按 `query_id` 前缀区分），分别对两个 backend 求各查询 Recall@k 的均值再对比；
- **theme 条目不参与比较**：theme 类查询是向量通道（semantic_search / browse）的职责，链接层对 `dimension=None` 的 theme 条目直接返回空结果（Recall 恒为 0）。脚本打印的全量 mean 包含 theme 条目，link 侧会被拉低，**不要直接用全量均值做验收判断**；
- 未达标时的排查方向：gold set 是否按数据收集协议逐条人工确认过；链接层回填是否已跑完目标公司/维度；keyword 是否被词典归并进错误的 canonical。

## 7. 生产切换

评估达标后，停发三元组 combined job（Neo4j 不再有新写入）：

1. 云端 `backend/.env` 添加：

   ```text
   ENABLE_KG_EXTRACTION=false
   ```

2. 重启调度器：

   ```bash
   systemctl restart qingshui-scheduler.service
   ```

## 8. 已知遗留事项

- **Mongo 中已 pending 的 combined job 仍会被 worker 消费**：`ENABLE_KG_EXTRACTION=false` 只停新发，不停消费。如需彻底停跑三元组抽取，须另行清理 job 队列中的存量 combined pending；
- **`extraction_status` 初始化仍含 `combined: pending` 占位**：新 evidence 入库时状态字典里保留该键（无害占位），未随开关移除；
- zhparser 全文检索、涌现聚类、embedding 概念层附着（spec §4.4 第 2/3 层）为后续迭代，本手册不含；
- `resolve` / `expand` 过渡期只读保留（承接传导查询），`neo4j_kg_search` 已在工具注册层下线；
- **部署前必须先 `alembic upgrade head`（027/028）**：否则链接层/台账表不存在，link job 会因表缺失而反复失败，进入失败循环；
- **`server_start.sh` 启动的 evidence worker 容器需重建**：容器内代码是构建时打入的，重启容器不会更新，须重建后才能拿到 link 等新 job 类型的处理逻辑；
- **存量 pending combined job 在排空前仍会被消费**（同本节首条）：切换开关后需关注 worker 日志，直至存量排空；
- **回填断点续跑以 keyword_extraction 缓存为键**：空文本 evidence 不产生缓存，每轮回填都会重新列出（无害，仅重复列名不重复扣 LLM 配额）；
- **雷达信号已由 link job 自动产出**：建链完成后机械候选落库并对比水位线发雷达信号；agent 确认路径 `write_observation` 与之共用同一水位线，双边只升不降。
