# 事件层设计 — 开放域事件接入与 Agent 推理

> 日期：2026-06-25
> 范围：事件数据接入、存储、Agent 工具、推理期事件→个股映射
> 状态：设计稿

---

## 1. 背景与动机

当前知识图谱（V1.3 Schema）仅支持 Company → Product → Metric 三类实体，所有数据建模围绕个股展开。系统缺少对**开放域事件**的建模能力——一个新闻或事件可能影响整个板块甚至整个市场，但系统没有地方存放它，Agent 也没有办法查询它。

### 核心缺口

| 维度 | 当前状态 | 目标 |
|------|---------|------|
| 事件存储 | 无 | PostgreSQL events 表 |
| 事件搜索 | 无 | Agent 可搜索财联社事件库 |
| 事件→个股映射 | 无 (LLM 在推理时自行判断) | 不预建映射表 |
| 事件因子信号 | 无 (Agent 在推理时自行产出) | 不预建因子引擎 |

### 设计原则

1. **事件独立于知识图谱** — 不进 Neo4j，不增加 KG Schema 复杂度
2. **映射实时化** — 事件→个股关联由 Agent 在推理时自主决策，不预建
3. **极简 Phase 1** — 不引入 Qdrant、情感分类、事件类型分类等额外 infra
4. **渐进增强** — Phase 1 跑通后，按需加向量搜索 / 因子引擎

---

## 2. 架构概览

```
Tushare 财联社 API
    │  (定时同步, scheduler)
    ▼
┌──────────────────────────┐
│  NewsService             │  data_pipeline/services/news_service.py
│  fetch_cls_news()        │
│  dedup by title hash     │
│  upsert into events 表   │
└───────────┬──────────────┘
            ▼
┌──────────────────────────┐
│  PostgreSQL events 表     │  结构化事件数据
│  ┌────────────────────┐  │
│  │ event_id (PK)      │  │
│  │ title + summary    │  │
│  │ content            │  │
│  │ source="cls"       │  │
│  │ publish_at         │  │
│  │ metadata (JSONB)   │  │
│  └────────────────────┘  │
└───────────┬──────────────┘
            ▼
┌──────────────────────────┐
│  Agent 工具              │  reasoning/tools/market_data/events/
│  ├ find_events()         │  PG 全文搜索 → 格式化返回
│  └ get_event_detail()    │  获取事件原始全文
└───────────┬──────────────┘
            ▼
      Agent 推理期自行决策
      (事件→个股映射 + 影响评分)
```

### 组件一览

| 组件 | 位置 | 职责 |
|------|------|------|
| `NewsService` | `data_pipeline/services/news_service.py` | Tushare 财联社新闻拉取 + 去重 |
| `events` 表 | PostgreSQL | 事件结构化存储 |
| `find_events` | `reasoning/tools/market_data/events/` | Agent 事件搜索工具 |
| `get_event_detail` | 同上 | Agent 获取事件详情工具 |

### 不包含的内容

- Qdrant 向量搜索（Phase 2）
- 事件类型/情感预分类（Agent 自行判断）
- 事件→个股映射表（Agent 实时推理）
- 事件因子引擎（Agent 实时产出）
- Neo4j Event 节点（事件不进图）
- 概念板块升格为图节点（维持现状）

---

## 3. 数据模型

```sql
CREATE TABLE events (
    id          BIGSERIAL PRIMARY KEY,
    event_id    VARCHAR(32) UNIQUE NOT NULL,    -- EV:{sha256(title)[:16]}
    title       TEXT NOT NULL,
    summary     TEXT,                           -- tushare 自带的摘要
    content     TEXT,                           -- 全文（如有）
    source      VARCHAR(32) NOT NULL DEFAULT 'cls',
    url         TEXT,
    publish_at  TIMESTAMPTZ NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    metadata    JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX idx_events_publish_at ON events (publish_at DESC);
CREATE INDEX idx_events_source ON events (source);
```

### 字段说明

| 字段 | 说明 |
|------|------|
| `event_id` | 稳定 ID，由 title 前 16 个字符的 SHA256 截断生成。同一标题的事件只存一条 |
| `title` | 新闻标题。Agent 搜索的主要目标 |
| `summary` | tushare API 返回的摘要（如有）。为完整搜索内容也加入 tsvector 索引 |
| `content` | 全文（如 tushare 不提供则为空）。Agent 阅读事件时通过 get_event_detail 获取 |
| `source` | 数据源标识，固定为 `cls`（财联社）。预留扩展其他源 |
| `metadata` | 保留 tushare 返回的原始字段，不做结构化映射 |

---

## 4. 数据同步 Pipeline

### 4.1 Tushare 财联社接口

tushare 提供 `news` / `major_news` 接口获取财联社快讯。

> **实现备注**：需确认 tushare pro 的具体接口名和返回字段（`pro.news()` vs `pro.major_news()` vs `pro.cls()`），以及是否需要额外权限。接入前验证一次。

