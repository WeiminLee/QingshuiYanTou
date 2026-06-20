# 知识构建层架构设计

> 日期：2026-06-20
> 范围：端到端知识系统（data_pipeline → knowledge → reasoning/tools）
> 目标：文档化现有架构，明确模块边界、数据流、接口契约、四层知识导航

---

## 1. 系统概览

### 1.1 系统边界

知识系统覆盖三个子系统：

| 子系统 | 目录 | 核心职责 |
|--------|------|----------|
| 数据采集层 | `data_pipeline/` | 数据源对接、调度触发、Job Queue、文件存储 |
| 知识构建层 | `knowledge/` | Evidence 管理、RAG 抽取、图谱写入、向量索引、冲突检测 |
| 知识查询层 | `reasoning/tools/knowledge/` | Agent 工具封装、resolve/expand 查询原语、四层导航 |

### 1.2 核心数据流

```
外部数据源 (akshare/cninfo/minishare/baostock)
    │
    ▼
┌─────────────────────────────────┐
│  数据采集层 (data_pipeline)      │
│  Fetcher → Client → FileStorage │
│  Scheduler → JobQueue → Worker  │
└────────────┬────────────────────┘
             │ ① 入库 PostgreSQL (源数据)
             │ ② 入队 ingestion_jobs
             │
             ▼
┌─────────────────────────────────┐
│  知识构建层 (knowledge)          │
│  EvidenceBuilder → EvidenceQueue│
│  EvidenceWorker → RAGExtractor  │
│  EntityService → RelationService│
│  VectorClient → Contradiction   │
└────────────┬────────────────────┘
             │ ③ 写入 Neo4j (图谱)
             │ ④ 写入 Qdrant (向量)
             │ ⑤ 写入 MongoDB (Evidence)
             │
             ▼
┌─────────────────────────────────┐
│  知识查询层 (reasoning/tools)    │
│  resolve → expand(select,filter)│
│  fetch_evidence (L1追溯)        │
└─────────────────────────────────┘
             │
             ▼
        Agent (LLM)
```

### 1.3 存储后端

| 后端 | 用途 | 关键 Collection/Table |
|------|------|----------------------|
| PostgreSQL | 源数据 + Job Queue | `ingestion_jobs`, `stocks`, `company_profiles` |
| MongoDB | Evidence + 抽取索引 | `kg_evidence`, `kg_extraction_jobs`, `kg_extraction_index` |
| Neo4j | 知识图谱 | `Entity` 节点, `RELATES` 边, `CONTRADICTS` 边 |
| Qdrant | 向量索引 | entity/relation/chunk 向量 |

---

## 2. 数据采集层 (data_pipeline)

### 2.1 模块结构

```
data_pipeline/
├── fetcher.py              # 编排器：协调各数据源采集
├── data_source.py          # 数据源封装：akshare/cninfo/baostock
├── cninfo_client.py        # 巨潮资讯客户端
├── minishare_client.py     # Minishare 备选源
├── file_storage.py         # 文件存储：PDF下载、URL归一化
├── rate_limiter.py         # 限流器：同步/异步两种
├── scheduler.py            # APScheduler 定时任务
├── job_queue.py            # Durable Job Queue (PostgreSQL)
├── job_producers.py        # Job 生产者
├── job_handlers.py         # Job 处理器
├── job_worker.py           # Job 消费者
├── progress.py             # 进度追踪
├── *_filter.py             # 数据过滤（公告/研报/IRM）
└── services/               # 业务服务（stock/kline/report...）
```

### 2.2 核心组件职责

| 组件 | 职责 | 关键接口 |
|------|------|----------|
| `Fetcher` | 编排采集流程，协调 Client/Storage/Filter | `fetch_announcements()`, `fetch_irm()`, `fetch_reports()` |
| `DataSourceClient` | 封装数据源 API 调用 | `get_irm()`, `get_stock_kline()`, `get_cls_telegraph()` |
| `FileStorage` | 管理文件存储路径、PDF 下载 | `save_report()`, `download_notice()`, `_resolve_pdf_url()` |
| `RateLimiter` | 限流控制，防止 API 过载 | `wait()`, `acquire()` |
| `Scheduler` | APScheduler 定时任务注册与触发 | `_run_*_job()`, `_fire_all_once()` |
| `IngestionJobQueue` | PostgreSQL 持久化任务队列 | `enqueue()`, `claim()`, `mark_success()`, `mark_failure()` |
| `IngestionJobWorker` | 消费 Job Queue，执行采集任务 | `run_once()`, `run_loop()` |

