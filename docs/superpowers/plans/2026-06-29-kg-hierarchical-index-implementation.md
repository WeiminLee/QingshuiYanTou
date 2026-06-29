# KG 分层索引体系 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build entity-anchored L1/L2/L3 summary layers on top of existing L0 knowledge graph, with on-demand LLM generation + Redis/PostgreSQL caching + automatic invalidation on new data.

**Architecture:** Three modules — `summary_cache.py` (Redis + PostgreSQL dual-layer cache), `summary_aggregator.py` (L1/L2/L3 aggregation logic with Neo4j queries), `summarize.py` (LangChain tool for Agent). Cache invalidation hooks into `kg_extractor.py` after KG extraction. Tool registered in `config.yaml` under knowledge group.

**Tech Stack:** LangChain BaseTool, Neo4j (async driver), Redis (aioredis), PostgreSQL (async SQLAlchemy), existing `chat_async()` LLM client

---

## File Structure

```
backend/app/knowledge/
├── summary_prompts.py      NEW — LLM prompt templates for L1/L2/L3
├── summary_cache.py        NEW — Redis + PostgreSQL cache layer
├── summary_aggregator.py   NEW — L1/L2/L3 aggregation logic (Neo4j queries)
├── kg_extractor.py         MODIFY — add cache invalidation hook after extraction

backend/app/reasoning/tools/knowledge/
├── summarize.py            NEW — LangChain tool for Agent
├── __init__.py             MODIFY — export summarize

backend/app/reasoning/registry/
├── config.yaml             MODIFY — register summarize tool

backend/migrations/
├── 001_add_summary_registry.sql  NEW — PostgreSQL migration
```

---

## Task 1: Database Migration — summary_registry Table

**Files:**
- Create: `backend/migrations/001_add_summary_registry.sql`

- [ ] **Step 1: Write the migration SQL**

```sql
-- 001_add_summary_registry.sql
-- 分层摘要持久化注册表

CREATE TABLE IF NOT EXISTS summary_registry (
    summary_key   TEXT PRIMARY KEY,       -- "L1:C:300308", "L2:P:ABCD1234", "L3:P:ABCD1234:3"
    level         INTEGER NOT NULL,       -- 1 / 2 / 3
    entity_id     TEXT NOT NULL,          -- 锚定实体 ID
    version       INTEGER DEFAULT 1,
    generated_at  TIMESTAMPTZ,
    stale         BOOLEAN DEFAULT FALSE,
    entity_count  INTEGER,               -- 覆盖的实体数
    summary_text  TEXT,                  -- 摘要全文
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    updated_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_summary_registry_level
    ON summary_registry(level);

CREATE INDEX IF NOT EXISTS idx_summary_registry_entity_id
    ON summary_registry(entity_id);

CREATE INDEX IF NOT EXISTS idx_summary_registry_stale
    ON summary_registry(stale)
    WHERE stale = TRUE;
```

- [ ] **Step 2: Run the migration**

```bash
cd backend && python -c "
from app.core.database import engine
from sqlalchemy import text
with open('migrations/001_add_summary_registry.sql') as f:
    sql = f.read()
import asyncio
async def run():
    async with engine.begin() as conn:
        for stmt in sql.split(';'):
            stmt = stmt.strip()
            if stmt:
                await conn.execute(text(stmt))
asyncio.run(run())
print('Migration complete')
"
```

Expected: `Migration complete`

- [ ] **Step 3: Commit**

```bash
git add backend/migrations/001_add_summary_registry.sql
git commit -m "feat: add summary_registry table for hierarchical summary caching"
```

---

## Task 2: Summary Prompts Module

**Files:**
- Create: `backend/app/knowledge/summary_prompts.py`

- [ ] **Step 1: Write the prompt module**