| 参数 | 值 |
|------|-----|
| API | `pro.news()` / `pro.major_news()` |
| 来源 | 财联社 (CLS) |
| 内容 | 标题 + 摘要 + 发布时间 + 来源 |

### 4.2 同步策略

```
Scheduler 每 N 分钟触发
    → NewsService.fetch_cls_news()
    → 遍历返回的新闻列表
    → 对每条：计算 event_id → 检查是否存在 → 不存在则 INSERT
    → 记录同步进度（最近一条的 publish_at，下次作为起点）
```

### 4.3 自动标签（Phase 1.5）

入库时对标题做一次轻量关键词匹配，标记事件涉及的板块/概念：

```
标题: "华为AI芯片突破，昇腾910B性能提升300%"

ths_concepts.name 匹配:
  ↓  "华为概念"  ✓
  ↓  "芯片概念"  ✓
  ↓  "AI概念"    ✓
  ↓  "昇腾概念"  ✓ (如有)
  
→ metadata.tags = ["华为概念", "芯片概念", "AI概念", "昇腾概念"]
```

实现方式：
```python
def auto_tag(title: str, concept_names: list[str]) -> list[str]:
    """从标题中匹配已知概念/板块名称，返回匹配到的标签列表。"""
    tags = []
    for name in concept_names:
        if name in title:  # "华为概念" in "华为AI芯片突破"
            tags.append(name)
    return tags
```

> **不依赖 LLM，不走 embedding**，纯字符串 `in` 匹配。概念列表从 `ths_concepts` 表定时加载。匹配命中率取决于标题长度和概念名称的特异性，财联社标题通常足够简洁，命中率尚可。

### 4.5 去重规则

| 场景 | 处理 |
|------|------|
| 同一标题的新闻 | `event_id` 唯一约束，`ON CONFLICT DO NOTHING` |
| Tushare 重复推送 | 检查 `publish_at` + `title` 组合，全量表扫描？ |
| 实际做法 | `event_id = EV:{sha256(title[:16])}`，天然去重 |

### 4.6 同步频率

默认每 5 分钟一次（可配置），每次获取最近 1 小时的新闻。第一次全量拉取历史 N 天（配置项）。

---

## 5. Agent 工具

### 5.1 `find_events`

```python
@tool("find_events")
def find_events(
    query: str | None = None,
    tags: list[str] | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    top_n: int = 10,
) -> str:
    """搜索财联社事件库。按关键词或板块标签查找相关事件，支持按时间范围过滤。
    适合用来查询最近影响某个行业、板块或个股的新闻事件。

    Args:
        query: 搜索关键词，越精确越好（如 "AI芯片 制裁 中际旭创"）。query 和 tags 可选至少传一个
        tags: 板块/概念标签过滤（如 ["芯片概念", "华为概念"]）。事件入库时会自动打标签，可用来精确筛选
        date_from: 开始日期 YYYYMMDD，不传则不限制
        date_to: 结束日期 YYYYMMDD，不传则到今天
        top_n: 返回条数，默认 10，最多 30
    """
```

**搜索实现**（Phase 1.5）：

执行策略：如果传了 `tags`，优先用 tags 索引过滤缩小范围（O(1) 索引查找），再在结果集上做 ILIKE 关键词搜索。

```sql
SELECT event_id, title, summary, source, publish_at
FROM events
WHERE (
    ($tags IS NULL)
    OR metadata @> '{"tags": $tag1}'   -- jsonb 索引扫描
    OR metadata @> '{"tags": $tag2}'
    -- (每个 tag 对应一个 @> 条件)
)
  AND (
    ($query IS NULL)
    OR (title ILIKE '%' || $keyword1 || '%'
        AND title ILIKE '%' || $keyword2 || '%')
    -- (Agent 输入的每个词对应一个 ILIKE 条件)
  )
  AND publish_at BETWEEN $date_from AND $date_to  -- 可选
ORDER BY publish_at DESC
LIMIT top_n;
```

> **为什么不用 tsvector**：中文在 PG `simple` 配置下不会被正确分词，`zhparser` 等扩展需要额外安装。Phase 1 的 tags 索引 + ILIKE 策略利用 GIN jsonb 索引做精确过滤，数据量 < 10 万行时性能可接受。Phase 2 切向量搜索时一并解决语义召回问题。

**返回格式**：
```
## 事件搜索结果（关键词：AI芯片 制裁）

**1.** 美国升级AI芯片出口管制，英伟达H20对华出口受限
   📅 2026-06-25 08:30  |  来源：财联社
   摘要：美国商务部宣布进一步收紧对华AI芯片出口限制...

**2.** 中际旭创：AI芯片制裁对公司800G光模块需求影响有限
   📅 2026-06-24 15:20  |  来源：财联社
   摘要：中际旭创在投资者互动平台表示...
```

### 5.2 `get_event_detail`