### 2.3 Job Queue 架构

```
Producer                    Queue (PostgreSQL)                    Consumer
   │                              │                                   │
   │ enqueue(job)                 │                                   │
   ├─────────────────────────────►│ ingestion_jobs                    │
   │                              │ - id, job_type, params            │
   │                              │ - status: pending/running/...     │
   │                              │ - attempts, max_attempts          │
   │                              │                                   │
   │                              │◄──────────────────────────────────┤
   │                              │  claim() FOR UPDATE SKIP LOCKED   │
   │                              │───────────────────────────────────►│
   │                              │  return job                       │
   │                              │                                   │
   │                              │◄──────────────────────────────────┤
   │                              │  mark_success() / mark_failure()  │
```

**状态机**：
```
pending → running → success
                 ↘ failure → pending (重试，指数退避)
                 ↘ dead (超过 max_attempts)
```

### 2.4 关键数据流

**公告采集**：
```
Scheduler 触发 → enqueue_recent_cninfo_jobs()
→ JobWorker.claim() → execute_ingestion_job()
→ cninfo_client.query_announcements()
→ file_storage.download_notice()
→ PostgreSQL 入库
```

**IRM 采集**：
```
Scheduler 触发 → enqueue_irm_company_jobs()
→ JobWorker → akshare.stock_zh_a_spot_em()
→ data_source.get_irm()
→ PostgreSQL 入库
```

---

## 3. 知识构建层 (knowledge)

### 3.1 模块结构

```
knowledge/
├── extraction/                    # ── 抽取子模块 ──
│   ├── rag_extractor.py           # RAG 抽取引擎（核心）
│   ├── rag_prompts.py             # Prompt 模板
│   ├── chunker.py                 # 文档分块
│   ├── chunk_dedup.py             # 分块去重
│   ├── light_extractor.py         # 轻量实体识别
│   ├── signal_extractor.py        # 规则信号提取
│   └── announcement_filter.py     # 公告关键词过滤
│
├── ingestion/                     # ── 摄入子模块 ──
│   ├── announcement_parser.py     # 公告 PDF 下载+章节切分
│   └── pdf_parser.py              # PDF 解析
│
├── entity_service.py              # Neo4j 实体节点 CRUD
├── entity_resolver.py             # 实体消解（editdistance + LLM）
├── entity_id.py                   # 实体 ID 生成与归一化
├── stock_name_resolver.py         # 股票名称→ts_code 映射
│
├── relation_service.py            # Neo4j RELATES 边 CRUD
├── relation_types.py              # 关系类型常量（旧版，待清理）
│
├── evidence.py                    # Evidence 数据结构
├── evidence_service.py            # MongoDB Evidence 存储
├── evidence_worker.py             # Evidence 异步消费 Worker
├── evidence_builders.py           # Evidence Builder（复杂版）
├── evidence_builders_simple.py    # Evidence Builder（简化版）
│
├── kg_extractor.py                # KG 抽取主引擎（编排）
├── kg_indexer.py                  # 提取索引（防重）
├── kg_metrics.py                  # 图谱质量指标
│
├── confidence.py                  # 置信度体系
├── contradiction.py               # 冲突检测
├── state_machine.py               # 行业状态机
├── state_writer.py                # 状态写入 Neo4j
├── structured_fact_service.py     # 结构化事实持久化
│
├── vector_client.py               # Qdrant 客户端
├── vector_ops.py                  # 向量操作辅助
├── irm_extractor.py               # IRM 互动易抽取
├── pdf_rotator.py                 # PDF 旋转处理
│
├── feedback_service.py            # 反馈服务
├── file_indexer.py                # 文件索引
├── knowledge_package.py           # 知识包导出
│
└── api/                           # ── API 子模块 ──
    ├── concept.py
    ├── entities.py
    ├── feedback.py
    ├── kg_extraction.py
    ├── knowledge_package.py
    └── relations.py
```

### 3.2 职责分组与耦合分析

