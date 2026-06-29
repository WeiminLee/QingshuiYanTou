# KG 分层索引体系 — 实体锚定 + 按需生成

> 日期：2026-06-29
> 范围：在现有 L0 图谱之上构建 L1/L2/L3 分层摘要，服务 Agentic Search
> 状态：设计稿

---

## 1. 背景与动机

### 1.1 现状

当前知识图谱已完成 L0 层建设（Neo4j 图谱 + Qdrant 向量索引），Agent 通过 `resolve → expand(select, filter)` 做子图游走。核心问题：

| 问题 | 表现 | 影响 |
|------|------|------|
| 无导航层 | Agent 面对海量节点，不知道从哪个实体切入 | 游走效率低，容易遗漏关键信息 |
| 无预聚合 | 每次查询都要从原始边开始遍历 | 无法快速回答宏观问题（"光模块产业链竞争格局"） |
| 无分层调度 | 无论问题粒度，都走同一套游走路径 | 简单问题过度游走，复杂问题游走不足 |

### 1.2 设计目标

在 L0 之上构建 L1/L2/L3 三层摘要体系，实现：

1. **实体锚定的确定性分层** — 每层锚定在明确的实体 ID 上，不依赖聚类算法
2. **按需生成 + 缓存** — 不预计算全量摘要，Agent 查询时触发生成，缓存复用
3. **零增量维护** — 新数据入库仅标记缓存失效，无需离线批处理
4. **Agent 自主路由** — 按问题粒度自动选择检索层级

### 1.3 设计原则

1. **实体锚定** — 每层摘要的 key 是确定性的实体 ID，可复现、可调试
2. **自然语言关系** — 不依赖预定义关系类型，LLM 读取 RELATES 描述来组织语义
3. **按需生成** — 只生成被实际查询过的摘要，避免全量预计算浪费
4. **级联失效** — L0 变更 → L1 stale → L2 stale → L3 stale，自动传播

---

## 2. 四层架构

```
┌─────────────────────────────────────────────────────────┐
│                      Agent 路由                          │
│                 按问题粒度选择检索层级                     │
└────────────┬────────────────────────────────────────────┘
             │
    ┌────────┴────────┐
    │                 │
    ▼                 ▼
┌───────────┐   ┌───────────┐
│ Qdrant    │   │ Redis/    │
│ 摘要向量   │   │ PG 缓存   │
│ (检索)    │   │ (时效性)  │
└───────────┘   └───────────┘
             │
    ┌────────┴────────────────────────────────────────┐
    │                                                  │
    ▼                                                  ▼
┌──────────────────────────────────────────────────────────┐
│ L3: 产业链视图                                           │
│     锚定: Product + depth=3                              │
│     生成: 遍历所有 Product → 取 L2 摘要 → LLM 组织为链    │
│     缓存 key: "L3:{product_id}:{depth}"                  │
│     失效: 路径上任意 Product 的 L2 缓存失效               │
├──────────────────────────────────────────────────────────┤
│ L2: 产品生态视图                                         │
│     锚定: Product                                        │
│     生成: 聚合所有关联 Company 的 L1 摘要 + LLM 总结      │
│     缓存 key: "L2:{product_id}"                          │
│     失效: 关联的任意 Company 的 L1 缓存失效               │
├──────────────────────────────────────────────────────────┤
│ L1: 公司画像                                             │
│     锚定: Company                                        │
│     生成: 聚合所有 RELATES 边 + LLM 总结                  │
│     缓存 key: "L1:{company_id}"                          │
│     失效: 该 Company 的 RELATES 边有变更                  │
├──────────────────────────────────────────────────────────┤
│ L0: 原始图谱 (已有)                                       │
│     Company / Product / Metric + RELATES（自然语言描述）   │
│     Neo4j + Qdrant                                      │
└──────────────────────────────────────────────────────────┘
```

### 2.1 L1 — 公司画像

**锚定**：`C:{ts_code}` 或 `CO:{hash}`

**输入**：该 Company 的所有 RELATES 边（1-hop）

**聚合规则**：
```
MATCH (c:Company {entity_id: $eid})-[r:RELATES]->(n)
RETURN n.name, n.entity_type, r.text, r.weight, r.stmt_type, r.relation_subtype
ORDER BY r.weight DESC
```

**LLM 生成 Prompt**：
```
你是一个投资研究助手。基于以下公司关联数据，生成该公司的结构化画像。

公司: {company_name}
关联数据:
{relations_text}

请按以下结构输出:
1. 主营产品: 该公司生产/提供的主要产品和服务
2. 技术路线: 该公司采用或研发的核心技术
3. 上下游: 主要客户和供应商关系
4. 关键指标: 重要的财务/经营指标（含数值和时间）
5. 发展状态: 当前所处阶段和关键信号

控制 200 字以内，只基于给定数据，不要编造。
```