```python
"""
summary_prompts.py — LLM Prompt 模板 for 分层摘要生成

L1: 公司画像 — 聚合 Company 的所有 RELATES 边
L2: 产品生态 — 聚合 Product 关联的所有 Company 画像
L3: 产业链视图 — 遍历 Product 路径，LLM 组织为产业逻辑链
"""

from __future__ import annotations

L1_COMPANY_PROFILE_PROMPT = """你是一个投资研究助手。基于以下公司关联数据，生成该公司的结构化画像。

公司: {company_name}
关联数据:
{relations_text}

请按以下结构输出:
1. 主营产品: 该公司生产/提供的主要产品和服务
2. 技术路线: 该公司采用或研发的核心技术
3. 上下游: 主要客户和供应商关系
4. 关键指标: 重要的财务/经营指标（含数值和时间）
5. 发展状态: 当前所处阶段和关键信号

控制 200 字以内，只基于给定数据，不要编造。"""

L2_PRODUCT_ECOSYSTEM_PROMPT = """你是一个投资研究助手。基于以下产品生态数据，生成该产品领域的竞争格局摘要。

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

控制 400 字以内，只基于给定数据。"""

L3_INDUSTRY_CHAIN_PROMPT = """你是一个投资研究助手。基于以下产品生态数据，组织为产业链视图。

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

控制 600 字以内，只基于给定数据。"""
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/knowledge/summary_prompts.py
git commit -m "feat: add LLM prompt templates for L1/L2/L3 summary generation"
```

---

## Task 3: Summary Cache Layer

**Files:**
- Create: `backend/app/knowledge/summary_cache.py`

- [ ] **Step 1: Write the cache module**