| 分组 | 文件 | 职责 | 耦合问题 |
|------|------|------|----------|
| **抽取引擎** | `rag_extractor`, `rag_prompts`, `chunker`, `chunk_dedup` | LLM 调用与结果解析 | ✅ 内聚良好 |
| **知识图谱存储** | `entity_service`, `relation_service`, `entity_id`, `entity_resolver` | Neo4j 节点/边 CRUD | ⚠️ `entity_resolver` 依赖 LLM，与纯存储层混在一起 |
| **Evidence 管理** | `evidence`, `evidence_service`, `evidence_worker`, `evidence_builders*` | Evidence 生命周期 | ⚠️ 两套 Builder 并存（复杂版/简化版），职责重叠 |
| **编排与调度** | `kg_extractor`, `kg_indexer`, `evidence_worker` | 抽取流程编排 | ⚠️ `kg_extractor` 职责过重，既编排又调用存储 |
| **向量与索引** | `vector_client`, `vector_ops`, `kg_metrics` | Qdrant 操作与质量指标 | ✅ 内聚良好 |
| **业务逻辑** | `confidence`, `contradiction`, `state_machine`, `state_writer`, `structured_fact_service` | 投资研究业务规则 | ⚠️ `state_machine`/`state_writer` 与 KG 存储紧耦合 |

### 3.3 Schema 统一：V1.3（3 类实体）

**决策**：统一为 V1.3 Schema，删除 V4 的 7 类 Schema。

| 实体类型 | 说明 | 属性归入规则 |
|----------|------|-------------|
| **Company** | 上市公司、客户、供应商、竞争对手 | Category(行业板块) → `industry` 属性；Project(项目) → `projects` 属性 |
| **Product** | 具体产品、材料、设备、服务 | Technology(技术) → `technology` 属性；Application(应用) → `application` 属性 |
| **Metric** | 量化/趋势指标（含数字+单位） | 不归入属性，保持独立实体 |

**Prompt 统一方案**：将 `EXTRACTION_PROMPT_V4` 和 `ANNOUNCEMENT_EXTRACTION_PROMPT` 合并为统一的 `EXTRACTION_PROMPT_V13`，保留两者各自的优点：

| 来源 | 保留内容 |
|------|----------|
| V4 Prompt | stmt_type（Fact/Claim/Estimate）、RELATES 格式、Metric 结构化输出 |
| 公告 Prompt | 公告主体公司必抽规则、业绩预告/年报指标格式、来源标注 |
| V1.3 Prompt | 3 类实体白名单、7 类噪声禁止规则、显式陈述原则 |

**V4 清理范围**：

| 类别 | 影响处数 | 说明 |
|------|----------|------|
| `ENTITY_TYPES_V4` 定义 | 5 | 改为 `ENTITY_TYPES`（3 类） |
| Prompt 实体类型段落 | 12 | 删除 Category/Application/Technology/Project 行 |
| `announcement_v4` source_type | 3 | 统一为 `announcement` |
| 函数名含 `_v4` 后缀 | ~10 | `upsert_relates_v4` → `upsert_relates`，`_parse_relates_v4` → `_parse_relates` |
| schema_version 字段 | 2 | 统一为 `"v1.3"` |

### 3.4 核心抽取流程

```
kg_extractor.extract_text()
    │
    ▼
1. Evidence 构建
   evidence_builders_simple.build_*_evidence()
   → MongoDB kg_evidence upsert
   → MongoDB kg_extraction_jobs enqueue
    │
    ▼
2. Evidence Worker 消费
   evidence_worker._process_job()
    │
    ▼
3. RAG 抽取
   rag_extractor.extract_sync()
   │  a. chunker.chunk_by_token()  → 文本分块
   │  b. LLM 调用 (gleaning × 2 轮)
   │  c. _parse_chunk_output()     → 解析实体/关系
   │  d. _parse_relates()          → 解析 RELATES 边
    │
    ▼
4. 图谱写入
   entity_service.upsert_entity()         → Neo4j 节点
   relation_service.upsert_relates()      → Neo4j RELATES 边
   vector_client.upsert_entity_vector()   → Qdrant 向量
    │
    ▼
5. 后处理
   contradiction.detect_contradiction()   → CONTRADICTS 边
   signal_extractor.persist_signals()     → Company 属性
   state_writer.write_state_to_neo4j()    → 行业状态
```

---

## 4. 知识存储层

### 4.1 Neo4j 图谱设计

#### 节点类型

| 标签 | 属性 | ID 规则 |
|------|------|---------|
| `Entity` | `name`, `type`(Company/Product/Metric), `description`, `source` | `C_{norm}` / `P_{norm}` / `M_{norm}`（norm=名称归一化） |
| `Company` 额外属性 | `industry`, `projects`, `ts_code`, `list_status` | — |

#### 边类型

