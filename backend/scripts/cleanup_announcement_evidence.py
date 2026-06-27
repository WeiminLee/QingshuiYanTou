"""
清理公告 evidence 中噪音章节。

从 kg_evidence 中删除不匹配 KEEP 规则的公告章节，同时清理
kg_extraction_jobs 中对应的 job。

用法：
    python -m scripts.cleanup_announcement_evidence --dry-run   # 预览
    python -m scripts.cleanup_announcement_evidence              # 正式执行
"""

from __future__ import annotations

import asyncio
import logging
import sys
import time

from app.core.mongodb import get_mongo_client, _extract_db_name
from app.config import settings
from app.knowledge.evidence_builders_simple import _classify_announcement_chapter

logger = logging.getLogger(__name__)


async def main() -> None:
    dry_run = "--dry-run" in sys.argv

    client = get_mongo_client()
    db_name = _extract_db_name(settings.mongodb_url)
    db = client[db_name]

    evidence_coll = db["kg_evidence"]
    jobs_coll = db["kg_extraction_jobs"]

    # ── 1. 获取所有公告 evidence 的 _id + 分类所需字段 ──────────────
    cursor = evidence_coll.find(
        {"source_type": "announcement"},
        {
            "_id": 1,
            "source_ref.chapter_heading": 1,
            "text_excerpt": 1,
            "subject_hint.ann_type": 1,
        },
    ).batch_size(500)

    total = await evidence_coll.count_documents({"source_type": "announcement"})

    to_delete: list[object] = []
    stats: dict[str, int] = {}

    processed = 0
    t0 = time.perf_counter()

    async for doc in cursor:
        heading = doc.get("source_ref", {}).get("chapter_heading", "") or ""
        body = doc.get("text_excerpt", "") or ""
        ann_type = doc.get("subject_hint", {}).get("ann_type", "") or ""

        decision = _classify_announcement_chapter(heading, body, ann_type)
        if decision == "skip":
            to_delete.append(doc["_id"])
            stats[ann_type] = stats.get(ann_type, 0) + 1

        processed += 1
        if processed % 5000 == 0:
            elapsed = time.perf_counter() - t0
            rate = processed / elapsed
            eta = (total - processed) / rate if rate > 0 else 0
            print(
                f"  扫描: {processed}/{total} | 已标记删除: {len(to_delete)} | "
                f"{rate:.0f}条/秒 | ETA {eta:.0f}s"
            )

    elapsed = time.perf_counter() - t0
    print(f"\n扫描完成: {processed}条 in {elapsed:.1f}s")
    print(f"标记删除: {len(to_delete)} 条 ({len(to_delete)/total*100:.1f}%)")
    print("\n按 ann_type 分布:")
    for ann_type, count in sorted(stats.items(), key=lambda x: -x[1]):
        print(f"  {ann_type:>20}: {count}")

    if not to_delete:
        print("\n没有需要删除的 evidence。")
        return

    if dry_run:
        print(f"\n🏁 Dry-run 模式，未执行删除。传 --dry-run 去掉则正式执行。")
        return

    # ── 2. 删除 ────────────────────────────────────────────────────
    print(f"\n开始删除 {len(to_delete)} 条 evidence 及关联 job...")

    BATCH = 500
    deleted_evidence = 0
    deleted_jobs = 0
    t0 = time.perf_counter()

    for i in range(0, len(to_delete), BATCH):
        batch = to_delete[i : i + BATCH]

        # 删除 evidence
        result = await evidence_coll.delete_many({"_id": {"$in": batch}})
        deleted_evidence += result.deleted_count

        # 删除关联的 extraction jobs
        job_result = await jobs_coll.delete_many(
            {"evidence_id": {"$in": [str(eid) for eid in batch]}}
        )
        deleted_jobs += job_result.deleted_count

        if (i + BATCH) % 5000 == 0 or i + BATCH >= len(to_delete):
            elapsed = time.perf_counter() - t0
            pct = min(100, (i + BATCH) / len(to_delete) * 100)
            print(
                f"  删除: {pct:.0f}% | evidence {deleted_evidence} | "
                f"jobs {deleted_jobs} | {elapsed:.1f}s"
            )

    elapsed = time.perf_counter() - t0
    print(f"\n✅ 删除完成: {deleted_evidence} evidence + {deleted_jobs} jobs in {elapsed:.1f}s")

    # ── 3. 最终统计 ──────────────────────────────────────────────
    remaining = await evidence_coll.count_documents({"source_type": "announcement"})
    print(f"公告 evidence 剩余: {remaining}")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    asyncio.run(main())
