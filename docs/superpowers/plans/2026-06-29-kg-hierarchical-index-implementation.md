# KG 分层索引体系 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**References:**
- Spec: `docs/superpowers/specs/2026-06-29-kg-hierarchical-index-design.md`
- Code analysis: `docs/代码分析报告-2026-06-25.md` (P1-#6 async anti-pattern, P1-#10 kg_extractor size)
- Existing tools: `backend/app/reasoning/tools/knowledge/graph_navigator.py` (resolve + expand)

**Goal:** Build entity-anchored L1/L2/L3 summary layers on top of existing L0 knowledge graph, with on-demand LLM generation + Redis/PostgreSQL caching + automatic invalidation on new data.

**Architecture:** Three modules — `summary_cache.py` (Redis + PostgreSQL dual-layer cache), `summary_aggregator.py` (L1/L2/L3 aggregation logic with Neo4j queries), `summarize.py` (LangChain tool for Agent). Cache invalidation hooks into `kg_extractor.py` after KG extraction. Tool registered in `config.yaml` under knowledge group.

**Tech Stack:** LangChain BaseTool / StructuredTool, Neo4j (async driver), Redis (aioredis), PostgreSQL (async SQLAlchemy), existing `chat_async()` LLM client

## Global Constraints

- All new Agent tools must inherit from `StructuredTool` and implement `_arun` (async) + `_run` (sync fallback); prohibit `@tool` + `asyncio.run()` pattern (see code analysis report P1-#6)
- All async Neo4j queries must use `get_async_driver()` from `app.core.neo4j_client`
- All LLM calls must use `chat_async()` from `app.core.llm_client`
- Redis key format: `summary:L{level}:{entity_id}[:{depth}]`; PG key format: `L{level}:{entity_id}[:{depth}]`
- Cache invalidation must cascade: L0 change → L1 stale → (Neo4j lookup for related Products) → L2 stale → L3 stale
- All summary prompts require `"只基于给定数据，不要编造"` guardrail in the system message
- Commit message convention: `feat:` for new features, `test:` for tests, `verify:` for verification commits

---

## File Structure

```
backend/app/knowledge/
├── summary_prompts.py        NEW — LLM prompt templates for L1/L2/L3
├── summary_cache.py          NEW — Redis + PostgreSQL cache layer
├── summary_aggregator.py     NEW — L1/L2/L3 aggregation logic (Neo4j queries)
├── summary_invalidator.py    NEW — independent invalidation trigger (avoids kg_extractor bloat)
├── kg_extractor.py           MODIFY — add 1-line call to summary_invalidator.trigger_invalidation()

backend/app/reasoning/tools/knowledge/
├── summarize.py              NEW — LangChain StructuredTool for Agent (async _arun + sync _run)
├── __init__.py               MODIFY — export summarize

backend/app/reasoning/registry/
├── config.yaml               MODIFY — register summarize tool

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

控制 400 字以内，只基于给定数据，不要编造。"""

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

控制 600 字以内，只基于给定数据，不要编造。"""
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
    # PG 中存储的 summary_key 不含 "summary:" 前缀（与 Redis key 区分）
    pg_key = key.removeprefix("summary:")
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
                "key": pg_key,
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

async def _find_related_products(entity_id: str) -> list[str]:
    """查询 Neo4j，找出与 Company 关联的 Product entity_id。

    Company 变更需要级联失效关联的 L2/L3 产品摘要。
    不从 Neo4j 查询则无法确定哪些 L2 key 需要标记 stale。
    """
    from app.core.neo4j_client import get_async_driver

    try:
        driver = await get_async_driver()
        async with driver.session() as session:
            result = await session.run(
                """
                MATCH (c:Company {entity_id: $eid})-[r:RELATES]->(p:Product)
                RETURN DISTINCT p.entity_id AS product_id
                """,
                eid=entity_id,
            )
            rows = await result.data()
            return [r["product_id"] for r in rows if r.get("product_id")]
    except Exception as e:
        logger.warning("查询关联 Product 失败 [%s]: %s", entity_id, e, exc_info=True)
        return []


async def _mark_stale_in_pg(summary_keys: list[str]) -> None:
    """在 PostgreSQL 中标记一批缓存为 stale。"""
    if not summary_keys:
        return
    from sqlalchemy import text

    async with async_session() as session:
        await session.execute(
            text("""
                UPDATE summary_registry SET stale = TRUE, updated_at = NOW()
                WHERE summary_key = ANY(:keys)
            """),
            {"keys": summary_keys},
        )
        await session.commit()


async def _delete_from_redis(summary_keys: list[str]) -> None:
    """从 Redis 删除一批缓存 key。"""
    if not summary_keys:
        return
    r = await _get_redis()
    # 在 Redis 中 key 格式是 "summary:L1:C:300308" vs PG 中 "L1:C:300308"
    redis_keys = [f"summary:{k}" if not k.startswith("summary:") else k for k in summary_keys]
    await r.delete(*redis_keys)


async def invalidate_entity(entity_id: str) -> None:
    """标记单个实体的所有摘要缓存为 stale。

    从 kg_extractor 调用，在 KG 抽取完成后触发。
    传播规则：
      Company 变更 → L1:{company} stale → 查关联 Product → L2/L3:{product} stale
      Product 变更 → L2:{product} stale → L3:{product}:* stale
    """
    stale_keys: list[str] = []

    # 1. L1 — 公司画像
    stale_keys.append(f"L1:{entity_id}")

    # 2. 判断 entity 类型：如果以 "C:" 开头，是 Company，需查关联 Product
    if entity_id.startswith("C:"):
        product_ids = await _find_related_products(entity_id)
        for pid in product_ids:
            stale_keys.append(f"L2:{pid}")
            # 使用 LIKE 匹配该 Product 的所有 L3 depth 变体
            stale_keys.append(f"L3:{pid}:%")
    else:
        # Product → L2 直接失效
        stale_keys.append(f"L2:{entity_id}")
        # 使用 LIKE 匹配该 Product 的所有 L3 depth 变体
        stale_keys.append(f"L3:{entity_id}:%")

    # 3. PG 标记 stale（L3 含 % 通配符，用 LIKE 而非精确匹配）
    exact_keys = [k for k in stale_keys if not k.endswith("%")]
    pattern_keys = [k for k in stale_keys if k.endswith("%")]

    if exact_keys:
        await _mark_stale_in_pg(exact_keys)

    for pattern in pattern_keys:
        from sqlalchemy import text

        async with async_session() as session:
            await session.execute(
                text("""
                    UPDATE summary_registry SET stale = TRUE, updated_at = NOW()
                    WHERE summary_key LIKE :pattern
                """),
                {"pattern": pattern},
            )
            await session.commit()

    # 4. Redis 清理
    #    Redis 中存储精确 key，不含通配符；L3 需要反查所有匹配的 key
    redis_exact = [k for k in stale_keys if not k.endswith("%")]
    await _delete_from_redis(redis_exact)

    #    Redis L3 匹配 — 用 scan_iter 避免阻塞
    redis_patterns = [k for k in stale_keys if k.endswith("%")]
    if redis_patterns:
        r = await _get_redis()
        for pattern in redis_patterns:
            redis_glob = f"summary:{pattern.replace('%', '*')}"
            async for key in r.scan_iter(match=redis_glob):
                await r.delete(key)

    logger.info(
        "Summary cache invalidated for entity: %s (%d exact + %d pattern keys)",
        entity_id,
        len(exact_keys),
        len(pattern_keys),
    )


async def invalidate_entities(entity_ids: list[str]) -> None:
    """批量标记实体摘要缓存为 stale。

    使用 asyncio.gather 并发执行，每个 invalidation 独立。
    """
    if not entity_ids:
        return
    # 去重
    import asyncio

    unique_ids = list(dict.fromkeys(entity_ids))
    await asyncio.gather(*[invalidate_entity(eid) for eid in unique_ids])


async def is_stale(level: int, entity_id: str, depth: int | None = None) -> bool:
    """检查摘要缓存是否过期。

    PG summary_key 不包含 "summary:" 前缀，需 strip 后查询。
    """
    from sqlalchemy import text

    pg_key = cache_key(level, entity_id, depth).removeprefix("summary:")
    async with async_session() as session:
        result = await session.execute(
            text("SELECT stale FROM summary_registry WHERE summary_key = :key"),
            {"key": pg_key},
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
            ORDER BY r.weight DESC
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
# ── L3: 产业链视图（逐跳剪枝版）──────────────────────────────

_TOPK_PER_HOP = 10  # 每跳最多保留的关系数（按 weight 排序）


async def _l3_expand_hop(
    session: Any,
    entity_ids: list[str],
    current_depth: int,
    max_depth: int,
    visited: set[str],
    rel_lines: list[str],
) -> list[dict]:
    """执行单跳展开，按 weight 取 Top-K。

    递归剪枝策略：每跳只保留 weight 最高的 TOPK_PER_HOP 个关系，
    防止路径爆炸。设计文档 §8 要求此机制。
    """
    if current_depth > max_depth:
        return []

    found: list[dict] = []
    for eid in entity_ids:
        result = await session.run(
            """
            MATCH (p:Product {entity_id: $eid})-[r:RELATES]-(other:Product)
            WHERE other.entity_id <> $eid
            RETURN other.entity_id AS entity_id,
                   other.name AS name,
                   r.text AS text,
                   r.weight AS weight
            ORDER BY r.weight DESC
            LIMIT $topk
            """,
            eid=eid,
            topk=_TOPK_PER_HOP,
        )
        rows = await result.data()
        for row in rows:
            pid = row["entity_id"]
            if pid in visited:
                continue
            visited.add(pid)
            found.append({"entity_id": pid, "name": row["name"]})
            rel_lines.append(
                f"- {eid} ↔ {pid}: {row.get('text', '')} (权重:{row.get('weight', 0):.1f})"
            )

    # 递归下一跳
    if current_depth < max_depth and found:
        next_ids = [f["entity_id"] for f in found]
        deeper = await _l3_expand_hop(
            session, next_ids, current_depth + 1, max_depth, visited, rel_lines
        )
        found.extend(deeper)

    return found


async def aggregate_l3(entity_id: str, depth: int = 3) -> str:
    """从锚定 Product 出发，逐跳剪枝遍历，收集 L2 摘要，LLM 组织为产业链。

    Args:
        entity_id: Product entity_id
        depth: 遍历深度（默认 3，最大 3）

    Returns:
        产业链视图摘要文本

    Notes:
        - 每跳使用 TOPK_PER_HOP=10 剪枝（按 RELATES.weight 排序），
          避免路径爆炸（设计文档 §8 风险缓解）。
        - 递归展开而非单条 Cypher 路径查询，避免指数级中间结果。
    """
    depth = min(depth, 3)

    # 1. 检查缓存
    cached = await get_summary(3, entity_id, depth)
    if cached and not await is_stale(3, entity_id, depth):
        return cached["summary"]

    # 2. 递归展开 Product 路径（逐跳剪枝）
    driver = await get_async_driver()
    async with driver.session() as session:
        # 获取锚定 Product 名称
        name_result = await session.run(
            "MATCH (p:Product {entity_id: $eid}) RETURN p.name AS name",
            eid=entity_id,
        )
        name_row = await name_result.single()
        product_name = name_row["name"] if name_row else entity_id

        # 逐跳展开，收集所有 Product 节点 + 关系描述
        visited: set[str] = {entity_id}
        rel_lines: list[str] = []
        path_products = await _l3_expand_hop(
            session,
            [entity_id],
            current_depth=1,
            max_depth=depth,
            visited=visited,
            rel_lines=rel_lines,
        )

    # 3. 收集各 Product 的 L2 摘要（已访问的去重集合）
    l2_summaries = []
    all_products = [{"entity_id": entity_id, "name": product_name}] + [
        {"entity_id": p["entity_id"], "name": p["name"]}
        for p in path_products
        if p["entity_id"] != entity_id
    ]

    for p in all_products:
        pid = p["entity_id"]
        try:
            l2_text = await aggregate_l2(pid)
        except Exception as e:
            logger.warning("L2 获取失败 [%s]: %s", pid, e)
            l2_text = f"{p['name']}: 暂无生态摘要"
        l2_summaries.append(f"**{p['name']}** ({pid}): {l2_text}")

    # 4. LLM 生成
    prompt = L3_INDUSTRY_CHAIN_PROMPT.format(
        product_name=product_name,
        depth=depth,
        l2_summaries="\n\n".join(l2_summaries),
        relation_texts="\n".join(rel_lines) if rel_lines else "暂无",
    )
    summary = await chat_async(prompt, temperature=0.1)

    # 5. 缓存
    await put_summary(
        level=3,
        entity_id=entity_id,
        summary=summary.strip(),
        entity_name=product_name,
        entity_count=len(l2_summaries),
        depth=depth,
        extra={"segments": [p["name"] for p in all_products]},
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

!!! Anti-pattern 警告
    不要使用 `@tool` + `asyncio.run()` 模式（会在已有事件循环中崩溃）。
    必须继承 `StructuredTool` 并同时实现 `_run`(sync fallback) + `_arun`(async)。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated, Any

from langchain_core.tools import StructuredTool

from app.knowledge.summary_aggregator import aggregate_l1, aggregate_l2, aggregate_l3

logger = logging.getLogger(__name__)


class SummarizeTool(StructuredTool):
    """获取知识图谱实体的分层摘要。

    使用场景：
    - 宏观问题（"光模块行业现状"）→ level=2 查产品生态，需要全局视角时 level=3
    - 中观问题（"800G光模块竞争格局"）→ level=2 查产品生态
    - 微观问题（"中际旭创的客户"）→ level=1 查公司画像，需要细节时用 expand

    缓存优先：命中则直接返回，未命中则 LLM 生成并缓存。
    """

    name: str = "summarize"
    description: str = (
        "获取知识图谱实体的分层摘要（L1=公司画像, L2=产品生态, L3=产业链视图）。"
        "缓存优先，按需生成。宏观问题用L2/L3，微观问题用L1。"
    )
    args_schema: type = ...  # 会在 __init__ 后设置

    def _validate(self, entity_id: str, level: int, depth: int = 3) -> str | None:
        """参数校验，返回 None 表示通过，否则返回错误消息。"""
        if not entity_id:
            return "请先用 resolve 工具获取实体 ID。"
        if level not in (1, 2, 3):
            return f"无效的层级: {level}。有效值: 1（公司画像）, 2（产品生态）, 3（产业链视图）"
        return None

    async def _arun(
        self,
        entity_id: str,
        level: int,
        depth: int = 3,
    ) -> str:
        """异步入口 — LangChain + FastAPI 兼容。"""
        error = self._validate(entity_id, level, depth)
        if error:
            return error
        try:
            if level == 1:
                return await aggregate_l1(entity_id)
            elif level == 2:
                return await aggregate_l2(entity_id)
            else:
                return await aggregate_l3(entity_id, depth=min(depth, 3))
        except Exception as e:
            logger.error("summarize failed [%s L%d]: %s", entity_id, level, e, exc_info=True)
            return f"摘要生成失败: {e}"

    def _run(
        self,
        entity_id: str,
        level: int,
        depth: int = 3,
    ) -> str:
        """同步 fallback — 仅在无事件循环时可用。"""
        error = self._validate(entity_id, level, depth)
        if error:
            return error
        try:
            return asyncio.run(self._arun(entity_id, level, depth))
        except RuntimeError as e:
            # 如果已有事件循环（如 FastAPI 环境），_run 不应被调用
            logger.error("summarize sync fallback 失败（已有事件循环）: %s", e)
            return "摘要生成失败：当前环境不支持同步调用，请使用异步调用。"
        except Exception as e:
            logger.error("summarize failed [%s L%d]: %s", entity_id, level, e, exc_info=True)
            return f"摘要生成失败: {e}"


# ── 导出单例 ──────────────────────────────────────────────────
summarize = SummarizeTool()

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

## Task 7: Cache Invalidation Hook — 独立模块 + 事件模式

**Files:**
- Create: `backend/app/knowledge/summary_invalidator.py`  **NEW — 独立的失效触发模块**
- Modify: `backend/app/knowledge/kg_extractor.py`           **精简为 ~5 行调用**

**动机**：`kg_extractor.py` 已达 1500+ 行（代码分析报告 P1-#10）。直接在末尾加 20 行
hook 会加剧该文件的可维护性问题。改为独立的失效触发模块，kg_extractor 只需导入并调用一次。

- [ ] **Step 1: Create the independent invalidator module**

Create `backend/app/knowledge/summary_invalidator.py`:

```python
"""
summary_invalidator.py — KG 抽取完成后触发摘要缓存失效

将失效逻辑从 kg_extractor（1500+ 行）中拆分为独立模块，
遵循单一职责原则。kg_extractor 只需调用 `trigger_invalidation()`。
"""

from __future__ import annotations

import logging
from typing import Any

from app.knowledge.summary_cache import invalidate_entities

logger = logging.getLogger(__name__)


async def collect_affected_entities(
    entity_ids: list[str],
    written_rels: list[dict[str, Any]],
) -> list[str]:
    """收集受本次 KG 抽取影响的所有实体 ID。

    包括：
    - 本次抽取创建/更新的实体
    - 关系两端的实体（即使本次未直接修改）
    """
    affected: list[str] = list(dict.fromkeys(entity_ids))

    for rel in written_rels:
        from_eid = rel.get("from", "")
        to_eid = rel.get("to", "")
        if from_eid and from_eid not in affected:
            affected.append(from_eid)
        if to_eid and to_eid not in affected:
            affected.append(to_eid)

    return affected


async def trigger_invalidation(
    entity_ids: list[str],
    written_rels: list[dict[str, Any]],
) -> None:
    """KG 抽取后的缓存失效入口。

    调用位置：`extract_text_async()` 末尾（约 L1155 附近）。

    设计决策：
    - 使用 try/except 包围，不阻塞 KG 抽取主流程
    - 失败仅记日志，不重试（下次查询时会触发按需生成）
    - 抽取独立模块避免 kg_extractor 进一步膨胀
    """
    if not entity_ids and not written_rels:
        return

    try:
        affected = await collect_affected_entities(entity_ids, written_rels)
        if affected:
            await invalidate_entities(affected)
            logger.info(
                "摘要缓存失效完成: %d 个实体 (来自 kg_extractor)",
                len(affected),
            )
    except Exception as exc:
        logger.warning(
            "摘要缓存失效失败（非致命，下次查询会按需生成）: %s",
            exc,
        )
```

- [ ] **Step 2: Modify kg_extractor.py — 替换内联 hook 为模块调用**

In `extract_text_async()`, after the line where `company_signals` is computed (around line 1155),
**replace** any inline invalidation code with:

```python
# ── 摘要缓存失效（新增）────────────────────────────────────
# 使用独立模块触发，避免 kg_extractor 进一步膨胀
from app.knowledge.summary_invalidator import trigger_invalidation

await trigger_invalidation(entity_ids, written_rels)
# ── end 摘要缓存失效 ────────────────────────────────────────
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/knowledge/summary_invalidator.py backend/app/knowledge/kg_extractor.py
git commit -m "feat: add summary cache invalidation trigger as separate module"
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

覆盖范围：
- 缓存 key 确定性
- 读写 + 过期检测
- 失效传播（Company→L1, Product→L2→L3）
- invalidation trigger 模块
- SummarizeTool async 模式
"""

from unittest.mock import AsyncMock, patch

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
    async def test_invalidation_product_propagation(self):
        """验证 Product 级失效传播: L2→L3"""
        from app.knowledge.summary_cache import (
            invalidate_entity,
            is_stale,
            put_summary,
        )

        # 写入 L2/L3 缓存（Product 锚定）
        await put_summary(level=2, entity_id="P:TEST002", summary="L2", entity_name="T")
        await put_summary(level=3, entity_id="P:TEST002", summary="L3", entity_name="T", depth=3)

        # 失效 Product
        await invalidate_entity("P:TEST002")

        # L2 应 stale
        assert await is_stale(2, "P:TEST002")
        # L3 应 stale（级联传播）
        assert await is_stale(3, "P:TEST002", depth=3)

    @pytest.mark.asyncio
    async def test_invalidation_company_l1_only(self):
        """验证 Company 级失效标记 L1，L2 需关联 Product 查询（集成时测试）"""
        from app.knowledge.summary_cache import (
            invalidate_entity,
            is_stale,
            put_summary,
        )

        await put_summary(level=1, entity_id="C:TEST003", summary="L1", entity_name="T")

        # Company 失效 → L1 应 stale
        await invalidate_entity("C:TEST003")
        assert await is_stale(1, "C:TEST003")

        # L2/L3 传播依赖 Neo4j 中实际存在的关联关系，
        # 在集成测试中通过 mock _find_related_products 验证
        # 这里只测 L1 自身失效
        assert await is_stale(1, "C:TEST003")

    @pytest.mark.asyncio
    async def test_company_invalidation_with_mock_lookup(self):
        """验证 Company 失效时，通过 Neo4j 查询关联 Product 并传播到 L2/L3"""
        from app.knowledge.summary_cache import (
            invalidate_entity,
            is_stale,
            put_summary,
        )

        # 写入 Company L1 + Product L2/L3
        await put_summary(level=1, entity_id="C:TEST004", summary="L1", entity_name="T")
        await put_summary(level=2, entity_id="P:RELATED01", summary="L2", entity_name="T")
        await put_summary(level=3, entity_id="P:RELATED01", summary="L3", entity_name="T", depth=3)

        # Mock Neo4j 返回关联 Product
        with patch(
            "app.knowledge.summary_cache._find_related_products",
            AsyncMock(return_value=["P:RELATED01"]),
        ):
            await invalidate_entity("C:TEST004")

        # L1 stale
        assert await is_stale(1, "C:TEST004")
        # L2 stale（通过 mock 关联 Product 传播）
        assert await is_stale(2, "P:RELATED01")
        # L3 stale
        assert await is_stale(3, "P:RELATED01", depth=3)

    @pytest.mark.asyncio
    async def test_get_summary_miss(self):
        """验证缓存未命中返回 None"""
        from app.knowledge.summary_cache import get_summary

        result = await get_summary(1, "C:NONEXISTENT")
        assert result is None

    @pytest.mark.asyncio
    async def test_invalidator_module(self):
        """验证 summary_invalidator 模块的 collect_affected_entities"""
        from app.knowledge.summary_invalidator import collect_affected_entities

        entity_ids = ["C:300308"]
        written_rels = [
            {"from": "C:300308", "to": "P:800G"},
            {"from": "P:800G", "to": "P:CHIP01"},
        ]

        affected = await collect_affected_entities(entity_ids, written_rels)
        assert "C:300308" in affected
        assert "P:800G" in affected
        assert "P:CHIP01" in affected

    @pytest.mark.asyncio
    async def test_invalidator_trigger_empty(self):
        """验证 trigger_invalidation 在空输入时无副作用"""
        from app.knowledge.summary_invalidator import trigger_invalidation

        # 不应抛异常
        await trigger_invalidation([], [])
        await trigger_invalidation(None, None)  # type: ignore


class TestSummarizeTool:
    """SummarizeTool 工具测试（验证 async 模式）"""

    @pytest.mark.asyncio
    async def test_tool_validation_errors(self):
        """验证参数校验"""
        from app.reasoning.tools.knowledge.summarize import summarize

        assert "无效的层级" in summarize._run("C:TEST", level=4)
        assert "请先用 resolve" in summarize._run("", level=1)
        assert "无效的层级" in await summarize._arun("C:TEST", level=0)

    @pytest.mark.asyncio
    async def test_tool_inherits_structured_tool(self):
        """验证工具继承自 StructuredTool（兼容 LangChain）"""
        from langchain_core.tools import StructuredTool
        from app.reasoning.tools.knowledge.summarize import summarize

        assert isinstance(summarize, StructuredTool)
        assert summarize.name == "summarize"
        assert summarize.description
```

- [ ] **Step 2: Run the test**

```bash
cd backend && python -m pytest tests/knowledge/test_summary_cache.py -v
```

Expected: 8 tests PASS (3 cache core + 2 invalidation + 1 invalidator + 2 tool)

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