| 边 | 属性 | 说明 |
|----|------|------|
| `RELATES` | `text`, `weight`, `stmt_type`, `relation_subtype`, `source`, `confidence` | 自然语言关系，核心边 |
| `CONTRADICTS` | `reason`, `polarity` | 冲突检测产出 |

**stmt_type 取值**：
- `Fact` — 原文明确陈述的客观事实（权重 3）
- `Claim` — 公司/管理层主张（权重 2）
- `Estimate` — 预测推测（权重 1）

**relation_subtype**：由 `infer_relation_type()` 从关系描述推断，如 `supplies_to`、`competes_with`、`produces` 等。

### 4.2 Qdrant 向量设计

| Collection | 向量来源 | 用途 |
|------------|----------|------|
| entity | 实体 name+description embedding | 语义实体搜索 |
| relation | 关系 text embedding | 语义关系搜索 |
| chunk | 文档分块 embedding | RAG 检索 |

### 4.3 MongoDB 设计

| Collection | 核心字段 | 用途 |
|------------|----------|------|
| `kg_evidence` | `evidence_id`, `source_type`, `chunks[]`, `extraction_status` | Evidence 原子层存储 |
| `kg_extraction_jobs` | `job_id`, `evidence_id`, `status`(pending/running/done/failed) | 抽取任务队列 |
| `kg_extraction_index` | `doc_fingerprint`, `status` | 防重复抽取索引 |

**Evidence 状态机**：
```
pending → extracting → done
                     ↘ failed
```

---

## 5. 知识查询层 — 统一查询原语

### 5.1 设计理念

**核心原语**：`resolve → expand(select, filter)`

- **resolve**：自然语言 → 图谱实体锚定
- **expand**：声明式受控展开，Agent 按需选择查询字段和过滤条件

**为什么不用枚举 mode**：枚举 mode（profile/chain/peers/...）限制了扩展性，每新增分析场景需加 mode，且无法自由组合。声明式 expand 让 Agent 自行决定查询什么，系统按 select 字段映射到底层 Cypher 查询。

### 5.2 resolve：实体锚定

```
resolve(query: str, entity_type?: "Company"|"Product"|"Metric") → Entity | null

功能：
  1. 名称归一化（全角→半角、简称→全称）
  2. 向量语义搜索
  3. 多条匹配时选最相关

返回：
  {
    entity_id: "C_新雷能",
    name: "新雷能",
    type: "Company",
    score: 0.95
  }
```

### 5.3 expand：声明式受控展开

```
expand(entity_id: str,
       select: str[],          // 要获取的字段
       filter?: {              // 过滤条件
         direction?: "upstream"|"downstream"|"both",
         relation_subtypes?: str[],
         stmt_types?: str[],
         dimension?: str,
         depth?: int,
         limit?: int
       }
) → SubGraph
```

#### select 字段定义

| select | 含义 | 返回内容 | 底层 Cypher 映射 |
|--------|------|----------|-----------------|
| `properties` | 实体属性 | name, type, industry 等 | `MATCH (e) RETURN e` |
| `relations` | 关联 RELATES 边 | 按 filter 过滤后的边列表 | `MATCH (e)-[r:RELATES]-(t) WHERE filter(r) RETURN r, t` |
| `metrics` | 关联 Metric 节点 | 含 stmt_type 聚合 | `MATCH (e)-[r]->(m:Entity {type:"Metric"}) RETURN r, m` |
| `products` | 关联 Product 节点 | — | `MATCH (e)-[r]->(p:Entity {type:"Product"}) RETURN r, p` |
| `companies` | 关联 Company 节点 | — | `MATCH (e)-[r]->(c:Entity {type:"Company"}) RETURN r, c` |
| `upstream` | 上游路径 | 沿 supplies_to 反向遍历 | `MATCH path=(e)<-[:RELATES*1..depth]-(prev) WHERE is_upstream RETURN path` |
| `downstream` | 下游路径 | 沿 supplies_to 正向遍历 | `MATCH path=(e)-[:RELATES*1..depth]->(next) WHERE is_downstream RETURN path` |
| `peers` | 共邻居竞争实体 | 共享 Product 的 Company | `MATCH (e)-[:RELATES]->(n)<-[:RELATES]-(peer) WHERE peer<>e RETURN peer, count(n)` |
| `divergence` | 预期差视图 | Fact vs Estimate 对比 | 聚合 metrics + 按 stmt_type 分组 |

