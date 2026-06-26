"""
P1: repair notice PDF paths and KG file-index inputs.

This script scans ``storage/notices`` and reconnects local PDFs to:
  1. PostgreSQL ``announcements.file_path`` where a matching announcement exists.
  2. MongoDB ``kg_file_index`` so the KG extraction pipeline can process them.

It is intentionally idempotent and safe to run repeatedly.

Examples:
  python scripts/p1_repair_notice_kg_inputs.py --limit 500
  python scripts/p1_repair_notice_kg_inputs.py --limit 500 --process-kg-limit 10
  python scripts/p1_repair_notice_kg_inputs.py --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
from sqlalchemy import text

load_dotenv()

from app.core.database import engine
from app.core.mongodb import get_mongo_db
from app.data_pipeline.announcement_filter import classify_title
from app.data_pipeline.progress import FAILED, PARTIAL, SUCCESS, IngestionProgressTracker
from scripts.kg_extraction_pipeline import KGPipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

NOTICE_ROOT = Path(__file__).resolve().parent.parent / "storage" / "notices"
KG_INDEX_COLLECTION = "kg_file_index"
HIGH_VALUE_DOC_TYPES = {
    "annual_report",
    "half_report",
    "quarter_report",
    "research_survey",
    "ma_activity",
    "investment",
}


def _sha256(file_path: Path) -> str:
    h = hashlib.sha256()
    with file_path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _iter_notice_pdfs(limit: int | None = None) -> list[Path]:
    files: list[Path] = []
    for path in sorted(NOTICE_ROOT.glob("*/*/*.pdf")):
        if path.is_file():
            files.append(path)
            if limit and len(files) >= limit:
                break
    return files


def _parse_path(path: Path) -> dict[str, str]:
    # storage/notices/{ts_code}/{YYYY-MM}/{filename}.pdf
    parts = path.relative_to(NOTICE_ROOT).parts
    ts_code = parts[0] if len(parts) >= 3 else ""
    year_month = parts[1] if len(parts) >= 3 else ""
    title = path.stem
    cninfo_id = ""
    if "_" in title:
        maybe_id, rest = title.split("_", 1)
        if maybe_id.isdigit() or maybe_id.startswith(("ann_", "notice_")):
            cninfo_id = maybe_id
            title = rest or title
    return {"ts_code": ts_code, "year_month": year_month, "title": title, "cninfo_id": cninfo_id}


async def _find_announcement(path: Path, parsed: dict[str, str]) -> dict[str, Any] | None:
    async with engine.connect() as conn:
        if parsed["cninfo_id"]:
            row = (
                (
                    await conn.execute(
                        text(
                            """
                        SELECT cninfo_id, ts_code, title, announcement_type, ann_date
                        FROM announcements
                        WHERE cninfo_id = :cninfo_id
                        LIMIT 1
                        """
                        ),
                        {"cninfo_id": parsed["cninfo_id"]},
                    )
                )
                .mappings()
                .first()
            )
            if row:
                return dict(row)

        row = (
            (
                await conn.execute(
                    text(
                        """
                    SELECT cninfo_id, ts_code, title, announcement_type, ann_date
                    FROM announcements
                    WHERE ts_code = :ts_code
                      AND (
                        title = :title
                        OR title LIKE :title_prefix
                        OR :title LIKE title || '%%'
                      )
                    ORDER BY ann_date DESC NULLS LAST
                    LIMIT 1
                    """
                    ),
                    {
                        "ts_code": parsed["ts_code"],
                        "title": parsed["title"],
                        "title_prefix": parsed["title"][:80] + "%",
                    },
                )
            )
            .mappings()
            .first()
        )
        return dict(row) if row else None


async def _update_postgres_file_path(cninfo_id: str, path: Path, doc_type: str, dry_run: bool) -> bool:
    if dry_run:
        async with engine.connect() as conn:
            row = (
                await conn.execute(
                    text(
                        """
                        SELECT 1
                        FROM announcements
                        WHERE cninfo_id = :cninfo_id
                          AND (
                            file_path IS NULL OR file_path = '' OR file_path <> :file_path
                            OR announcement_type IS NULL OR announcement_type IN ('disclosure', 'other', 'unknown')
                          )
                        LIMIT 1
                        """
                    ),
                    {"cninfo_id": cninfo_id, "file_path": str(path)},
                )
            ).first()
        return bool(row)
    async with engine.begin() as conn:
        result = await conn.execute(
            text(
                """
                UPDATE announcements
                SET file_path = :file_path,
                    announcement_type = CASE
                        WHEN announcement_type IS NULL OR announcement_type IN ('disclosure', 'other', 'unknown')
                        THEN :doc_type
                        ELSE announcement_type
                    END
                WHERE cninfo_id = :cninfo_id
                  AND (
                    file_path IS NULL OR file_path = '' OR file_path <> :file_path
                    OR announcement_type IS NULL OR announcement_type IN ('disclosure', 'other', 'unknown')
                  )
                """
            ),
            {"cninfo_id": cninfo_id, "file_path": str(path), "doc_type": doc_type},
        )
    return bool(result.rowcount and result.rowcount > 0)


async def _upsert_kg_file_index(path: Path, announcement: dict[str, Any], doc_type: str, dry_run: bool) -> bool:
    if dry_run:
        db = get_mongo_db()
        existing = await db[KG_INDEX_COLLECTION].find_one(
            {"file_path": str(path), "status": {"$in": ["pending", "extracting", "done"]}},
            {"_id": 1},
        )
        return existing is None
    db = get_mongo_db()
    col = db[KG_INDEX_COLLECTION]
    await col.create_index("file_path", unique=True)
    await col.create_index("cninfo_id")
    await col.create_index("status")
    stat = path.stat()
    file_hash = _sha256(path)
    now = datetime.utcnow()
    existing = await col.find_one({"file_path": str(path)}, {"file_hash": 1, "status": 1})
    status = "pending"
    if existing and existing.get("file_hash") == file_hash and existing.get("status") == "done":
        status = "done"
    await col.update_one(
        {"file_path": str(path)},
        {
            "$set": {
                "file_name": path.name,
                "file_type": "pdf",
                "file_size": stat.st_size,
                "mtime": stat.st_mtime,
                "file_hash": file_hash,
                "status": status,
                "ts_code": announcement.get("ts_code"),
                "cninfo_id": announcement.get("cninfo_id"),
                "title": announcement.get("title"),
                "source_type": "annual_report" if doc_type == "annual_report" else "announcement",
                "doc_type": doc_type,
                "schema_version": "v4",
                "parser_version": "v4",
                "updated_at": now,
            },
            "$setOnInsert": {
                "entities_count": 0,
                "relations_count": 0,
                "extracted_at": None,
                "error": None,
                "retry_count": 0,
                "created_at": now,
            },
        },
        upsert=True,
    )
    return True


async def _backfill_existing_announcement_types(dry_run: bool) -> int:
    """Backfill generic announcement_type values for rows that already have file_path."""
    async with engine.connect() as conn:
        rows = (
            (
                await conn.execute(
                    text(
                        """
                    SELECT cninfo_id, title, file_path
                    FROM announcements
                    WHERE file_path IS NOT NULL
                      AND file_path <> ''
                      AND (announcement_type IS NULL OR announcement_type IN ('disclosure', 'other', 'unknown'))
                    """
                    )
                )
            )
            .mappings()
            .all()
        )

    updates: list[dict[str, str]] = []
    for row in rows:
        title = str(row["title"] or "")
        if not title and row["file_path"]:
            title = Path(str(row["file_path"])).stem
        doc_type, _ = classify_title(title)
        if doc_type not in {"unknown", "other"}:
            updates.append({"cninfo_id": str(row["cninfo_id"]), "doc_type": doc_type})

    if dry_run or not updates:
        return len(updates)

    async with engine.begin() as conn:
        for item in updates:
            await conn.execute(
                text(
                    """
                    UPDATE announcements
                    SET announcement_type = :doc_type
                    WHERE cninfo_id = :cninfo_id
                      AND (announcement_type IS NULL OR announcement_type IN ('disclosure', 'other', 'unknown'))
                    """
                ),
                item,
            )
    return len(updates)


async def repair(limit: int | None, include_all: bool, dry_run: bool, process_kg_limit: int) -> dict[str, int]:
    tracker = IngestionProgressTracker(source="cninfo", task_name="p1_notice_kg_inputs", scope="storage_notices")
    ctx = await tracker.start_run(metadata={"limit": limit, "include_all": include_all, "dry_run": dry_run})
    files = _iter_notice_pdfs(limit)
    counters = {
        "total": len(files),
        "matched": 0,
        "postgres_updated": 0,
        "kg_indexed": 0,
        "skipped": 0,
        "fail": 0,
    }

    for idx, path in enumerate(files, start=1):
        parsed = _parse_path(path)
        doc_type, action = classify_title(parsed["title"])
        if not include_all and doc_type not in HIGH_VALUE_DOC_TYPES:
            counters["skipped"] += 1
            continue
        try:
            announcement = await _find_announcement(path, parsed)
            if not announcement:
                counters["skipped"] += 1
                await tracker.event(
                    ctx,
                    stage="not_matched",
                    message="本地公告 PDF 未匹配到 announcements 记录",
                    total_items=len(files),
                    processed_items=idx,
                    item_id=parsed["ts_code"],
                    item_title=parsed["title"],
                    metadata={"file_path": str(path), "doc_type": doc_type},
                )
                continue
            counters["matched"] += 1
            ann_doc_type, _ = classify_title(str(announcement.get("title") or parsed["title"]))
            if ann_doc_type in {"unknown", "other"}:
                ann_doc_type = doc_type
            if await _update_postgres_file_path(str(announcement["cninfo_id"]), path, ann_doc_type, dry_run):
                counters["postgres_updated"] += 1
            if await _upsert_kg_file_index(path, announcement, ann_doc_type, dry_run):
                counters["kg_indexed"] += 1
        except Exception as exc:  # noqa: BLE001
            counters["fail"] += 1
            await tracker.event(
                ctx,
                stage="item_error",
                message="公告 PDF 修复失败",
                total_items=len(files),
                processed_items=idx,
                item_title=path.name,
                error=str(exc),
            )

        if idx % 100 == 0 or idx == len(files):
            await tracker.update_run(
                ctx,
                total_items=len(files),
                processed_items=idx,
                success_count=counters["kg_indexed"],
                skipped_count=counters["skipped"],
                fail_count=counters["fail"],
                last_item_id=path.name[:100],
            )
            await tracker.event(
                ctx,
                stage="progress",
                message="P1 公告 PDF 修复进展",
                total_items=len(files),
                processed_items=idx,
                success_count=counters["kg_indexed"],
                skipped_count=counters["skipped"],
                fail_count=counters["fail"],
                metadata=counters,
            )

    if process_kg_limit > 0 and not dry_run:
        old_batch_size = None
        try:
            import scripts.kg_extraction_pipeline as kgp

            old_batch_size = kgp.BATCH_SIZE
            kgp.BATCH_SIZE = process_kg_limit
            kg_stats = await KGPipeline().run_once(limit=process_kg_limit)
            counters["kg_processed"] = int(kg_stats.get("total", 0) or 0)
            counters["kg_success"] = int(kg_stats.get("success", 0) or 0)
            counters["kg_failed"] = int(kg_stats.get("failed", 0) or 0)
            counters["kg_skipped"] = int(kg_stats.get("skipped", 0) or 0)
        finally:
            if old_batch_size is not None:
                kgp.BATCH_SIZE = old_batch_size

    counters["announcement_type_backfilled"] = await _backfill_existing_announcement_types(dry_run)

    status = FAILED if counters["fail"] and not counters["kg_indexed"] else (PARTIAL if counters["fail"] else SUCCESS)
    await tracker.finish_run(
        ctx,
        status=status,
        total_items=len(files),
        processed_items=len(files),
        success_count=counters["kg_indexed"],
        skipped_count=counters["skipped"],
        downloaded_count=0,
        fail_count=counters["fail"],
        metadata=counters,
    )
    return counters


def main() -> None:
    parser = argparse.ArgumentParser(description="P1 repair notice PDF KG inputs")
    parser.add_argument("--limit", type=int, default=1000, help="max local PDFs to scan; 0 means all")
    parser.add_argument(
        "--include-all",
        action="store_true",
        help="index all notice PDFs, not only high-value titles",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--process-kg-limit",
        type=int,
        default=0,
        help="optionally process this many pending KG files after repair",
    )
    args = parser.parse_args()
    limit = None if args.limit == 0 else args.limit
    result = asyncio.run(repair(limit, args.include_all, args.dry_run, args.process_kg_limit))
    logger.info("P1_RESULT %s", result)


if __name__ == "__main__":
    main()
