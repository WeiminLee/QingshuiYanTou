#!/usr/bin/env python3
"""
公告 PDF → 知识层证据摄取脚本

从 PostgreSQL minishare_announcements 表读取已下载 PDF 的公告，
通过 build_announcement_evidence() 构建 evidence 并加入知识层提取队列。

用法：
    uv run python scripts/ingest_announcements_to_kg.py                     # 全量
    uv run python scripts/ingest_announcements_to_kg.py --limit 10         # 只处理 10 条
    uv run python scripts/ingest_announcements_to_kg.py --ts-code 000001.SZ # 单只股票
    uv run python scripts/ingest_announcements_to_kg.py --offset 31400     # 断点续跑
    uv run python scripts/ingest_announcements_to_kg.py --dry-run --limit 10
"""

from __future__ import annotations

import argparse
import asyncio
import gc
import logging
import sys
from pathlib import Path

# 添加 backend 目录到 path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import text

from app.core.database import engine
from app.knowledge.evidence_builders_simple import build_announcement_evidence
from app.knowledge.evidence_service import EvidenceService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("ingest_announcements")

BATCH_SIZE = 100  # 每批处理 100 条
EVIDENCE_FLUSH_INTERVAL = 50  # 每 50 条 evidence 批量写入一次


async def get_announcements(
    ts_code: str | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> list[dict]:
    """从 minishare_announcements 表读取「有 PDF 且尚未 build evidence」的公告记录。"""
    conditions = ["file_path IS NOT NULL", "evidence_at IS NULL"]
    params: dict[str, int | str] = {}
    if ts_code:
        conditions.append("ts_code = :ts_code")
        params["ts_code"] = ts_code
    where = " AND ".join(conditions)
    sql = f"""
        SELECT id, ann_date, ts_code, name, title, type as announcement_type,
               source_url as pdf_url, file_path
        FROM minishare_announcements
        WHERE {where}
        ORDER BY ann_date DESC
        OFFSET :offset
        LIMIT :limit
    """
    params["offset"] = offset
    params["limit"] = limit or 1000
    async with engine.connect() as conn:
        rows = (await conn.execute(text(sql), params)).mappings().all()
    return [dict(row) for row in rows]


async def get_total_count(ts_code: str | None = None) -> int:
    """获取有 PDF 的公告总数。"""
    conditions = ["file_path IS NOT NULL"]
    params: dict[str, str] = {}
    if ts_code:
        conditions.append("ts_code = :ts_code")
        params["ts_code"] = ts_code
    where = " AND ".join(conditions)
    sql = f"SELECT count(*) FROM minishare_announcements WHERE {where}"
    async with engine.connect() as conn:
        result = await conn.execute(text(sql), params)
        return result.scalar() or 0


async def main():
    parser = argparse.ArgumentParser(description="公告 PDF → 知识层证据摄取")
    parser.add_argument("--ts-code", type=str, default=None, help="指定个股 ts_code")
    parser.add_argument("--limit", type=int, default=None, help="限制处理条数")
    parser.add_argument("--offset", type=int, default=0, help="跳过前 N 条（断点续跑用）")
    parser.add_argument("--dry-run", action="store_true", help="试运行")
    args = parser.parse_args()

    total = await get_total_count(ts_code=args.ts_code)
    logger.info("有 PDF 的公告总数: %d%s", total, f" (ts_code={args.ts_code})" if args.ts_code else "")

    if args.dry_run:
        limit = args.limit or min(10, total)
        records = await get_announcements(ts_code=args.ts_code, limit=limit)
        logger.info("=== 试运行模式 ===")
        logger.info("将处理 %d 条公告", len(records))
        for rec in records:
            evidence_list = build_announcement_evidence(rec)
            decisions = []
            for ev in evidence_list:
                if ev.source_ref.get("is_aggregated"):
                    merged = ev.source_ref.get("merged_chapters", [])
                    headings = [
                        c.get("heading", "")[:20] or "(无标题)"
                        for c in merged
                    ]
                    decisions.append(
                        f"aggregated({len(merged)}ch):{','.join(headings[:3])}"
                    )
                else:
                    decisions.append("title-only")
            logger.info(
                "  %s %s %s → %d 个 evidence, 章节: %s",
                rec["ts_code"],
                rec["ann_date"],
                str(rec["title"])[:50],
                len(evidence_list),
                ", ".join(decisions[:3]),
            )
        logger.info("=== 试运行结束，无实际写入 ===")
        return

    service = EvidenceService()
    processed = args.offset
    evidence_created = 0
    jobs_queued = 0
    offset = args.offset

    while True:
        fetch_limit = min(args.limit - processed, BATCH_SIZE) if args.limit else BATCH_SIZE
        if fetch_limit <= 0:
            break
        records = await get_announcements(ts_code=args.ts_code, limit=fetch_limit, offset=offset)
        if not records:
            break
        offset += len(records)

        # 收集这一批的 evidence inputs
        all_inputs = []
        for rec in records:
            evidence_list = build_announcement_evidence(rec)
            all_inputs.extend(evidence_list)

        if all_inputs:
            # 批量写入 evidence
            written = await service.bulk_upsert_evidence(all_inputs)
            # 收集 evidence_ids 批量 enqueue jobs
            evidence_ids = []
            for inp in all_inputs:
                from app.knowledge.evidence import stable_evidence_id
                eid = stable_evidence_id(inp.source_type, inp.source_id, 0, inp.text_excerpt)
                evidence_ids.append(eid)
            # 去重
            evidence_ids = list(set(evidence_ids))
            enqueued = await service.bulk_enqueue_jobs(evidence_ids)
            evidence_created += written
            jobs_queued += enqueued

        processed += len(records)
        # 主动回收内存，防止长时间运行导致内存膨胀
        if processed % 1000 == 0:
            gc.collect()
        logger.info(
            "进度: %d/%d, evidence=%d, jobs=%d",
            processed,
            total if not args.limit else 0,
            evidence_created,
            jobs_queued,
        )

        if args.limit and processed >= args.limit:
            break

    logger.info("公告证据摄取完成:")
    logger.info("  处理记录: %d", processed)
    logger.info("  创建证据: %d", evidence_created)
    logger.info("  入队作业: %d", jobs_queued)


if __name__ == "__main__":
    asyncio.run(main())