#### filter 参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `direction` | `"upstream"\|"downstream"\|"both"` | 产业链遍历方向 |
| `relation_subtypes` | `str[]` | 按关系子类型过滤（如 `["supplies_to", "produces"]`） |
| `stmt_types` | `str[]` | 按陈述类型过滤（如 `["Fact", "Estimate"]`） |
| `dimension` | `str` | 按业务维度过滤（如 `"financial"`, `"supply_chain"`） |
| `depth` | `int` | 遍历深度（默认 1） |
| `limit` | `int` | 返回数量限制（默认 20） |

#### 调用示例

```python
# 个股概览
expand("C_新雷能", select=["properties", "products", "metrics"])

# 产业链上游
expand("C_新雷能", select=["upstream"], filter={direction: "upstream", depth: 3})

# 竞争对比
expand("C_新雷能", select=["peers", "metrics"])

# 预期差
expand("C_新雷能", select=["divergence", "metrics"])

# 自由组合：产业链 + 预期差
expand("C_新雷能", select=["upstream", "divergence"], filter={depth: 2})

# 精细过滤：只看供应链相关的 Fact
expand("C_新雷能", select=["relations"], filter={stmt_types: ["Fact"], relation_subtypes: ["supplies_to"]})
```

### 5.4 Agent 游走模式

```
┌─────────────────────────────────────────────────────────┐
│                    用户查询                              │
└─────────────────────┬───────────────────────────────────┘
                      ▼
              ┌───────────────┐
              │   RESOLVE     │ 锚定实体
              └───────┬───────┘
                      ▼
              ┌───────────────┐
              │ EXPAND        │ 实体概览
              │ (properties,  │
              │  products,    │
              │  metrics)     │
              └───────┬───────┘
                      ▼
         ┌────────────┼────────────┐
         ▼            ▼            ▼
   ┌───────────┐ ┌───────────┐ ┌───────────┐
   │EXPAND     │ │EXPAND     │ │EXPAND     │
   │(upstream/ │ │(peers,    │ │(divergence│
   │ downstream│ │ metrics)  │ │ , metrics)│
   │)          │ │           │ │           │
   │产业链分析  │ │竞争分析    │ │预期差挖掘  │
   └───────────┘ └───────────┘ └───────────┘
         │            │            │
         └────────────┼────────────┘
                      ▼
              递归 EXPAND 或
              调用 L1 工具（fetch_evidence）
```

### 5.5 场景示例

**场景 1：产业链分析**
```
用户: 分析新雷能的产业链上游

Agent:
1. resolve("新雷能") → C_新雷能
2. expand("C_新雷能", select=["properties", "products"])
   → products: ["电源模块", "精密温控"]
3. expand("P_电源模块", select=["upstream"], filter={direction: "upstream", depth: 3})
   → paths: [电源模块 → 铜箔 → 铜]
4. fetch_evidence(...) → 追溯原文
```

**场景 2：竞争分析**
```
用户: 对比新雷能和英维克的竞争力

Agent:
1. resolve("新雷能") → C_新雷能
2. expand("C_新雷能", select=["peers", "metrics"])
   → peers: [{英维克, shared_products: ["精密温控"]}]
3. expand("C_英维克", select=["properties", "metrics"])
   → 对比两者的 metrics
4. expand("C_新雷能", select=["divergence"]) vs expand("C_英维克", select=["divergence"])
   → 对比预期差
```

**场景 3：预期差挖掘**
```
用户: 新雷能有哪些预期差？

Agent:
1. resolve("新雷能") → C_新雷能
2. expand("C_新雷能", select=["divergence", "metrics"])
   → 营收、毛利率存在分歧
3. expand("C_新雷能", select=["upstream"], filter={direction: "upstream", depth: 2})
   → 追踪上游是否有类似分歧（传导分析）
4. fetch_evidence(...) → 追溯原文验证
```

### 5.6 四层知识导航映射

| 层级 | 名称 | 查询原语 | 数据来源 | 内容示例 |
|------|------|----------|----------|----------|
| **L4** | 认知抽象层 | `expand(select=["properties"])` + `state_machine` | Neo4j Company.state | "储能行业处于成长期" |
| **L3** | 叙事逻辑层 | `expand(select=["relations", "upstream", "downstream"])` | Neo4j RELATES 边 | "宁德时代 → 三元锂电池 → 储能" |
| **L2** | 结构化索引层 | `expand(select=["properties", "metrics"])` | Neo4j Entity 属性 | "宁德时代: 2024营收120亿" |
| **L1** | 证据原子层 | `fetch_evidence(evidence_id)` | MongoDB kg_evidence | 公告原文 PDF 章节 |

