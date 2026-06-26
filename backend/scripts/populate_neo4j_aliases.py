"""
One-time migration: populate Neo4j Company node `aliases` property
from StockNameResolver (PostgreSQL stocks + company_profiles + supplemental_aliases.json).

For each Company node with entity_id starting with 'C:':
  1. Get all known name variants from StockNameResolver.get_aliases(ts_code)
  2. SET n.aliases = [variants except n.name]

Usage:
    uv run --directory backend -- python scripts/populate_neo4j_aliases.py
    uv run --directory backend -- python scripts/populate_neo4j_aliases.py --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


async def main(dry_run: bool = False) -> None:
    from app.core.neo4j_client import run, run_write
    from app.knowledge.stock_name_resolver import get_stock_name_resolver

    # Step 1: warm cache
    resolver = get_stock_name_resolver()
    await resolver.warm_cache()
    logger.info("StockNameResolver 已加载: %d 条名称映射", resolver.size())

    # Step 2: list all Company nodes with C: prefix
    nodes = run(
        """
        MATCH (c:Company)
        WHERE c.entity_id STARTS WITH 'C:'
        RETURN c.entity_id AS entity_id,
               c.name AS name,
               c.ts_code AS ts_code,
               c.aliases AS existing_aliases
        """,
        {},
    )
    logger.info("发现 %d 个 Company 节点", len(nodes))

    # Step 3: build update payload
    updates: list[dict] = []
    for node in nodes:
        entity_id = node["entity_id"]
        name = node["name"]
        ts_code = node["ts_code"] or entity_id[2:]  # strip "C:" prefix
        existing = node.get("existing_aliases") or []

        all_names = resolver.get_aliases(ts_code)
        new_aliases = [n for n in all_names if n and n != name]

        # Merge with existing aliases (immutable: build new list)
        merged = list({*existing, *new_aliases})
        if not merged or sorted(merged) == sorted(existing or []):
            continue

        updates.append(
            {
                "entity_id": entity_id,
                "aliases": merged,
            }
        )

    logger.info("需要更新 %d 个节点", len(updates))

    if dry_run:
        logger.info("DRY-RUN 模式，不写入。前 5 个示例：")
        for u in updates[:5]:
            logger.info("  %s → %s", u["entity_id"], u["aliases"])
        return

    # Step 4: batch UNWIND update
    BATCH_SIZE = 500
    written = 0
    for i in range(0, len(updates), BATCH_SIZE):
        batch = updates[i : i + BATCH_SIZE]
        run_write(
            """
            UNWIND $rows AS row
            MATCH (c:Company {entity_id: row.entity_id})
            SET c.aliases = row.aliases
            """,
            {"rows": batch},
        )
        written += len(batch)
        logger.info("已写入 %d / %d", written, len(updates))

    logger.info("完成：%d 个 Company 节点的 aliases 已更新", written)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Populate Neo4j Company.aliases from StockNameResolver")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without writing")
    args = parser.parse_args()
    asyncio.run(main(dry_run=args.dry_run))
