#!/usr/bin/env python3
"""
批量构建 Evidence 脚本

从 PostgreSQL announcements 表读取数据，批量构建 Evidence 入 MongoDB。

用法:
    python -m scripts.build_evidence_batch --type announcement
    python -m scripts.build_evidence_batch --type irm
    python -m scripts.build_evidence_batch --type all
    python -m scripts.build_evidence_batch --type all --limit 1000  # 限制条数
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from pathlib import Path
from typing import Any

# 添加 backend 到 path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text

from app.core.database import engine
from app.core.mongodb import get_mongo_db
from app.knowledge.evidence_service import EvidenceService
from app.knowledge.evidence_builders_simple import (
    build_announcement_evidence,
    build_irm_evidence,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

BATCH_SIZE = 100


async def fetch_announcements_batch(
    conn,
    start_id: int,
    batch_size: int,
    filter_type: str = "announcement",  # "announcement" | "irm" | "all"
):
    """批量获取公告数据"""
    if filter_type == "announcement":
        where_clause = "source_type = 'minishare' AND announcement_type NOT LIKE 'irm:%'"
    elif filter_type == "irm":
        where_clause = "source_type = 'minishare' AND announcement_type LIKE 'irm:%'"
    else:
        where_clause = "source_type = 'minishare'"

    query = text(f"""
        SELECT id, ts_code, name, title, ann_date, announcement_type,
               pdf_url, file_path, content
        FROM announcements
        WHERE {where_clause}
        AND id > :start_id
        ORDER BY id
        LIMIT :limit
    """)
    result = await conn.execute(query, {"start_id": start_id, "limit": batch_size})
    return result.fetchall()


async def build_announcement_evidence_batch(limit: int | None = None):
    """批量构建公告 Evidence"""
    service = EvidenceService()
    total = 0
    start_id = 0

    logger.info("开始构建公告 Evidence...")

    async with engine.connect() as conn:
        while True:
            rows = await fetch_announcements_batch(
                conn, start_id, BATCH_SIZE, "announcement"
            )
            if not rows:
                break

            for row in rows:
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
                }

                evidence_list = build_announcement_evidence(record)
                for ei in evidence_list:
                    await service.upsert_evidence(ei)

                total += 1

            start_id = rows[-1][0]
            logger.info(f"已处理公告 {total} 条 (last_id={start_id})")

            if limit and total >= limit:
                break

    logger.info(f"公告 Evidence 构建完成: {total} 条")
    return total


async def build_irm_evidence_batch(limit: int | None = None):
    """批量构建 IRM Evidence"""
    service = EvidenceService()
    total = 0
    start_id = 0

    logger.info("开始构建 IRM Evidence...")

    async with engine.connect() as conn:
        while True:
            rows = await fetch_announcements_batch(
                conn, start_id, BATCH_SIZE, "irm"
            )
            if not rows:
                break

            for row in rows:
                record = {
                    "id": row[0],
                    "ts_code": row[1],
                    "name": row[2],
                    "title": row[3],
                    "ann_date": row[4],
                    "announcement_type": row[5],
                    "content": row[8],
                }

                evidence_input = build_irm_evidence(record)
                await service.upsert_evidence(evidence_input)
                total += 1

            start_id = rows[-1][0]
            logger.info(f"已处理 IRM {total} 条 (last_id={start_id})")

            if limit and total >= limit:
                break

    logger.info(f"IRM Evidence 构建完成: {total} 条")
    return total


async def enqueue_all_jobs():
    """为所有 pending evidence enqueue jobs"""
    db = get_mongo_db()
    service = EvidenceService()

    count = 0
    async for doc in db.kg_evidence.find({"extraction_status": None}):
        await service.enqueue_default_jobs(doc["evidence_id"])
        count += 1
        if count % 1000 == 0:
            logger.info(f"已 enqueue {count} jobs")

    logger.info(f"共 enqueue {count} jobs")
    return count


async def main():
    parser = argparse.ArgumentParser(description="批量构建 Evidence")
    parser.add_argument(
        "--type",
        choices=["announcement", "irm", "all"],
        default="all",
        help="构建类型: announcement(非IRM公告) | irm(IRM问答) | all(全部)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="限制条数（用于测试）",
    )
    args = parser.parse_args()

    start_time = time.time()

    if args.type in ["announcement", "all"]:
        await build_announcement_evidence_batch(limit=args.limit)

    if args.type in ["irm", "all"]:
        await build_irm_evidence_batch(limit=args.limit)

    logger.info("开始 enqueue extraction jobs...")
    await enqueue_all_jobs()

    elapsed = time.time() - start_time
    logger.info(f"全部完成，耗时 {elapsed:.1f}s")


if __name__ == "__main__":
    asyncio.run(main())