```python
"""
summary_cache.py — Redis + PostgreSQL 双层缓存 for 分层摘要

Redis: 热缓存（TTL 7天），Agent 查询时快速读取
PostgreSQL: 持久化注册表，记录版本号、stale 状态、失效传播
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import redis.asyncio as aioredis

from app.config import settings
from app.core.database import async_session

logger = logging.getLogger(__name__)

# ── Redis 连接 ──────────────────────────────────────────────

_redis: aioredis.Redis | None = None

async def _get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(
            settings.redis_url or "redis://localhost:6379/0",
            decode_responses=True,
        )
    return _redis

# ── 缓存 key 规则 ───────────────────────────────────────────

def cache_key(level: int, entity_id: str, depth: int | None = None) -> str:
    """生成确定性缓存 key。

    L1: "summary:L1:C:300308"
    L2: "summary:L2:P:ABCD1234"
    L3: "summary:L3:P:ABCD1234:3"
    """
    base = f"summary:L{level}:{entity_id}"
    if level == 3 and depth is not None:
        return f"{base}:{depth}"
    return base

# ── 读取缓存 ────────────────────────────────────────────────

async def get_summary(level: int, entity_id: str, depth: int | None = None) -> dict | None:
    """从 Redis 读取摘要缓存。未命中返回 None。"""
    r = await _get_redis()
    key = cache_key(level, entity_id, depth)
    raw = await r.get(key)
    if raw:
        return json.loads(raw)
    return None

# ── 写入缓存 ────────────────────────────────────────────────

async def put_summary(
    level: int,
    entity_id: str,
    summary: str,
    *,
    entity_name: str = "",
    entity_count: int = 0,
    depth: int | None = None,
    extra: dict | None = None,
) -> None:
    """写入 Redis 热缓存 + PostgreSQL 注册表。"""
    key = cache_key(level, entity_id, depth)
    now = datetime.now(timezone.utc).isoformat()
    payload = {
        "key": key,
        "entity_id": entity_id,
        "entity_name": entity_name,
        "level": level,
        "summary": summary,
        "generated_at": now,
        "stale": False,
        "entity_count": entity_count,
    }
    if depth is not None:
        payload["depth"] = depth
    if extra:
        payload.update(extra)

    # 写 Redis（TTL 7天）
    r = await _get_redis()
    await r.set(key, json.dumps(payload, ensure_ascii=False), ex=7 * 86400)

    # 写 PostgreSQL（upsert）
    from sqlalchemy import text

    async with async_session() as session:
        await session.execute(
            text("""
                INSERT INTO summary_registry (summary_key, level, entity_id, version,
                    generated_at, stale, entity_count, summary_text, updated_at)
                VALUES (:key, :level, :entity_id, 1, :gen_at, FALSE, :cnt, :text, :now)
                ON CONFLICT (summary_key) DO UPDATE SET
                    version = summary_registry.version + 1,
                    generated_at = :gen_at,
                    stale = FALSE,
                    entity_count = :cnt,
                    summary_text = :text,
                    updated_at = :now
            """),
            {
                "key": key,
                "level": level,
                "entity_id": entity_id,
                "gen_at": now,
                "cnt": entity_count,
                "text": summary,
                "now": now,
            },
        )
        await session.commit()

# ── 缓存失效 ────────────────────────────────────────────────

async def invalidate_entity(entity_id: str) -> None:
    """标记单个实体的所有摘要缓存为 stale。

    从 kg_extractor 调用，在 KG 抽取完成后触发。
    传播规则：L1 stale → L2 stale → L3 stale
    """
    from sqlalchemy import text

    async with async_session() as session:
        # 标记 L1 缓存 stale
        await session.execute(
            text("""
                UPDATE summary_registry SET stale = TRUE, updated_at = NOW()
                WHERE summary_key = :l1_key
            """),
            {"l1_key": f"L1:{entity_id}"},
        )

        # 标记 L2 缓存 stale（如果该 entity 是 Product，或者关联的 Company 有 L1）
        await session.execute(
            text("""
                UPDATE summary_registry SET stale = TRUE, updated_at = NOW()
                WHERE summary_key = :l2_key
            """),
            {"l2_key": f"L2:{entity_id}"},
        )

        # 标记 L3 缓存 stale（所有 L3 缓存都检查是否包含该 entity）
        await session.execute(
            text("""
                UPDATE summary_registry SET stale = TRUE, updated_at = NOW()
                WHERE level = 3 AND summary_key LIKE :pattern
            """),
            {"pattern": f"%{entity_id}%"},
        )

        await session.commit()

    # 同时清除 Redis 缓存
    r = await _get_redis()
    await r.delete(f"summary:L1:{entity_id}")
    await r.delete(f"summary:L2:{entity_id}")
    # L3 可能包含该 entity 的所有 key 都清除
    keys = await r.keys(f"summary:L3:*{entity_id}*")
    if keys:
        await r.delete(*keys)

    logger.info("Summary cache invalidated for entity: %s", entity_id)


async def invalidate_entities(entity_ids: list[str]) -> None:
    """批量标记实体摘要缓存为 stale。"""
    for eid in entity_ids:
        await invalidate_entity(eid)


async def is_stale(level: int, entity_id: str, depth: int | None = None) -> bool:
    """检查摘要缓存是否过期。"""
    from sqlalchemy import text

    key = cache_key(level, entity_id, depth)
    async with async_session() as session:
        result = await session.execute(
            text("SELECT stale FROM summary_registry WHERE summary_key = :key"),
            {"key": key},
        )
        row = result.first()
        if row is None:
            return True  # 不存在视为过期，需要生成
        return bool(row[0])
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/knowledge/summary_cache.py
git commit -m "feat: add Redis + PostgreSQL dual-layer summary cache with invalidation"
```

---

## Task 4: Summary Aggregator — L1/L2/L3 Logic

**Files:**
- Create: `backend/app/knowledge/summary_aggregator.py`

- [ ] **Step 1: Write the L1 aggregation function**

