# Neo4j 除役记录

日期：2026-10-13 · 决策：**除役（不补装）** · 状态：已执行（代码面零依赖，570 测试绿）
前置调研：2026-10-13 对四类活进程（backend / data-mcp / scheduler / worker）逐一正向
追调用链，确认 Neo4j 依赖全景；本文引用的结论均以当代码为据。

## 一、为什么是除役

1. **活路径零依赖**：Data MCP 21 工具、readiness 五源、ingestion/worker、金标 3/3（**指 v1
   三案子集全过，非全量金标；v2 全量为 11 案，见 `docs/待办.md`**）全部
   不需要 Neo4j——chemagent 自迁移起就没有 Neo4j，生产和评测一直绿。
2. **真源方向早已确定**：2026-09-18 知识层重设计（草案 §15）明确「新结构全入 PG，
   Neo4j 冻结只读过渡；三元组管线退役」。当时保留的读侧（resolve/expand）只服务旧
   LangChain Agent——该运行时已于 10-13 删除，过渡期已自然终结。
3. **无数据迁移负担**：Neo4j 数据从未迁到 chemagent；云端只读快照待下线再无消费者。
   补装等于把已冻结的组件拖回生产，还要付出部署/运维/双写一致性成本。
4. **风险倒挂**：残留的「注册了但无人调用」的路由（entity/relation/kg/feedback/package）
   一旦被误打即 500；`connection_acquisition_timeout=30s` 意味着最坏挂线程池 30 秒。
   `ENABLE_KG_EXTRACTION` 生产靠 .env 压 false（代码默认 True），误配即复活假成功的
   combined 写入。死代码比没代码危险。

## 二、执行范围（commit githash 见 git log）

**整体删除（43 个文件）**：
- 基础设施：`core/neo4j_client.py`
- 旧三元组管线：`kg_extractor / kg_batch / state_writer / state_machine / contradiction /
  entity_service / relation_service / entity_resolver / structured_fact_service /
  kg_metrics / kg_indexer / summary_aggregator / summary_cache / summary_invalidator /
  knowledge_package / feedback_service / extraction/signal_extractor`（注意：活信号面是
  `app/signals/extractor.py` 的 `RuleSignalExtractor`，未动）
- 无消费者路由：`api/entities / relations / kg_extraction / feedback / knowledge_package`
- 旧管线脚本 ×17（sample_kg_extract / run_extraction / clean_kg_noise 等）＋根目录
  expand_sector_v1_2 / migrate_kg_v1_2

**手术拆分**：
| 文件 | 保留 | 摘除 |
|---|---|---|
| `evidence_worker.py` | vector/signal/link 三类 job | JOB_COMBINED 分支（默认 job_type 改 link） |
| `evidence_service.py` | 队列/幂等/状态回写 | combined enqueue 与 `enable_kg_extraction` 开关 |
| `irm_extractor.py` | `create_irm_evidence_jobs`（活 IRM 链路） | `extract_irm_qa/batch` 直写族 + upsert_irm_* 助手 |
| `pdf_rotator.py` | `rotate_old_pdfs`（scheduler 周任务，Mongo 驱动） | `_mark_neo4j_pdf_rotated` |
| `vector_client.py` | chunk 向量面 + `semantic_search_entities`（读 Qdrant 冻结集合） | `upsert_entity/relation_vector` |
| `signals/kg_propagation.py` | KGPath/Provider 协议 + `build_kg_propagations`（为链接层 Provider 预留插槽） | `Neo4jKGPathProvider` + `neo4j_rows_to_paths`；lightweight 成为唯一传导 |

**配置/部署**：`config.py` 拔 neo4j 三项 + **NEO4J_PASSWORD 必填校验**（chemagent 此前靠
`worker_supervisor.py` 写 dummy 才起得来）+ `ENABLE_KG_EXTRACTION` 开关；requirements 拔
`neo4j` 双行；根 docker-compose 拔 neo4j 服务与 env；`.env.example`/conftest 占位同步清理。
**worker 的 job 轮转默认集合**（combined/vector/signal/link → vector/signal/link）在
`scripts/knowledge_worker.py` 同步收口，误传 combined 会落「unsupported job_type」失败计数
而非假成功。

## 三、数据与读侧交接

- **PG**：三元组 kg_* 表早在 alembic 018 已 drop；唯一孤儿 `summary_registry`
  （`migrations/001_add_summary_registry.sql`）——数据侧遗留，待云端下线一并清理。
- **Qdrant**：`kg_entities`/`kg_relations` 为三元组投影的**冻结只读**集合，仍被
  `/search/semantic (scope=entities)` 读取——保留不动；是否退役属独立决策。
- **Neo4j 本体**：仅存在于云端只读快照，随云端下线自然消失。

## 四、验证

- 全套 pytest：**570 passed / 0 failed**（删旧测试 ×4 文件 + 修剪 ×6 文件，worker 流程
  测试从 combined 重新挂到 signal job 保覆盖）
- `import app.main` 正常；四进程入口零 neo4j import（grep 清零）
- E2E 金标与本除役无耦合（金标从未经过 Neo4j 路径）；chemagent 下次部署一并生效

## 五、遗留观察

- `kg_extraction_jobs`（Mongo 队列名）保留——集合名是历史，本体是活的 vector/link 队列；
  改名涉及存量在途 job，收益低，不动。
- 云端下线前若需捞 Neo4j 数据做归档，一次性 `neo4j-admin dump` 即可，与本仓代码无关。