```python
@tool("get_event_detail")
def get_event_detail(event_id: str) -> str:
    """获取事件的原始全文内容。在 find_events 找到感兴趣的事件后调用。

    Args:
        event_id: 事件 ID（EV: 开头）
    """
```

**返回格式**：
```
## 事件详情
ID: EV:a1b2c3d4e5f6
标题: 美国升级AI芯片出口管制，英伟达H20对华出口受限
时间: 2026-06-25 08:30
来源: 财联社

【全文内容】
...
```

> **注意**：`get_stock_concepts` 和 `get_concept_stocks` 目前仅有 FastAPI 接口（`knowledge/api/concept.py`），尚未封装为 LangChain Agent 工具。Phase 1 需要新增这两个工具，或在实现层将 find_events 直接嵌入 concept 查询逻辑。具体见实现计划。

### 5.3 可复用的现有工具

Agent 在推理时自主组合以完成事件→个股映射：

| 工具 | 已有 | 用途 |
|------|------|------|
| `get_concept_hot` | ✅ | 查看当前热点概念板块 |
| `get_stock_concepts` | API 层有，需封装为 Agent 工具 | 查个股属于哪些概念 |
| `get_concept_stocks` | API 层有，需封装为 Agent 工具 | 查概念包含哪些成分股 |
| `resolve` (图谱) | ✅ | 锚定个股/行业实体 |
| `expand` (图谱) | ✅ | 展开个股产业链关系 |

### 5.4 Agent 典型推理路径

```
用户: "芯片制裁对中际旭创有什么影响？"

Agent 推理链:
1. find_events("AI芯片 出口管制 制裁") → 返回一批事件
2. 阅读事件详情 → 判断事件内容和性质
3. get_stock_concepts("300308.SZ") → 发现属于"光通信""5G""CPO"概念
4. 推理判断: "AI芯片制裁→限制H20出口→可能影响CSP资本开支→光模块需求端受影响→但中际旭创客户覆盖北美CSP→影响程度中等"
5. 回答: 给出判断 + 引用事件原文作为证据
```

---

## 6. 文件清单

### 新增

| 文件 | 内容 |
|------|------|
| `backend/app/data_pipeline/services/news_service.py` | Tushare 财联社新闻抓取 + 去重 + 入库 |
| `backend/app/reasoning/tools/market_data/events/__init__.py` | `find_events` + `get_event_detail` 工具 |
| `backend/app/reasoning/tools/market_data/events/events.py` | 工具实现 |
| `backend/app/models/event.py` | SQLAlchemy Event 模型（或加在 models.py 中） |

### 修改

| 文件 | 修改内容 |
|------|---------|
| `backend/app/data_pipeline/scheduler.py` | 注册 news 定时同步任务 |
| `backend/app/reasoning/registry/loader.py` | 注册 `find_events` 和 `get_event_detail` 工具 |
| `backend/app/reasoning/langchain_agent/prompts/lead_system_prompt.py` | 在相关策略中加入事件搜索提示 |

### 数据库迁移

```sql
-- 新建 events 表
CREATE TABLE events (
    id          BIGSERIAL PRIMARY KEY,
    event_id    VARCHAR(32) UNIQUE NOT NULL,
    title       TEXT NOT NULL,
    summary     TEXT,
    content     TEXT,
    source      VARCHAR(32) NOT NULL DEFAULT 'cls',
    url         TEXT,
    publish_at  TIMESTAMPTZ NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    metadata    JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX idx_events_publish_at ON events (publish_at DESC);
CREATE INDEX idx_events_source ON events (source);
CREATE INDEX idx_events_tags ON events USING gin (metadata jsonb_path_ops);
```

---

## 7. Phase 2 候选

以下内容不在 Phase 1 范围内，仅记录供后续参考：

| 功能 | 触发条件 | 方案 |
|------|---------|------|
| Qdrant 向量搜索 | Agent 语义召回不足时 | 新增 Qdrant `events` collection，title+summary BERT embedding |
| 情感/类型预分类 | Agent 需要按情感过滤且 PG 搜索不足时 | LLM 或 BERT 分类，结果存 metadata 字段 |
| 因子信号 | 需要评分系统自动叠加事件影响时 | 事件情绪 × 时间衰减 → 叠加到 ConceptScore |
| 事件→个股映射表 | Agent 推理结果不稳定需要缓存时 | PostgreSQL `event_stock_impact` 表，LLM 标注 + 人工审核 |
| Neo4j Event 节点 | Agent 需要图遍历"事件→概念→个股"时 | 薄 Event 节点 + AFFECTS 边 |

---

## 8. 测试策略

| 测试类型 | 覆盖内容 |
|---------|---------|
| 单元测试 | `NewsService.dedup()`, `event_id` 生成稳定性 |
| 集成测试 | Tushare mock → events 表写入 → `find_events` 查询 |
| Agent 测试 | 模拟 Agent 调用 `find_events` + `get_event_detail` 的流程 |
| 端到端测试 | 真实调度 → 入库 → Agent 查询 → 推理映射 |