```python
"""
summary_aggregator.py — L1/L2/L3 分层摘要聚合逻辑

每层锚定在明确的实体 ID 上，聚合规则是确定性的。
"""
from __future__ import annotations

import logging

from app.core.llm_client import chat_async
from app.core.neo4j_client import get_async_driver
from app.knowledge.summary_cache import get_summary, is_stale, put_summary
from app.knowledge.summary_prompts import (
    L1_COMPANY_PROFILE_PROMPT,
    L2_PRODUCT_ECOSYSTEM_PROMPT,
    L3_INDUSTRY_CHAIN_PROMPT,
)

logger = logging.getLogger(__name__)

# ── L1: 公司画像 ────────────────────────────────────────────


async def aggregate_l1(entity_id: str) -> str:
    """聚合 Company 的所有 RELATES 边，生成公司画像。

    Args:
        entity_id: Company entity_id，如 "C:300308"

    Returns:
        公司画像摘要文本
    """
    # 1. 检查缓存
    cached = await get_summary(1, entity_id)
    if cached and not await is_stale(1, entity_id):
        return cached["summary"]

    # 2. 查询 Neo4j
    driver = await get_async_driver()
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (c:Company {entity_id: $eid})-[r:RELATES]->(n)
            RETURN n.name AS name,
                   labels(n) AS labels,
                   r.text AS text,
                   r.weight AS weight,
                   r.stmt_type AS stmt_type
            ORDER BY r.weight DESC
            LIMIT 50
            """,
            eid=entity_id,
        )
        records = await result.data()

    if not records:
        return f"实体 {entity_id} 暂无关联数据。"

    # 获取公司名称
    company_name = entity_id
    for r in records:
        if "Company" in r.get("labels", []):
            company_name = r.get("name", entity_id)
            break

    # 3. 构建 relations_text
    lines = []
    for r in records:
        stmt = r.get("stmt_type", "Fact")
        weight = r.get("weight", 0)
        lines.append(
            f"- [{stmt}] {r['name']} ({', '.join(r.get('labels', []))}): "
            f"{r.get('text', '')} (权重:{weight:.1f})"
        )
    relations_text = "\n".join(lines)

    # 4. LLM 生成
    prompt = L1_COMPANY_PROFILE_PROMPT.format(
        company_name=company_name,
        relations_text=relations_text,
    )
    summary = await chat_async(prompt, temperature=0.1)

    # 5. 缓存
    await put_summary(
        level=1,
        entity_id=entity_id,
        summary=summary.strip(),
        entity_name=company_name,
        entity_count=len(records),
    )

    return summary.strip()
```

- [ ] **Step 2: Write the L2 aggregation function**

```python
# ── L2: 产品生态 ────────────────────────────────────────────


async def aggregate_l2(entity_id: str) -> str:
    """聚合 Product 关联的所有 Company 画像，生成产品生态摘要。

    Args:
        entity_id: Product entity_id，如 "P:ABCD1234"

    Returns:
        产品生态摘要文本
    """
    # 1. 检查缓存
    cached = await get_summary(2, entity_id)
    if cached and not await is_stale(2, entity_id):
        return cached["summary"]

    # 2. 查询 Neo4j — 获取关联的 Company
    driver = await get_async_driver()
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (p:Product {entity_id: $eid})<-[r:RELATES]-(c:Company)
            RETURN c.entity_id AS entity_id,
                   c.name AS name,
                   r.text AS text,
                   r.weight AS weight
            ORDER BY r.weight DESC
            LIMIT 30
            """,
            eid=entity_id,
        )
        records = await result.data()

        # 获取产品名称
        name_result = await session.run(
            "MATCH (p:Product {entity_id: $eid}) RETURN p.name AS name",
            eid=entity_id,
        )
        name_row = await name_result.single()
        product_name = name_row["name"] if name_row else entity_id

        # 获取产品间关系
        rel_result = await session.run(
            """
            MATCH (p:Product {entity_id: $eid})-[r:RELATES]-(other:Product)
            RETURN other.name AS name, r.text AS text, r.weight AS weight
            LIMIT 20
            """,
            eid=entity_id,
        )
        product_rels = await rel_result.data()

    if not records:
        return f"产品 {product_name} 暂无关联公司数据。"

    # 3. 获取各 Company 的 L1 摘要
    l1_summaries = []
    seen_companies = set()
    for r in records:
        cid = r["entity_id"]
        if cid in seen_companies:
            continue
        seen_companies.add(cid)
        try:
            l1_text = await aggregate_l1(cid)  # 递归获取 L1
        except Exception as e:
            logger.warning("L1 获取失败 [%s]: %s", cid, e)
            l1_text = f"{r['name']}: {r.get('text', '')}"
        l1_summaries.append(f"**{r['name']}** ({cid}): {l1_text}")

    # 4. 构建 product_relations
    rel_lines = []
    for pr in product_rels:
        rel_lines.append(f"- {product_name} ↔ {pr['name']}: {pr.get('text', '')} (权重:{pr.get('weight', 0):.1f})")

    # 5. LLM 生成
    prompt = L2_PRODUCT_ECOSYSTEM_PROMPT.format(
        product_name=product_name,
        l1_summaries="\n\n".join(l1_summaries),
        product_relations="\n".join(rel_lines) if rel_lines else "暂无",
    )
    summary = await chat_async(prompt, temperature=0.1)

    # 6. 缓存
    await put_summary(
        level=2,
        entity_id=entity_id,
        summary=summary.strip(),
        entity_name=product_name,
        entity_count=len(records),
    )

    return summary.strip()
```

