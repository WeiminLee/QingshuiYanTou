"""IRM Q&A knowledge extraction for Schema V4."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from app.core.metadata import CURRENT_KG_PARSER_VERSION, CURRENT_KG_SCHEMA_VERSION
from app.core.mongodb import get_mongo_db
from app.knowledge.evidence_builders import build_irm_evidence_batch
from app.knowledge.evidence_service import EvidenceService

logger = logging.getLogger(__name__)

ProgressCallback = Callable[..., Awaitable[None]]
# Bug-5 修复：checkpoint 集合名与 fetcher.py 保持一致（"irm_checkpoint"）
IRM_CHECKPOINT_COLLECTION = "irm_checkpoint"
IRM_KG_SCHEMA_VERSION = CURRENT_KG_SCHEMA_VERSION
IRM_KG_PARSER_VERSION = CURRENT_KG_PARSER_VERSION
_IRM_KG_INDEXES_READY = False


def _utc_now() -> datetime:
    return datetime.now(UTC)


async def _emit(progress_callback: ProgressCallback | None, stage: str, message: str, **kwargs: Any) -> None:
    if progress_callback is None:
        return
    try:
        await progress_callback(stage=stage, message=message, **kwargs)
    except Exception as exc:  # noqa: BLE001
        logger.debug("IRM progress callback failed [%s]: %s", stage, exc)


def _irm_record_key(rec: dict[str, Any]) -> str:
    cninfo_id = str(rec.get("cninfo_id") or "").strip()
    if cninfo_id:
        return cninfo_id
    ts_code = str(rec.get("ts_code") or "").strip()
    content_hash = _irm_content_hash(rec)
    return f"{ts_code}:{content_hash[:20]}" if ts_code else content_hash[:24]


def _irm_content_hash(rec: dict[str, Any]) -> str:
    payload = "\n".join(
        [
            str(rec.get("ts_code") or ""),
            str(rec.get("company_name") or rec.get("name") or ""),
            str(rec.get("question") or rec.get("title") or ""),
            str(rec.get("answer") or rec.get("type") or ""),
            str(rec.get("ann_date") or ""),
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def _irm_checkpoint_col():
    global _IRM_KG_INDEXES_READY
    if _IRM_KG_INDEXES_READY:
        return get_mongo_db()[IRM_CHECKPOINT_COLLECTION]
    db = get_mongo_db()
    col = db[IRM_CHECKPOINT_COLLECTION]
    try:
        await col.create_index("record_key", unique=True, sparse=True)
    except Exception:  # index may already exist
        pass
    try:
        await col.create_index("cninfo_id")
    except Exception:
        pass
    try:
        await col.create_index("ts_code")
    except Exception:
        pass
    try:
        await col.create_index("status")
    except Exception:
        pass
    try:
        await col.create_index("updated_at")
    except Exception:
        pass
    _IRM_KG_INDEXES_READY = True
    return col


async def _get_done_checkpoint(record_key: str, content_hash: str) -> dict[str, Any] | None:
    col = await _irm_checkpoint_col()
    doc = await col.find_one(
        {
            "record_key": record_key,
            "content_hash": content_hash,
            "status": "done",
            "schema_version": IRM_KG_SCHEMA_VERSION,
            "parser_version": IRM_KG_PARSER_VERSION,
        },
        {"_id": 0},
    )
    return dict(doc) if doc else None


async def _mark_irm_running(rec: dict[str, Any], record_key: str, content_hash: str) -> None:
    col = await _irm_checkpoint_col()
    now = _utc_now()
    await col.update_one(
        {"record_key": record_key},
        {
            "$set": {
                "cninfo_id": str(rec.get("cninfo_id") or ""),
                "ts_code": str(rec.get("ts_code") or ""),
                "company_name": str(rec.get("company_name") or rec.get("name") or ""),
                "question": str(rec.get("question") or rec.get("title") or "")[:500],
                "content_hash": content_hash,
                "status": "running",
                "schema_version": IRM_KG_SCHEMA_VERSION,
                "parser_version": IRM_KG_PARSER_VERSION,
                "updated_at": now,
            },
            "$setOnInsert": {"created_at": now, "retry_count": 0},
        },
        upsert=True,
    )


async def _mark_irm_done(record_key: str, result: dict[str, Any]) -> None:
    col = await _irm_checkpoint_col()
    await col.update_one(
        {"record_key": record_key},
        {
            "$set": {
                "status": "done",
                "result": result,
                "entities_count": int(result.get("entities_created", 0) or 0)
                + int(result.get("entities_updated", 0) or 0),
                "relations_count": int(result.get("relations_created", 0) or 0)
                + int(result.get("relations_updated", 0) or 0),
                "qa_vector_ok": bool(result.get("qa_vector_ok")),
                "entity_vectors_ok": int(result.get("entity_vectors_ok", 0) or 0),
                "relation_vectors_ok": int(result.get("relation_vectors_ok", 0) or 0),
                "error": None,
                "finished_at": _utc_now(),
                "updated_at": _utc_now(),
            }
        },
    )


async def _mark_irm_failed(record_key: str, error: str) -> None:
    col = await _irm_checkpoint_col()
    await col.update_one(
        {"record_key": record_key},
        {
            "$set": {
                "status": "failed",
                "error": error[:1000],
                "updated_at": _utc_now(),
            },
            "$inc": {"retry_count": 1},
        },
    )


async def create_irm_evidence_jobs(
    records: list[dict[str, Any]],
    progress_callback: ProgressCallback | None = None,
) -> dict[str, int]:
    """Create Evidence-first jobs for IRM records (按 ts_code+ann_date 聚合后构建)."""
    service = EvidenceService()
    totals = {"records": len(records), "evidence": 0, "jobs": 0, "fail": 0, "skipped": 0}
    # 批量构建（聚合+去重）
    all_inputs = build_irm_evidence_batch(records)
    totals["evidence"] = len(all_inputs)
    written = await service.bulk_upsert_evidence(all_inputs)
    totals["evidence"] = written
    # 批量收集 evidence_ids 然后入队
    evidence_ids = []
    for inp in all_inputs:
        from app.knowledge.evidence import stable_evidence_id
        eid = stable_evidence_id(inp.source_type, inp.source_id, 0, inp.text_excerpt)
        evidence_ids.append(eid)
    evidence_ids = list(set(evidence_ids))
    enqueued = await service.bulk_enqueue_jobs(evidence_ids)
    totals["jobs"] = enqueued
    await _emit(
        progress_callback,
        "irm_evidence_created",
        "互动易 Evidence 批量创建完成",
        metadata={"evidence": written, "jobs": enqueued, "fail": totals["fail"]},
    )
    return totals