**缓存结构**：
```json
{
  "key": "L1:C:300308",
  "entity_id": "C:300308",
  "entity_name": "中际旭创",
  "level": 1,
  "summary": "中际旭创主营800G/1.6T光模块，采用CPO/LPO/硅光技术路线...",
  "products": ["800G光模块", "1.6T光模块", "400G光模块"],
  "metrics_snapshot": ["2025Q1营收150亿", "毛利率35%"],
  "relation_count": 47,
  "generated_at": "2026-06-29T10:00:00Z",
  "data_freshness": "2026-06-29",
  "stale": false
}
```

### 2.2 L2 — 产品生态

**锚定**：`P:{hash}`

**输入**：所有关联该 Product 的 Company 的 L1 摘要 + 该 Product 的 RELATES 边

**聚合规则**：
```
Step 1: MATCH (p:Product {entity_id: $eid})<-[r:RELATES]-(c:Company)
        RETURN c.entity_id, c.name, r.text, r.weight
Step 2: 对每个 Company 查 L1 缓存（命中则复用，未命中则先生成 L1）
Step 3: LLM 合并所有 L1 摘要 + Product 间关系
```

**LLM 生成 Prompt**：
```
你是一个投资研究助手。基于以下产品生态数据，生成该产品领域的竞争格局摘要。

产品: {product_name}
关联公司及画像:
{l1_summaries}

产品间关系:
{product_relations}

请按以下结构输出:
1. 竞争格局: 主要参与者及其市场份额/地位
2. 技术路线: 不同参与者采用的技术方案对比
3. 上下游: 该产品领域的关键上游供应和下游应用
4. 发展趋势: 技术迭代方向和产能扩张动态

控制 400 字以内，只基于给定数据。
```

**缓存结构**：
```json
{
  "key": "L2:P:ABCD1234",
  "entity_id": "P:ABCD1234",
  "entity_name": "800G光模块",
  "level": 2,
  "summary": "800G光模块领域，中际旭创占据龙头地位约40%份额...",
  "company_count": 23,
  "key_technologies": ["CPO", "LPO", "EML", "硅光"],
  "upstream_products": ["光芯片", "DSP", "电芯片"],
  "downstream_products": ["数据中心互联", "AI服务器"],
  "generated_at": "2026-06-29T10:05:00Z",
  "stale": false
}
```

### 2.3 L3 — 产业链视图

**锚定**：`P:{hash}` + `depth=3`

**输入**：从锚定 Product 出发，沿 RELATES 边无方向遍历 depth 跳，收集路径上所有 Product 节点及其 L2 摘要

**聚合规则**：
```
Step 1: MATCH path = (p:Product {entity_id: $eid})-[:RELATES*1..{depth}]-(other:Product)
        收集路径上所有 distinct Product 节点
Step 2: 对每个 Product 查 L2 缓存（命中则复用，未命中则先生成 L2 → L1）
Step 3: 收集 Product 之间的 RELATES 描述文本
Step 4: LLM 阅读关系描述，组织为产业逻辑链
```

**LLM 生成 Prompt**：
```
你是一个投资研究助手。基于以下产品生态数据，组织为产业链视图。

锚定产品: {product_name}
遍历深度: {depth}

各产品生态摘要:
{l2_summaries}

产品间关系描述:
{relation_texts}

请阅读关系描述，判断各产品在产业链中的位置（上游/中游/下游），然后输出:
1. 产业链结构: 按 上游→中游→下游 组织各产品环节
2. 传导逻辑: 需求如何从下游传导到上游
3. 瓶颈环节: 哪些环节存在产能/技术瓶颈
4. 关键公司: 各环节的核心参与者

控制 600 字以内，只基于给定数据。
```

**缓存结构**：
```json
{
  "key": "L3:P:ABCD1234:3",
  "entity_id": "P:ABCD1234",
  "entity_name": "800G光模块",
  "depth": 3,
  "level": 3,
  "summary": "AI算力产业链: 光芯片(上游) → 光模块(中游) → 数据中心(下游)...",
  "segments": [
    { "product": "光芯片", "role": "上游核心器件", "l2_key": "L2:P:CHIP01" },
    { "product": "800G光模块", "role": "中游核心产品", "l2_key": "L2:P:ABCD1234" },
    { "product": "数据中心互联", "role": "下游应用", "l2_key": "L2:P:DC001" }
  ],
  "generated_at": "2026-06-29T10:10:00Z",
  "stale": false
}
```

---

## 3. Agent 路由策略

### 3.1 路由决策流程