- [ ] **Step 3: Write the L3 aggregation function**

```python
# ── L3: 产业链视图 ──────────────────────────────────────────


async def aggregate_l3(entity_id: str, depth: int = 3) -> str:
    """从锚定 Product 出发，遍历路径，收集 L2 摘要，LLM 组织为产业链。

    Args:
        entity_id: Product entity_id
        depth: 遍历深度（默认 3，最大 3）

    Returns:
        产业链视图摘要文本
    """
    depth = min(depth, 3)

    # 1. 检查缓存
    cached = await get_summary(3, entity_id, depth)
    if cached and not await is_stale(3, entity_id, depth):
        return cached["summary"]

    # 2. 遍历 Product 路径
    driver = await get_async_driver()
    async with driver.session() as session:
        # 获取 Product 名称
        name_result = await session.run(
            "MATCH (p:Product {entity_id: $eid}) RETURN p.name AS name",
            eid=entity_id,
        )
        name_row = await name_result.single()
        product_name = name_row["name"] if name_row else entity_id

        # 遍历路径，收集 distinct Product 节点
        path_result = await session.run(
            f"""
            MATCH path = (p:Product {{entity_id: $eid}})-[:RELATES*1..{depth}]-(other:Product)
            RETURN DISTINCT other.entity_id AS entity_id, other.name AS name
            LIMIT 30
            """,
            eid=entity_id,
        )
        path_products = await path_result.data()

        # 收集 Product 间关系描述
        rel_result = await session.run(
            f"""
            MATCH (p1:Product)-[r:RELATES]-(p2:Product)
            WHERE p1.entity_id = $eid OR p2.entity_id = $eid
            RETURN p1.name AS from_name, p2.name AS to_name, r.text AS text, r.weight AS weight
            LIMIT 30
            """,
            eid=entity_id,
        )
        product_rels = await rel_result.data()

    # 3. 收集各 Product 的 L2 摘要
    l2_summaries = []
    all_products = [{"entity_id": entity_id, "name": product_name}] + [
        {"entity_id": p["entity_id"], "name": p["name"]}
        for p in path_products
        if p["entity_id"] != entity_id
    ]

    seen = set()
    for p in all_products:
        pid = p["entity_id"]
        if pid in seen:
            continue
        seen.add(pid)
        try:
            l2_text = await aggregate_l2(pid)
        except Exception as e:
            logger.warning("L2 获取失败 [%s]: %s", pid, e)
            l2_text = f"{p['name']}: 暂无生态摘要"
        l2_summaries.append(f"**{p['name']}** ({pid}): {l2_text}")

    # 4. 构建关系描述
    rel_lines = []
    for pr in product_rels:
        rel_lines.append(
            f"- {pr.get('from_name', '')} ↔ {pr.get('to_name', '')}: "
            f"{pr.get('text', '')} (权重:{pr.get('weight', 0):.1f})"
        )

    # 5. LLM 生成
    prompt = L3_INDUSTRY_CHAIN_PROMPT.format(
        product_name=product_name,
        depth=depth,
        l2_summaries="\n\n".join(l2_summaries),
        relation_texts="\n".join(rel_lines) if rel_lines else "暂无",
    )
    summary = await chat_async(prompt, temperature=0.1)

    # 6. 缓存
    await put_summary(
        level=3,
        entity_id=entity_id,
        summary=summary.strip(),
        entity_name=product_name,
        entity_count=len(l2_summaries),
        depth=depth,
    )

    return summary.strip()
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/knowledge/summary_aggregator.py
git commit -m "feat: add L1/L2/L3 summary aggregation logic with entity-anchored rules"
```

