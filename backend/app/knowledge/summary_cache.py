"""
summary_cache.py — PostgreSQL 单层缓存 for 分层摘要

PostgreSQL: 持久化注册表，记录版本号、stale 状态、失效传播
（已移除 Redis 依赖，所有读写均走 PostgreSQL）
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.core.database import async_session

logger = logging.getLogger(__name__)


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
    """从 PostgreSQL 读取摘要缓存。未命中或已过期返回 None。"""
    from sqlalchemy import text

    pg_key = cache_key(level, entity_id, depth).removeprefix("summary:")
    async with async_session() as session:
        result = await session.execute(
            text("""
                SELECT entity_id, entity_name, level, summary_text, generated_at,
                       stale, entity_count
                FROM summary_registry
                WHERE summary_key = :key AND stale = FALSE
            """),
            {"key": pg_key},
        )
        row = result.first()
        if row is None:
            return None
        return {
            "key": f"summary:{pg_key}",
            "entity_id": row[0],
            "entity_name": row[1],
            "level": row[2],
            "summary": row[3],
            "generated_at": row[4].isoformat() if isinstance(row[4], datetime) else str(row[4]),
            "stale": False,
            "entity_count": row[6],
        }


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
    """写入 PostgreSQL 注册表。"""
    key = cache_key(level, entity_id, depth)
    now = datetime.now(timezone.utc).isoformat()

    # 写 PostgreSQL（upsert）
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
    # 分离精确 key 和 pattern key，分别处理
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

    logger.info(
        "Summary cache invalidated for entity: %s (%d keys)",
        entity_id,
        len(stale_keys),
    )


async def invalidate_entities(entity_ids: list[str]) -> None:
    """批量标记实体摘要缓存为 stale。

    使用 asyncio.gather 并发执行，每个 invalidation 独立。
    """
    if not entity_ids:
        return
    # 去重
    unique_ids = list(dict.fromkeys(entity_ids))
    import asyncio
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
