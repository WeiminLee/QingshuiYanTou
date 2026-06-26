#!/usr/bin/env python3
"""
Evidence 提取管道启动脚本

从 PostgreSQL announcements 构建 Evidence → enqueue jobs → 并发执行 extraction

用法:
    # 第一步：构建 Evidence（如已有，跳过）
    python -m scripts.run_evidence_pipeline --step build --limit 1000

    # 第二步：Enqueue extraction jobs
    python -m scripts.run_evidence_pipeline --step enqueue

    # 第三步：启动提取 workers（并发）
    python -m scripts.run_evidence_pipeline --step extract --workers 10
    python -m scripts.run_evidence_pipeline --step extract --workers 10 --job-type combined  # 只处理 combined
    python -m scripts.run_evidence_pipeline --step extract --workers 10 --job-type vector   # 只处理 vector

    # 一键启动（build → enqueue → extract）
    python -m scripts.run_evidence_pipeline --step all --workers 10

    # 查看状态
    python -m scripts.run_evidence_pipeline --step status
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# 添加 backend 到 path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.mongodb import get_mongo_db
from app.knowledge.evidence_service import EvidenceService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


async def step_status() -> None:
    """查看当前状态"""
    db = get_mongo_db()

    # Evidence 统计
    total = await db.kg_evidence.count_documents({})
    print(f"\n{'=' * 50}")
    print(f"  kg_evidence 总数: {total:,}")

    # 按 source_type 分布
    pipeline = [{"$group": {"_id": "$source_type", "count": {"$sum": 1}}}, {"$sort": {"count": -1}}]
    async for doc in db.kg_evidence.aggregate(pipeline):
        print(f"    {doc['_id']}: {doc['count']:,}")

    # Extraction Jobs 统计
    jobs_total = await db.kg_extraction_jobs.count_documents({})
    pending = await db.kg_extraction_jobs.count_documents({"status": "pending"})
    running = await db.kg_extraction_jobs.count_documents({"status": "running"})
    done = await db.kg_extraction_jobs.count_documents({"status": "done"})
    failed = await db.kg_extraction_jobs.count_documents({"status": "failed"})

    print(f"\n  kg_extraction_jobs: {jobs_total:,}")
    print(f"    pending: {pending:,}")
    print(f"    running: {running:,}")
    print(f"    done: {done:,}")
    print(f"    failed: {failed:,}")

    # 按 job_type 分布
    pipeline = [
        {"$group": {"_id": {"$cond": ["$job_type", "$job_type", "null"]}, "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]
    print("\n  按 job_type 分布:")
    async for doc in db.kg_extraction_jobs.aggregate(pipeline):
        print(f"    {doc['_id']}: {doc['count']:,}")

    print(f"{'=' * 50}\n")


async def step_build(limit: int | None = None) -> None:
    """从 PostgreSQL 构建 Evidence"""
    from sqlalchemy import text

    from app.core.database import engine
    from app.knowledge.evidence_builders_simple import (
        build_announcement_evidence,
        build_irm_evidence,
    )

    service = EvidenceService()
    BATCH_SIZE = 100
    MONGO_BATCH_SIZE = 500

    total = 0
    total_inputs = 0
    total_irm = 0
    total_announcement = 0
    start_id = 0

    logger.info("开始构建 Evidence...")

    async with engine.connect() as conn:
        while True:
            # 获取 batch
            query = text("""
                SELECT id, ts_code, name, title, ann_date, announcement_type,
                       pdf_url, file_path, content, type
                FROM announcements
                WHERE source_type = 'minishare'
                AND id > :start_id
                ORDER BY id
                LIMIT :limit
            """)
            result = await conn.execute(query, {"start_id": start_id, "limit": BATCH_SIZE})
            rows = result.fetchall()

            if not rows:
                break

            # 收集所有 evidence inputs
            all_inputs = []
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
                    "type": row[9],  # IRM 回答字段
                }

                ann_type = record.get("announcement_type", "")
                if ann_type.startswith("irm:"):
                    evidence_list = [build_irm_evidence(record)]
                    total_irm += 1
                else:
                    evidence_list = build_announcement_evidence(record)
                    total_announcement += 1

                all_inputs.extend(evidence_list)
                total_inputs += len(evidence_list)

            # 批量写入 MongoDB
            for i in range(0, len(all_inputs), MONGO_BATCH_SIZE):
                batch = all_inputs[i : i + MONGO_BATCH_SIZE]
                await service.bulk_upsert_evidence(batch)

            total += len(rows)
            start_id = rows[-1][0]
            logger.info(f"已处理 {total} 条 (last_id={start_id})")

            if limit and total >= limit:
                break

    logger.info(
        f"Evidence 构建完成: {total} 条 announcements, 其中 IRM={total_irm}, 其他={total_announcement}, 总 inputs={total_inputs}"
    )


async def step_enqueue(batch_size: int = 500) -> None:
    """Enqueue extraction jobs"""
    db = get_mongo_db()
    service = EvidenceService()

    # 查找 extraction_status.combined = pending 的 evidence
    # 这些是还没有对应 extraction job 的证据
    evidence_ids = []
    async for doc in db.kg_evidence.find({"extraction_status.combined": "pending"}, {"evidence_id": 1}):
        evidence_ids.append(doc["evidence_id"])

    if not evidence_ids:
        logger.info("没有需要 enqueue 的 evidence")
        return

    logger.info(f"找到 {len(evidence_ids):,} 个需要 enqueue 的 evidence")

    total = 0
    for i in range(0, len(evidence_ids), batch_size):
        batch = evidence_ids[i : i + batch_size]
        count = await service.bulk_enqueue_jobs(batch)
        total += count
        if (i + batch_size) % 10000 == 0 or (i + batch_size) >= len(evidence_ids):
            logger.info(f"已 enqueue {min(i + batch_size, len(evidence_ids))}/{len(evidence_ids)}")

    logger.info(f"共 enqueue {total:,} jobs")


async def step_extract(
    workers: int = 10,
    job_type: str | None = None,
    max_jobs: int | None = None,
    interval: int = 30,
) -> None:
    """启动并发 extraction worker"""
    from app.knowledge.evidence_worker import EvidenceExtractionWorker

    worker = EvidenceExtractionWorker(max_concurrency=workers)

    if max_jobs:
        # 单次运行有限数量
        result = await worker.run_once(limit=max_jobs, job_type=job_type or "combined")
        logger.info(f"Extraction 完成: {result}")
    else:
        # 持续运行
        logger.info(f"启动 {workers} 并发 workers，job_type={job_type or 'combined'}，间隔 {interval}s")
        await worker.run_loop(interval_seconds=interval, job_type=job_type or "combined")


async def step_clean_failed(max_retries: int = 3) -> int:
    """清理失败的 jobs，重置为 pending"""
    db = get_mongo_db()
    service = EvidenceService()

    result = await db.kg_extraction_jobs.update_many(
        {"status": "failed", "retry_count": {"$gte": max_retries}},
        {
            "$set": {
                "status": "pending",
                "retry_count": 0,
                "error": None,
                "updated_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc),
            }
        },
    )

    count = result.modified_count
    logger.info(f"重置 {count} 个失败 jobs 为 pending")
    return count


async def main() -> None:
    parser = argparse.ArgumentParser(description="Evidence 提取管道")
    parser.add_argument(
        "--step",
        choices=["status", "build", "enqueue", "extract", "clean", "all"],
        default="status",
        help="执行步骤",
    )
    parser.add_argument("--limit", type=int, default=None, help="限制条数")
    parser.add_argument("--workers", type=int, default=10, help="并发 worker 数")
    parser.add_argument("--job-type", type=str, choices=["combined", "vector"], help="Job 类型")
    parser.add_argument("--interval", type=int, default=30, help="Worker 轮询间隔（秒）")
    parser.add_argument("--batch-size", type=int, default=500, help="批量处理大小")
    parser.add_argument("--max-retries", type=int, default=3, help="最大重试次数（clean 命令）")

    args = parser.parse_args()

    if args.step == "status":
        await step_status()

    elif args.step == "build":
        await step_build(limit=args.limit)

    elif args.step == "enqueue":
        await step_enqueue(batch_size=args.batch_size)

    elif args.step == "extract":
        await step_extract(
            workers=args.workers,
            job_type=args.job_type,
            max_jobs=args.limit,
            interval=args.interval,
        )

    elif args.step == "clean":
        await step_clean_failed(max_retries=args.max_retries)

    elif args.step == "all":
        # 一键执行完整流程
        logger.info("=" * 50)
        logger.info("启动完整 Evidence 提取管道")
        logger.info("=" * 50)

        # Step 1: Build
        logger.info("\n>>> Step 1: 构建 Evidence")
        await step_build(limit=args.limit)

        # Step 2: Enqueue
        logger.info("\n>>> Step 2: Enqueue Extraction Jobs")
        await step_enqueue(batch_size=args.batch_size)

        # Step 3: Status
        logger.info("\n>>> Step 3: 状态预览")
        await step_status()

        # Step 4: Extract
        logger.info("\n>>> Step 4: 启动 Extraction Workers")
        await step_extract(
            workers=args.workers,
            job_type=args.job_type,
            max_jobs=None,  # 持续运行
            interval=args.interval,
        )


if __name__ == "__main__":
    asyncio.run(main())
