#!/usr/bin/env python3
"""
IRM Evidence 批量分类 + Job 清理脚本。

对全部 IRM evidence 运行分类器，将 JOB_COMBINED 标记为 skipped 用于
empty/defer 类别（不需要 KG 提取的 evidence）。

用法:
    python -m scripts.classify_irm_batch                     # 全量
    python -m scripts.classify_irm_batch --limit 1000        # 只处理前1000条
    python -m scripts.classify_irm_batch --dry-run           # 只统计，不做任何修改
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.mongodb import get_mongo_db
from app.knowledge.evidence import EVIDENCE_COLLECTION, EXTRACTION_JOBS_COLLECTION, JOB_COMBINED
from app.knowledge.extraction.irm_classifier import classify_irm_evidence, extraction_tier

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


async def classify_irm_batch(limit: int | None = None, dry_run: bool = False) -> dict:
    db = get_mongo_db()
    evidence_col = db[EVIDENCE_COLLECTION]
    jobs_col = db[EXTRACTION_JOBS_COLLECTION]

    query = {"source_type": "irm"}
    total = await evidence_col.count_documents(query)
    logger.info("Total IRM evidence: %d", total)

    cursor = evidence_col.find(query, {"_id": 0}).limit(limit) if limit else evidence_col.find(query, {"_id": 0})

    category_counts: Counter = Counter()
    skipped_jobs = 0
    processed = 0
    errors = 0
    start = time.time()

    batch = []
    BATCH_SIZE = 500

    async def flush_batch():
        nonlocal skipped_jobs
        if not batch:
            return
        if not dry_run:
            result = await jobs_col.update_many(
                {"evidence_id": {"$in": batch}, "job_type": JOB_COMBINED, "status": "pending"},
                {"$set": {"status": "skipped", "error": "IRM empty/defer, no KG needed"}},
            )
            skipped_jobs += int(getattr(result, "modified_count", 0))
        else:
            skipped_count = await jobs_col.count_documents(
                {"evidence_id": {"$in": batch}, "job_type": JOB_COMBINED, "status": "pending"}
            )
            skipped_jobs += skipped_count
        batch.clear()

    async for doc in cursor:
        processed += 1
        try:
            category = classify_irm_evidence(doc)
            category_counts[category] += 1
            if extraction_tier(category) == 0:
                batch.append(doc.get("evidence_id", ""))
                if len(batch) >= BATCH_SIZE:
                    await flush_batch()
        except Exception as exc:
            errors += 1
            logger.warning("Classification error [%s]: %s", doc.get("evidence_id", "")[:30], exc)

        if processed % 10000 == 0:
            elapsed = time.time() - start
            rate = processed / elapsed if elapsed > 0 else 0
            logger.info(
                "Progress: %d / %d (%.1f%%) | %.0f docs/s | cats=%s",
                processed,
                total,
                processed / total * 100,
                rate,
                dict(category_counts),
            )

    await flush_batch()

    elapsed = time.time() - start
    logger.info("=" * 60)
    logger.info("Classification complete: %d docs in %.1fs (%.0f/s)", processed, elapsed, processed / elapsed)
    logger.info("Category distribution: %s", dict(category_counts))
    logger.info("Errors: %d", errors)
    if dry_run:
        logger.info("[DRY RUN] Would skip %d JOB_COMBINED for empty/defer", skipped_jobs)
    else:
        logger.info("Actually skipped %d JOB_COMBINED jobs", skipped_jobs)
    logger.info("=" * 60)

    return {
        "processed": processed,
        "total": total,
        "errors": errors,
        "elapsed_seconds": round(elapsed, 2),
        "categories": dict(category_counts),
        "jobs_skipped": skipped_jobs,
        "dry_run": dry_run,
    }


async def main():
    parser = argparse.ArgumentParser(description="Classify IRM evidence and clean up jobs")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of evidence to process")
    parser.add_argument("--dry-run", action="store_true", help="Only count, don't modify anything")
    args = parser.parse_args()

    result = await classify_irm_batch(limit=args.limit, dry_run=args.dry_run)

    print(f"\n分类结果: {result['processed']} 条处理, {result['errors']} 条错误")
    print(f"类别分布: {result['categories']}")
    print(f"Job清理: {'[DRY RUN] ' if result['dry_run'] else ''}{result['jobs_skipped']} 条 JOB_COMBINED 已跳过")
    print(f"耗时: {result['elapsed_seconds']}s")


if __name__ == "__main__":
    asyncio.run(main())