```
用户问题
    │
    ▼
┌─────────────────────────────────────────────┐
│  Step 1: resolve 实体锚定                    │
│  "光模块产业链竞争格局" → P:800G光模块       │
│  "中际旭创的客户"       → C:300308          │
└──────────────┬──────────────────────────────┘
               ▼
┌──────────────────────────────────────────────┐
│  Step 2: 层级选择（按问题粒度）               │
│                                              │
│  宏观问题（"产业链/行业格局/赛道分析"）       │
│    → 查 L2 缓存 → 必要时升级到 L3            │
│                                              │
│  中观问题（"某某产品竞争格局/技术路线对比"）  │
│    → 先查 L2 缓存                            │
│                                              │
│  微观问题（"某某公司客户/供应商/业绩"）       │
│    → 先查 L1 缓存 → 需要细节时降到 L0        │
└──────────────┬──────────────────────────────┘
               ▼
┌──────────────────────────────────────────────┐
│  Step 3: 缓存检查 + 按需生成                  │
│                                              │
│  缓存命中且非 stale → 直接返回                │
│  缓存未命中 → LLM 生成 → 写入缓存 → 返回      │
│  缓存命中但 stale → LLM 重新生成 → 更新缓存   │
└──────────────┬──────────────────────────────┘
               ▼
┌──────────────────────────────────────────────┐
│  Step 4: Agent 决策                          │
│                                              │
│  摘要足够 → 直接基于摘要回答                  │
│  需要细节 → 降级到 L0 做子图游走              │
│               resolve → expand(select,filter) │
│  需要对比 → 跨 Product/Company 并行查摘要     │
│  需要追溯 → fetch_evidence(原文)              │
└──────────────────────────────────────────────┘
```

### 3.2 路由场景示例

| 用户问题 | resolve | 路由路径 | 数据源 |
|---------|---------|---------|--------|
| "光模块产业现状" | P:800G光模块 | L2 → 如需全局视角 → L3 | L2/L3 摘要 |
| "中际旭创的客户有哪些" | C:300308 | L1 → 需要细节 → L0 | L1 摘要 + L0 子图 |
| "800G光模块产能对比" | P:800G光模块 | L2 → 跨 Company L1 对比 | L2 + 多 L1 |
| "中际旭创 vs 新易盛" | C:300308, C:300502 | 并行查 L1 → 对比 | 两个 L1 摘要 |
| "AI 算力有哪些投资机会" | P:800G光模块 | L2 → L3 → 关联 L2 主题 | L3 + 多 L2 |
| "中际旭创最新公告说了什么" | C:300308 | 直接 L0 + fetch_evidence | L0 子图 + 原文 |

---

## 4. 缓存与增量更新

### 4.1 缓存存储

**Redis**（热缓存）：
- Key: `summary:{level}:{entity_id}[:{extra_params}]`
- Value: JSON 摘要
- TTL: 7 天（未被访问则自动淘汰）
- 用于 Agent 查询时的快速读取

**PostgreSQL**（持久化注册表）：
```sql
CREATE TABLE summary_registry (
    summary_key   TEXT PRIMARY KEY,    -- "L1:C:300308"
    level         INTEGER NOT NULL,    -- 1/2/3
    entity_id     TEXT NOT NULL,       -- 锚定实体 ID
    version       INTEGER DEFAULT 1,
    generated_at  TIMESTAMPTZ,
    stale         BOOLEAN DEFAULT FALSE,
    entity_count  INTEGER,             -- 覆盖的实体数
    summary_text  TEXT,                -- 摘要全文
    embedding     vector(2560)         -- 向量（用于检索）
);
```

### 4.2 缓存失效机制

**失效触发**：
```
KG 抽取完成 → 新实体/关系写入 Neo4j
    │
    ▼
计算受影响的缓存 key:
  - 新 RELATES 边涉及 C:300308 → "L1:C:300308" 标记 stale
  - 新 RELATES 边涉及 P:ABCD1234 → "L2:P:ABCD1234" 标记 stale
  - L3 同理，按路径传播
```

**失效传播**：
```
L0 变更
  → L1:{company_id} stale        (该 Company 的 RELATES 边变了)
  → L2:{product_id} stale        (关联的任意 Company L1 变了)
  → L3:{product_id}:{depth} stale (路径上任意 Product L2 变了)
```

**实现方式**：
- 在 `kg_extractor.py` 的 `extract_text_async()` 末尾，记录受影响的 entity_id 列表
- 调用 `summary_cache.invalidate(entity_ids)` 标记 stale
- 不立即重新生成，等待下次查询时触发

### 4.3 增量更新流程