### 5.7 stmt_type 在查询中的应用

| stmt_type | Agent 行为建议 |
|-----------|----------------|
| `Fact` | 直接采信，作为确定性证据 |
| `Claim` | 需交叉验证，查找其他来源佐证 |
| `Estimate` | 标注为预测，需补充假设条件和时间范围 |

---

## 6. 附录

### 6.1 模块依赖图

```
data_pipeline/
  fetcher ──→ data_source, cninfo_client, minishare_client, file_storage
  scheduler ──→ job_producers
  job_worker ──→ job_queue, job_handlers
  job_handlers ──→ fetcher, file_storage

knowledge/
  kg_extractor ──→ rag_extractor, entity_service, relation_service, vector_client,
                   contradiction, signal_extractor, state_writer, evidence_service
  rag_extractor ──→ rag_prompts, chunker, chunk_dedup
  evidence_worker ──→ evidence_service, kg_extractor
  entity_resolver ──→ entity_service, LLM
  relation_service ──→ Neo4j driver
  vector_client ──→ Qdrant client

reasoning/tools/knowledge/
  neo4j/kg_search ──→ neo4j/neo4j (driver)
  evidence ──→ knowledge/evidence_service
```

### 6.2 完整文件清单

**data_pipeline/** (25 文件)
- `fetcher.py`, `data_source.py`, `cninfo_client.py`, `minishare_client.py`
- `file_storage.py`, `rate_limiter.py`, `scheduler.py`
- `job_queue.py`, `job_producers.py`, `job_handlers.py`, `job_worker.py`
- `progress.py`, `monitor.py`
- `announcement_filter.py`, `report_filter.py`, `irm_filter.py`, `irm_pipeline.py`
- `services/`: `concept_service.py`, `kline_service.py`, `market_service.py`, `report_service.py`, `stock_service.py`
- `api/`: `data.py`, `data_sync.py`, `information.py`, `monitor.py`, `monitor_api.py`, `stocks.py`

**knowledge/** (30+ 文件)
- `extraction/`: `rag_extractor.py`, `rag_prompts.py`, `chunker.py`, `chunk_dedup.py`, `light_extractor.py`, `signal_extractor.py`, `announcement_filter.py`
- `ingestion/`: `announcement_parser.py`, `pdf_parser.py`
- `entity_service.py`, `entity_resolver.py`, `entity_id.py`, `stock_name_resolver.py`
- `relation_service.py`, `relation_types.py`
- `evidence.py`, `evidence_service.py`, `evidence_worker.py`, `evidence_builders.py`, `evidence_builders_simple.py`
- `kg_extractor.py`, `kg_indexer.py`, `kg_metrics.py`
- `confidence.py`, `contradiction.py`, `state_machine.py`, `state_writer.py`, `structured_fact_service.py`
- `vector_client.py`, `vector_ops.py`, `irm_extractor.py`, `pdf_rotator.py`
- `feedback_service.py`, `file_indexer.py`, `knowledge_package.py`
- `api/`: `concept.py`, `entities.py`, `feedback.py`, `kg_extraction.py`, `knowledge_package.py`, `relations.py`

**reasoning/tools/knowledge/** (8 文件)
- `evidence.py`
- `announcement/__init__.py`
- `neo4j/__init__.py`, `neo4j/neo4j.py`, `neo4j/kg_search.py`, `neo4j/query_classify.py`, `neo4j/relevance.py`, `neo4j/search_strategy.py`
- `research_report/__init__.py`

### 6.3 配置项汇总

| 配置 | 位置 | 说明 |
|------|------|------|
| `NEO4J_URI/USER/PASSWORD` | env | Neo4j 连接 |
| `QDRANT_URL/API_KEY` | env | Qdrant 连接 |
| `MONGODB_URI` | env | MongoDB 连接 |
| `DATABASE_URL` | env | PostgreSQL 连接 |
| `LLM_MODEL` | env | LLM 模型名 |
| `MINISHARE_DATA_ROOT` | env | 外部数据目录 |
| `akshare_rate_limit` | `rate_limiter.py` | akshare 限速 80 req/min |
| `cninfo_pdf_rate_limit` | `rate_limiter.py` | cninfo PDF 限速 |
| `gleaning_rounds` | `rag_extractor.py` | gleaning 轮数（默认 2） |
