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
        logger.warning("查询关联 Product 失败 [%s]: %s", entity_id, e)
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
            stale_keys.append(f"L3:{pid}:3")
            stale_keys.append(f"L3:{pid}:2")
    else:
        # Product → L2 直接失效
        stale_keys.append(f"L2:{entity_id}")
        # L3 — 该 Product 的所有 depth 变体
        stale_keys.append(f"L3:{entity_id}:3")
        stale_keys.append(f"L3:{entity_id}:2")

    # 3. PG 标记 stale
    await _mark_stale_in_pg(stale_keys)

    # 4. Redis 清理
    await _delete_from_redis(stale_keys)

    logger.info(
        "Summary cache invalidated for entity: %s (%d keys)",
        entity_id,
        len(stale_keys),
    )


async def invalidate_entities(entity_ids: list[str]) -> None:
    """批量标记实体摘要缓存为 stale。"""
    if not entity_ids:
        return
    # 去重
    unique_ids = list(dict.fromkeys(entity_ids))
    for eid in unique_ids:
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
