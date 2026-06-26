#!/usr/bin/env python3
"""
高效的 Evidence 批量构建脚本

策略：
1. 先构建所有 IRM 数据（快，约 1000条/秒）
2. 再构建有 PDF 的公告数据（较慢，依赖 PDF 解析）

用法:
    python -m scripts.build_evidence_fast --type irm --limit 100000
    python -m scripts.build_evidence_fast --type announcement --limit 10000
    python -m scripts.build_evidence_fast --type all --limit 100000
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text

from app.core.database import engine
from app.core.mongodb import get_mongo_db
from app.knowledge.evidence_builders_simple import build_announcement_evidence, build_irm_evidence
from app.knowledge.evidence_service import EvidenceService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


async def build_irm_batch(batch_size: int = 5000, limit: int | None = None):
    """批量构建 IRM Evidence"""
    service = EvidenceService()
    total = 0

    logger.info(f"开始构建 IRM Evidence (batch_size={batch_size})...")

    async with engine.connect() as conn:
        query = text("""
            SELECT id, ts_code, name, title, ann_date, announcement_type, type
            FROM announcements
            WHERE source_type = 'minishare'
            AND announcement_type LIKE 'irm:%'
            ORDER BY id
        """)
        result = await conn.stream(query)

        batch = []
        start_time = time.time()

        async for row in result:
            record = {
                "id": row[0],
                "ts_code": row[1],
                "name": row[2],
                "title": row[3],
                "ann_date": row[4],
                "announcement_type": row[5],
                "type": row[6],
            }
            evidence = build_irm_evidence(record)
            batch.append(evidence)

            if len(batch) >= batch_size:
                await service.bulk_upsert_evidence(batch)
                total += len(batch)
                batch = []

                elapsed = time.time() - start_time
                rate = total / elapsed if elapsed > 0 else 0
                logger.info(f"已构建 {total} 条 (速度: {rate:.0f}/s)")

                if limit and total >= limit:
                    break

        # 处理剩余
        if batch:
            await service.bulk_upsert_evidence(batch)
            total += len(batch)

    elapsed = time.time() - start_time
    logger.info(f"IRM Evidence 构建完成: {total} 条, 耗时 {elapsed:.1f}s, 速度: {total / elapsed:.0f}/s")
    return total


async def build_announcement_batch(batch_size: int = 100, limit: int | None = None):
    """批量构建公告 Evidence（需要 PDF 解析，较慢）"""
    service = EvidenceService()
    total = 0
    total_inputs = 0

    logger.info(f"开始构建公告 Evidence (batch_size={batch_size})...")

    async with engine.connect() as conn:
        query = text("""
            SELECT id, ts_code, name, title, ann_date, announcement_type,
                   pdf_url, file_path, content, type
            FROM announcements
            WHERE source_type = 'minishare'
            AND announcement_type NOT LIKE 'irm:%'
            AND file_path IS NOT NULL
            AND file_path != ''
            ORDER BY id
        """)
        result = await conn.stream(query)

        batch = []
        start_time = time.time()
        last_log_time = start_time

        async for row in result:
            record = {
                "id": row[0],
                "ts_code": row[1],
                "name": row[2],
                "title": row[3],
                "ann_date": row[4],
                "announcement_type": row[5],
                "pdf_url": row[6],
                "file_path": row[7],
                "content": row[8],
                "type": row[9],
            }
            evidence_list = build_announcement_evidence(record)
            batch.extend(evidence_list)
            total_inputs += len(evidence_list)

            if len(evidence_list) >= batch_size:
                await service.bulk_upsert_evidence(batch)
                total += batch_size
                batch = []

                now = time.time()
                if now - last_log_time >= 10:
                    elapsed = now - start_time
                    rate = total / elapsed if elapsed > 0 else 0
                    logger.info(f"已构建 {total} 条 announcements ({total_inputs} inputs, 速度: {rate:.0f}/s)")
                    last_log_time = now

                if limit and total >= limit:
                    break

        # 处理剩余
        if batch:
            await service.bulk_upsert_evidence(batch)
            total += len(batch)

    elapsed = time.time() - start_time
    logger.info(
        f"公告 Evidence 构建完成: {total} 条 announcements ({total_inputs} inputs), 耗时 {elapsed:.1f}s, 速度: {total / elapsed:.1f}/s"
    )
    return total


async def main():
    parser = argparse.ArgumentParser(description="高效 Evidence 构建")
    parser.add_argument("--type", choices=["irm", "announcement", "all"], default="all")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--batch-size", type=int, default=5000)
    args = parser.parse_args()

    start_time = time.time()

    if args.type in ["irm", "all"]:
        irm_count = await build_irm_batch(batch_size=args.batch_size, limit=args.limit if args.type == "irm" else None)

    if args.type in ["announcement", "all"]:
        ann_count = await build_announcement_batch(
            batch_size=100, limit=args.limit if args.type == "announcement" else None
        )

    # 统计
    db = get_mongo_db()
    total = await db.kg_evidence.count_documents({})

    pipeline = [{"$group": {"_id": "$source_type", "count": {"$sum": 1}}}, {"$sort": {"count": -1}}]

    print(f"\n{'=' * 50}")
    print("  Evidence 构建完成!")
    print(f"  总计: {total:,} 条")
    async for doc in db.kg_evidence.aggregate(pipeline):
        print(f"    {doc['_id']}: {doc['count']:,}")
    print(f"  总耗时: {time.time() - start_time:.1f}s")
    print(f"{'=' * 50}")


if __name__ == "__main__":
    asyncio.run(main())
