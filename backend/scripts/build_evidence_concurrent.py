#!/usr/bin/env python3
"""
并发 Evidence 构建脚本

使用 asyncio.gather 并发处理 PDF 解析

用法:
    python -m scripts.build_evidence_concurrent --workers 8 --limit 10000
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
from sqlalchemy.ext.asyncio import create_async_engine

from app.knowledge.evidence_builders_simple import build_announcement_evidence
from app.knowledge.evidence_service import EvidenceService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


async def fetch_batch(conn, start_id: int, batch_size: int = 100):
    """获取一批数据"""
    query = text("""
        SELECT id, ts_code, name, title, ann_date, announcement_type,
               pdf_url, file_path, content, type
        FROM announcements
        WHERE source_type = 'minishare'
        AND announcement_type NOT LIKE 'irm:%'
        AND file_path IS NOT NULL
        AND file_path != ''
        AND id > :start_id
        ORDER BY id
        LIMIT :limit
    """)
    result = await conn.execute(query, {"start_id": start_id, "limit": batch_size})
    return result.fetchall()


async def process_record(record: dict) -> list:
    """处理单条记录，返回 evidence list"""
    try:
        return build_announcement_evidence(record)
    except Exception as e:
        logger.warning(f"处理记录失败 [{record.get('id')}]: {e}")
        return []


async def build_concurrent(
    workers: int = 8,
    batch_size: int = 50,
    limit: int | None = None,
):
    """并发构建公告 Evidence"""
    service = EvidenceService()

    # 创建独立的数据库连接用于游标
    engine = create_async_engine(
        "postgresql+asyncpg://qingshui:qingshui123@localhost:5433/qingshui",
        pool_size=workers + 2,
        max_overflow=10,
    )

    total_announcements = 0
    total_inputs = 0
    start_id = 0
    start_time = time.time()
    last_log_time = start_time

    logger.info(f"开始并发构建公告 Evidence (workers={workers}, batch_size={batch_size})...")

    while True:
        if limit and total_announcements >= limit:
            break

        async with engine.connect() as conn:
            rows = await fetch_batch(conn, start_id, batch_size)
            if not rows:
                break

            # 构建记录
            records = []
            for row in rows:
                records.append(
                    {
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
                )

            # 并发处理
            semaphore = asyncio.Semaphore(workers)

            async def process_with_sem(record):
                async with semaphore:
                    return await process_record(record)

            results = await asyncio.gather(*[process_with_sem(r) for r in records])

            # 收集所有 evidence
            all_inputs = []
            for evidence_list in results:
                all_inputs.extend(evidence_list)

            # 批量写入
            if all_inputs:
                for i in range(0, len(all_inputs), 500):
                    batch = all_inputs[i : i + 500]
                    await service.bulk_upsert_evidence(batch)

            total_announcements += len(records)
            total_inputs += len(all_inputs)
            start_id = rows[-1][0]

            # 日志
            now = time.time()
            if now - last_log_time >= 10:
                elapsed = now - start_time
                rate = total_announcements / elapsed if elapsed > 0 else 0
                eta = (limit - total_announcements) / rate / 60 if limit and rate > 0 else 0
                logger.info(
                    f"已构建 {total_announcements} announcements ({total_inputs} inputs), "
                    f"速度: {rate:.1f}/s, ETA: {eta:.1f}min"
                )
                last_log_time = now

    await engine.dispose()

    elapsed = time.time() - start_time
    logger.info(
        f"公告 Evidence 构建完成: {total_announcements} announcements ({total_inputs} inputs), "
        f"耗时 {elapsed:.1f}s, 速度: {total_announcements / elapsed:.1f}/s"
    )
    return total_announcements, total_inputs


async def main():
    parser = argparse.ArgumentParser(description="并发 Evidence 构建")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    await build_concurrent(
        workers=args.workers,
        batch_size=args.batch_size,
        limit=args.limit,
    )


if __name__ == "__main__":
    asyncio.run(main())