---

## Task 5: Summarize Tool — LangChain Tool for Agent

**Files:**
- Create: `backend/app/reasoning/tools/knowledge/summarize.py`

- [ ] **Step 1: Write the summarize tool**

```python
"""
summarize — Agent 分层摘要工具

实体锚定 + 按需生成 + 缓存优先。
Agent 用此工具获取 L1/L2/L3 摘要，替代逐边遍历。
"""

from __future__ import annotations

import logging
from typing import Annotated

from langchain_core.tools import tool

from app.knowledge.summary_aggregator import aggregate_l1, aggregate_l2, aggregate_l3

logger = logging.getLogger(__name__)


@tool("summarize")
def summarize(
    entity_id: Annotated[
        str,
        "实体 ID（如 C:300308, P:ABCD1234）。必须先用 resolve 获取 entity_id。",
    ],
    level: Annotated[
        int,
        "摘要层级：1=公司画像（聚合该公司所有 RELATES 边），"
        "2=产品生态（聚合该产品关联的所有公司画像），"
        "3=产业链视图（遍历 Product 上下游，组织为产业链）",
    ],
    depth: Annotated[
        int,
        "L3 遍历深度（默认 3，最大 3）。仅 level=3 时需要。",
    ] = 3,
) -> str:
    """获取知识图谱实体的分层摘要。

    使用场景：
    - 宏观问题（"光模块行业现状"）→ level=2 查产品生态，需要全局视角时 level=3
    - 中观问题（"800G光模块竞争格局"）→ level=2 查产品生态
    - 微观问题（"中际旭创的客户"）→ level=1 查公司画像，需要细节时用 expand

    缓存优先：命中则直接返回，未命中则 LLM 生成并缓存。
    """
    import asyncio

    if level not in (1, 2, 3):
        return f"无效的层级: {level}。有效值: 1（公司画像）, 2（产品生态）, 3（产业链视图）"

    if not entity_id:
        return "请先用 resolve 工具获取实体 ID。"

    try:
        async def _run():
            if level == 1:
                return await aggregate_l1(entity_id)
            elif level == 2:
                return await aggregate_l2(entity_id)
            else:
                return await aggregate_l3(entity_id, depth=min(depth, 3))

        return asyncio.run(_run())
    except Exception as e:
        logger.error("summarize 失败 [%s L%d]: %s", entity_id, level, e, exc_info=True)
        return f"摘要生成失败: {e}"
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/reasoning/tools/knowledge/summarize.py
git commit -m "feat: add summarize tool for Agent hierarchical summary retrieval"
```

---

## Task 6: Register Summarize Tool

**Files:**
- Modify: `backend/app/reasoning/tools/knowledge/__init__.py`
- Modify: `backend/app/reasoning/registry/config.yaml`

- [ ] **Step 1: Export summarize from knowledge tools**