```
每天新增公告/IRM 数据
    │
    ▼
KG 抽取（已有流程）
    │
    ▼
summary_cache.invalidate(affected_entity_ids)
  → UPDATE summary_registry SET stale = TRUE
    WHERE summary_key IN (
      SELECT 'L1:' || eid FROM affected_entities WHERE type = 'Company'
      UNION
      SELECT 'L2:' || eid FROM affected_entities WHERE type = 'Product'
      UNION
      SELECT 'L3:' || peid || ':*' FROM affected_paths
    )
    │
    ▼
完成。无需离线批处理。
下次 Agent 查询命中 stale 缓存 → 自动重新生成。
```

---

## 5. 工具接口设计

### 5.1 summarize — 新增 Agent 工具

```python
@tool("summarize")
def summarize(
    entity_id: Annotated[str, "实体 ID（如 C:300308, P:ABCD1234）"],
    level: Annotated[int, "摘要层级：1=公司画像, 2=产品生态, 3=产业链视图"],
    depth: Annotated[int, "L3 遍历深度（默认 3）"] = 3,
) -> str:
    """
    获取实体的分层摘要。

    层级说明：
    - L1: 公司画像（聚合该公司所有 RELATES 边）
    - L2: 产品生态（聚合该产品关联的所有公司画像）
    - L3: 产业链视图（遍历 Product 上下游，组织为产业链）

    缓存优先：命中则直接返回，未命中则 LLM 生成并缓存。
    """
```

### 5.2 现有工具不变

- `resolve(entity_name)` — 实体锚定，不变
- `expand(entity_id, select, filter)` — 子图游走，不变
- `fetch_evidence(evidence_id)` — 原文追溯，不变

### 5.3 Agent 调用示例

```python
# 场景 1: 宏观行业分析
result = resolve("光模块")
# → P:ABCD1234 (800G光模块)
summary = summarize("P:ABCD1234", level=2)
# → L2 产品生态摘要
# 如果需要全局视角:
chain = summarize("P:ABCD1234", level=3, depth=3)
# → L3 产业链视图

# 场景 2: 公司深度分析
result = resolve("中际旭创")
# → C:300308
profile = summarize("C:300308", level=1)
# → L1 公司画像
# 需要细节客户关系:
details = expand("C:300308", select=["relations", "metrics"],
                 filter={"relation_subtypes": ["supplies_to"]})
# → L0 子图详细数据
```

---

## 6. 实现计划

### Phase 1: L1 公司画像（最小可行）

- [ ] 实现 `summarize` 工具框架（缓存检查 + LLM 生成 + 缓存写入）
- [ ] 实现 L1 聚合逻辑（取 Company 的 RELATES 边 + LLM Prompt）
- [ ] 实现 Redis 缓存 + PostgreSQL 注册表
- [ ] 实现缓存失效（`kg_extractor` 写入后标记 stale）

### Phase 2: L2 产品生态

- [ ] 实现 L2 聚合逻辑（取 Product 关联 Company → 查 L1 缓存 → LLM 合并）
- [ ] 实现级联失效（L1 stale → L2 stale）

### Phase 3: L3 产业链视图

- [ ] 实现 L3 遍历逻辑（Product 路径遍历 + 收集 L2 摘要）
- [ ] 实现 LLM 组织 Prompt（阅读 RELATES 描述判断上下游方向）
- [ ] 实现级联失效（L2 stale → L3 stale）

### Phase 4: Agent 路由优化

- [ ] 在 Agent system prompt 中增加分层路由策略说明
- [ ] 监控摘要缓存命中率、生成延迟、Token 消耗
- [ ] 根据查询日志识别高频查询，考虑预热机制

---

## 7. 成本估算

| 操作 | LLM Token 消耗 | 延迟 | 频率 |
|------|---------------|------|------|
| L1 生成 | ~800 input + 200 output | 2-3s | 首次查询某公司 |
| L2 生成 | ~2000 input + 400 output | 3-5s | 首次查询某产品 |
| L3 生成 | ~4000 input + 600 output | 5-8s | 首次查询某产业链 |
| 缓存命中 | 0 LLM | <10ms | 绝大多数查询 |
| 缓存失效标记 | 0 LLM | <1ms | 每次 KG 抽取后 |

**冷启动**：零成本。首次查询时按需生成。
**稳态运行**：缓存命中率预计 >80%，仅新实体/新产品的首次查询触发 LLM 生成。

---

## 8. 风险与缓解

| 风险 | 缓解 |
|------|------|
| 首次查询延迟高（冷缓存） | Agent 可先用 L0 快速回答，摘要后台异步生成 |
| L3 遍历路径爆炸 | depth 限制 ≤3，每跳取 Top-10 关系（按 weight 排序） |
| LLM 生成摘要质量不稳定 | Prompt 中明确要求"只基于给定数据，不要编造" |
| 缓存存储膨胀 | Redis TTL 7 天自动淘汰 + PostgreSQL 保留全量（可归档） |