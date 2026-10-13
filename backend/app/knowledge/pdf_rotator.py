"""Two-year local PDF rotation while retaining KG entities."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.core.mongodb import get_mongo_db
from app.knowledge.file_indexer import FileIndexer

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(UTC)


async def get_files_older_than(cutoff_date: datetime, limit: int = 1000) -> list[dict[str, Any]]:
    db = get_mongo_db()
    indexer = FileIndexer(db)
    await indexer.ensure_indexes()
    return await indexer.find_files_older_than(cutoff_date, limit=limit)


async def get_rotation_stats(days_threshold: int = 730) -> dict[str, int | float]:
    cutoff = _utc_now() - timedelta(days=days_threshold)
    files = await get_files_older_than(cutoff)
    total_size = 0
    existing = 0
    missing = 0
    for doc in files:
        path = Path(str(doc.get("file_path") or ""))
        size = int(doc.get("file_size") or 0)
        if path.exists():
            existing += 1
            total_size += size or path.stat().st_size
        else:
            missing += 1
    return {
        "eligible": len(files),
        "existing": existing,
        "missing": missing,
        "size_mb": round(total_size / 1024 / 1024, 2),
    }


async def rotate_old_pdfs(days_threshold: int = 730, dry_run: bool = False) -> dict[str, int]:
    """Delete local PDFs older than the threshold; retain Mongo metadata."""
    cutoff = _utc_now() - timedelta(days=days_threshold)
    files = await get_files_older_than(cutoff)
    db = get_mongo_db()
    indexer = FileIndexer(db)

    stats = {"checked": 0, "deleted": 0, "missing": 0, "cleared": 0, "failed": 0}
    for doc in files:
        stats["checked"] += 1
        file_path = str(doc.get("file_path") or "")
        cninfo_id = str(doc.get("cninfo_id") or doc.get("file_name") or file_path)
        path = Path(file_path)
        try:
            if path.exists():
                if not dry_run:
                    path.unlink()
                stats["deleted"] += 1
            else:
                stats["missing"] += 1

            if not dry_run:
                cleared = await indexer.clear_file_path(cninfo_id)
                if not cleared and file_path:
                    await db[indexer.COLLECTION].update_one(
                        {"file_path": file_path},
                        {
                            "$set": {
                                "file_path": None,
                                "status": "rotated",
                                "rotated_at": _utc_now(),
                                "updated_at": _utc_now(),
                            }
                        },
                    )
                    cleared = True
                stats["cleared"] += int(cleared)
        except Exception as exc:  # noqa: BLE001
            stats["failed"] += 1
            logger.warning("PDF rotation failed [%s]: %s", file_path, exc)
    return stats
