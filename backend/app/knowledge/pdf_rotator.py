"""Two-year local PDF rotation while retaining KG entities."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.core.mongodb import get_mongo_db
from app.core.neo4j_client import run_write
from app.knowledge.file_indexer import FileIndexer

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


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


def _mark_neo4j_pdf_rotated(cninfo_id: str, file_path: str) -> None:
    try:
        run_write(
            """
            MATCH (n)
            WHERE n.evidence_url = $file_path OR n.source_document_id = $cninfo_id
            SET n.evidence_url = $marker, n.pdf_rotated_at = $rotated_at
            """,
            {
                "file_path": file_path,
                "cninfo_id": cninfo_id,
                "marker": f"PDF rotated: {cninfo_id}",
                "rotated_at": _utc_now().isoformat(),
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("Neo4j PDF rotated marker skipped [%s]: %s", cninfo_id, exc)


async def rotate_old_pdfs(days_threshold: int = 730, dry_run: bool = False) -> dict[str, int]:
    """Delete local PDFs older than the threshold; retain Mongo/Neo4j metadata."""
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
                        {"$set": {
                            "file_path": None,
                            "status": "rotated",
                            "rotated_at": _utc_now(),
                            "updated_at": _utc_now(),
                        }},
                    )
                    cleared = True
                _mark_neo4j_pdf_rotated(cninfo_id, file_path)
                stats["cleared"] += int(cleared)
        except Exception as exc:  # noqa: BLE001
            stats["failed"] += 1
            logger.warning("PDF rotation failed [%s]: %s", file_path, exc)
    return stats