Edit `backend/app/reasoning/tools/knowledge/__init__.py`:

```python
from app.reasoning.tools.knowledge.evidence import fetch_evidence
from app.reasoning.tools.knowledge.graph_navigator import expand, resolve
from app.reasoning.tools.knowledge.semantic_search import semantic_search
from app.reasoning.tools.knowledge.summarize import summarize

__all__ = ["fetch_evidence", "resolve", "expand", "semantic_search", "summarize"]
```

- [ ] **Step 2: Register in config.yaml**

Add after the `expand` tool entry in `backend/app/reasoning/registry/config.yaml`:

```yaml
  - name: summarize
    group: knowledge
    use: app.reasoning.tools.knowledge:summarize
    description: 获取知识图谱实体的分层摘要（L1=公司画像, L2=产品生态, L3=产业链视图）。缓存优先，按需生成。宏观问题用L2/L3，微观问题用L1。
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/reasoning/tools/knowledge/__init__.py backend/app/reasoning/registry/config.yaml
git commit -m "feat: register summarize tool in knowledge group and config.yaml"
```

---

## Task 7: Cache Invalidation Hook in kg_extractor

**Files:**
- Modify: `backend/app/knowledge/kg_extractor.py`

- [ ] **Step 1: Add invalidation hook after extraction**

In `extract_text_async()`, after the entity and relation writes are complete, add the invalidation call. Insert after the line where `company_signals` is computed (around line 1155):

```python
# ── 摘要缓存失效（新增）────────────────────────────────────
# 收集本次抽取涉及的实体，标记对应摘要缓存为 stale
try:
    from app.knowledge.summary_cache import invalidate_entities

    affected_entity_ids = list(entity_ids)  # 已写入的实体
    # 关系两端实体也加入
    for rel in written_rels:
        from_eid = rel.get("from", "")
        to_eid = rel.get("to", "")
        if from_eid and from_eid not in affected_entity_ids:
            affected_entity_ids.append(from_eid)
        if to_eid and to_eid not in affected_entity_ids:
            affected_entity_ids.append(to_eid)

    if affected_entity_ids:
        await invalidate_entities(affected_entity_ids)
        logger.info(
            "摘要缓存失效标记完成: %d 个实体",
            len(affected_entity_ids),
        )
except Exception as inv_ex:
    logger.warning("摘要缓存失效标记失败: %s", inv_ex)
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/knowledge/kg_extractor.py
git commit -m "feat: add summary cache invalidation hook after KG extraction"
```

---

## Task 8: Agent Routing Prompt Update

**Files:**
- Modify: `backend/app/reasoning/langchain_agent/prompts/lead_system_prompt.py`

- [ ] **Step 1: Add summarize routing guide to agent system prompt**

Add the following section to the system prompt (locate the tools section and append):

```python
# ── 分层摘要路由策略 ──────────────────────────────────────────
SUMMARIZE_ROUTING_GUIDE = """
## 分层摘要路由策略

使用 `summarize` 工具获取实体的预聚合摘要，减少逐边遍历：

**路由规则：**
- 宏观问题（"产业链"、"行业格局"、"赛道分析"）→ 先用 resolve 锚定 Product → summarize(level=2) → 需要全局视角时 summarize(level=3)
- 中观问题（"产品竞争格局"、"技术路线对比"）→ resolve → summarize(level=2)
- 微观问题（"公司客户"、"供应商"、"业绩"）→ resolve → summarize(level=1) → 需要细节时 expand(L0)

**原则：先查摘要，再决定是否深入。摘要可以直接回答概括性问题，节省 token。**
"""
```

Insert `SUMMARIZE_ROUTING_GUIDE` into the main system prompt template where tools are described.

- [ ] **Step 2: Commit**

```bash
git add backend/app/reasoning/langchain_agent/prompts/lead_system_prompt.py
git commit -m "feat: add summarize routing guide to agent system prompt"
```

---

## Task 9: Integration Test

