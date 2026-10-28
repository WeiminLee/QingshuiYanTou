"""Document-level AI summaries, stored separately from evidence.

Summaries are additive: a missing summary never blocks the document view.
The collection is keyed by the same ``ann_id`` shapes as
``document_service.ann_id_variants`` (PG int for old rows, composite string
for PDF-worker rows).
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.knowledge.document_service import ann_id_variants

SUMMARY_COLLECTION = "kg_document_summaries"


async def ensure_summary_indexes(db: Any) -> None:
    await db[SUMMARY_COLLECTION].create_index("ann_id", unique=True)


async def get_document_summary(db: Any, ann_id: str) -> dict[str, Any] | None:
    """Return the stored summary for one document, or ``None``."""
    doc = await db[SUMMARY_COLLECTION].find_one(
        {"ann_id": {"$in": ann_id_variants(ann_id)}}
    )
    if not doc:
        return None
    summary = doc.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        return None
    updated = doc.get("updated_at")
    return {
        "summary": summary.strip(),
        "updated_at": updated.isoformat() if hasattr(updated, "isoformat") else None,
        "model": doc.get("model"),
    }


async def save_document_summary(
    db: Any,
    *,
    ann_id: Any,
    title: str | None,
    ts_code: str | None,
    publish_date: str | None,
    summary: str,
    model: str,
    text_sha: str,
) -> None:
    await db[SUMMARY_COLLECTION].update_one(
        {"ann_id": ann_id},
        {
            "$set": {
                "ann_id": ann_id,
                "title": title,
                "ts_code": ts_code,
                "publish_date": publish_date,
                "summary": summary,
                "model": model,
                "text_sha": text_sha,
                "updated_at": datetime.now(UTC),
            }
        },
        upsert=True,
    )