**Files:**
- Create: `backend/tests/knowledge/test_summary_cache.py`

- [ ] **Step 1: Write integration test for summary cache**

```python
"""
test_summary_cache.py — 分层摘要缓存集成测试
"""

import pytest


class TestSummaryCache:
    """摘要缓存读写 + 失效传播测试"""

    @pytest.mark.asyncio
    async def test_cache_key_deterministic(self):
        """验证缓存 key 生成是确定性的"""
        from app.knowledge.summary_cache import cache_key

        assert cache_key(1, "C:300308") == "summary:L1:C:300308"
        assert cache_key(2, "P:ABCD1234") == "summary:L2:P:ABCD1234"
        assert cache_key(3, "P:ABCD1234", depth=3) == "summary:L3:P:ABCD1234:3"

    @pytest.mark.asyncio
    async def test_put_and_get_summary(self):
        """验证缓存写入和读取"""
        from app.knowledge.summary_cache import get_summary, put_summary

        await put_summary(
            level=1,
            entity_id="C:TEST001",
            summary="测试公司画像摘要",
            entity_name="测试公司",
            entity_count=10,
        )

        cached = await get_summary(1, "C:TEST001")
        assert cached is not None
        assert cached["summary"] == "测试公司画像摘要"
        assert cached["entity_name"] == "测试公司"
        assert cached["level"] == 1
        assert cached["stale"] is False

    @pytest.mark.asyncio
    async def test_invalidation_propagation(self):
        """验证缓存失效传播"""
        from app.knowledge.summary_cache import (
            invalidate_entity,
            is_stale,
            put_summary,
        )

        # 写入 L1/L2/L3 缓存
        await put_summary(level=1, entity_id="C:TEST002", summary="L1", entity_name="T")
        await put_summary(level=2, entity_id="P:TEST002", summary="L2", entity_name="T")
        await put_summary(level=3, entity_id="P:TEST002", summary="L3", entity_name="T", depth=3)

        # 失效
        await invalidate_entity("C:TEST002")

        # L1 应 stale
        assert await is_stale(1, "C:TEST002")

        # L2 应 stale（关联的 entity 失效）
        assert await is_stale(2, "P:TEST002")

    @pytest.mark.asyncio
    async def test_get_summary_miss(self):
        """验证缓存未命中返回 None"""
        from app.knowledge.summary_cache import get_summary

        result = await get_summary(1, "C:NONEXISTENT")
        assert result is None
```

- [ ] **Step 2: Run the test**

```bash
cd backend && python -m pytest tests/knowledge/test_summary_cache.py -v
```

Expected: 4 tests PASS

- [ ] **Step 3: Commit**

```bash
git add backend/tests/knowledge/test_summary_cache.py
git commit -m "test: add integration tests for summary cache layer"
```

---

## Task 10: End-to-End Verification

- [ ] **Step 1: Verify tool registration**

```bash
cd backend && python -c "
from app.reasoning.tools.tools import get_available_tools
tools = get_available_tools(groups=['knowledge'])
names = [t.name for t in tools]
print('Knowledge tools:', names)
assert 'summarize' in names, 'summarize tool not registered!'
print('SUCCESS: summarize tool registered')
"
```

Expected: `SUCCESS: summarize tool registered`

- [ ] **Step 2: Verify L1 aggregation with real data**

```bash
cd backend && python -c "
import asyncio
from app.knowledge.summary_aggregator import aggregate_l1

async def test():
    # 使用一个真实存在的 Company entity_id
    result = await aggregate_l1('C:300308.SZ')
    print('L1 Summary:', result[:200])
    assert len(result) > 20, 'Summary too short'

asyncio.run(test())
print('SUCCESS: L1 aggregation works')
"
```

Expected: L1 summary text for 中际旭创 (or the company matching the entity_id)

- [ ] **Step 3: Commit**

```bash
git commit -m "verify: end-to-end tool registration and L1 aggregation"
```