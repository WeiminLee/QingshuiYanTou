"""Mongo-backed Evidence and extraction job service."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from pymongo import ReturnDocument, UpdateOne

from app.core.mongodb import get_mongo_db
from app.knowledge.evidence import (
    EVIDENCE_COLLECTION,
    EXTRACTION_JOBS_COLLECTION,
    EXTRACTOR_VERSION,
    JOB_COMBINED,
    JOB_VECTOR,
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_RUNNING,
    EvidenceInput,
    default_source_confidence,
    stable_evidence_id,
    stable_job_id,
    text_checksum,
)

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class EvidenceService:
    """Async repository for Evidence and extraction jobs."""

    def __init__(self, db: Any | None = None):
        self._db = db or get_mongo_db()
        self._evidence = self._db[EVIDENCE_COLLECTION]
        self._jobs = self._db[EXTRACTION_JOBS_COLLECTION]

    async def ensure_indexes(self) -> None:
        await self._evidence.create_index("evidence_id", unique=True)
        await self._evidence.create_index("checksum")
        await self._evidence.create_index("source_type")
        await self._evidence.create_index("subject_hint.ts_code")
        await self._evidence.create_index("publish_date")

        await self._jobs.create_index("job_id", unique=True)
        await self._jobs.create_index("evidence_id")
        await self._jobs.create_index("status")
        await self._jobs.create_index("job_type")
        await self._jobs.create_index("updated_at")

    async def upsert_evidence(self, input: EvidenceInput, chunk_index: int = 0) -> dict[str, Any]:
        await self.ensure_indexes()
        now = _utc_now()
        text = input.text_excerpt or ""
        evidence_id = stable_evidence_id(input.source_type, input.source_id, chunk_index, text)
        checksum = text_checksum(text)
        confidence = input.confidence
        if confidence is None:
            confidence = default_source_confidence(input.source_type)
        source_ref = dict(input.source_ref or {})
        source_ref.setdefault("chunk_index", chunk_index)

        existing = await self._evidence.find_one({"evidence_id": evidence_id}, {"_id": 0})
        if existing and not text.strip():
            return dict(existing)

        doc = {
            "evidence_id": evidence_id,
            "source_type": input.source_type,
            "source_name": input.source_name,
            "source_id": input.source_id,
            "subject_hint": dict(input.subject_hint or {}),
            "publish_date": input.publish_date,
            "observed_at": input.observed_at or now,
            "text_excerpt": text,
            "source_ref": source_ref,
            "checksum": checksum,
            "confidence": float(confidence),
            "metadata": dict(input.metadata or {}),
            "updated_at": now,
        }
        set_on_insert = {
            "created_at": now,
            "extraction_status": {
                JOB_COMBINED: STATUS_PENDING,
                JOB_VECTOR: STATUS_PENDING,
                "last_extracted_at": None,
                "extractor_version": EXTRACTOR_VERSION,
            },
        }
        await self._evidence.update_one(
            {"evidence_id": evidence_id},
            {"$set": doc, "$setOnInsert": set_on_insert},
            upsert=True,
        )
        saved = await self.get_evidence(evidence_id)
        return saved or {**set_on_insert, **doc}

    async def get_evidence(self, evidence_id: str) -> dict[str, Any] | None:
        doc = await self._evidence.find_one({"evidence_id": evidence_id}, {"_id": 0})
        return dict(doc) if doc else None

    async def enqueue_job(
        self,
        evidence_id: str,
        job_type: str,
        extractor_version: str = EXTRACTOR_VERSION,
    ) -> dict[str, Any]:
        await self.ensure_indexes()
        now = _utc_now()
        job_id = stable_job_id(evidence_id, job_type, extractor_version)
        doc = {
            "job_id": job_id,
            "evidence_id": evidence_id,
            "job_type": job_type,
            "status": STATUS_PENDING,
            "retry_count": 0,
            "error": None,
            "extractor_version": extractor_version,
            "locked_by": None,
            "locked_at": None,
            "started_at": None,
            "finished_at": None,
            "created_at": now,
            "updated_at": now,
        }
        await self._jobs.update_one(
            {"job_id": job_id},
            {"$setOnInsert": doc},
            upsert=True,
        )
        saved = await self._jobs.find_one({"job_id": job_id}, {"_id": 0})
        return dict(saved) if saved else doc

    async def enqueue_default_jobs(self, evidence_id: str) -> list[dict[str, Any]]:
        return [
            await self.enqueue_job(evidence_id, JOB_COMBINED),
            await self.enqueue_job(evidence_id, JOB_VECTOR),
        ]

    # ── 批量写入 ────────────────────────────────────────────────

    async def bulk_upsert_evidence(self, inputs: list[EvidenceInput]) -> int:
        """批量 upsert Evidence 记录（高并发优化）

        注意: build_announcement_evidence 已经将每个 chunk 拆分为独立的 EvidenceInput，
        所以这里直接处理每个 input 即可。
        """
        if not inputs:
            return 0
        await self.ensure_indexes()
        now = _utc_now()
        operations = []
        for input in inputs:
            # 每个 EvidenceInput 代表一个 chunk
            evidence_id = stable_evidence_id(input.source_type, input.source_id, 0, input.text_excerpt)
            checksum = text_checksum(input.text_excerpt)
            confidence = input.confidence or default_source_confidence(input.source_type)
            source_ref = dict(input.source_ref or {})
            source_ref.setdefault("chunk_index", 0)
            doc = {
                "evidence_id": evidence_id,
                "source_type": input.source_type,
                "source_name": input.source_name,
                "source_id": input.source_id,
                "subject_hint": dict(input.subject_hint or {}),
                "publish_date": input.publish_date,
                "observed_at": input.observed_at or now,
                "text_excerpt": input.text_excerpt,
                "source_ref": source_ref,
                "checksum": checksum,
                "confidence": float(confidence),
                "metadata": dict(input.metadata or {}),
                "updated_at": now,
            }
            set_on_insert = {
                "created_at": now,
                "extraction_status": {
                    JOB_COMBINED: STATUS_PENDING,
                    JOB_VECTOR: STATUS_PENDING,
                    "last_extracted_at": None,
                    "extractor_version": EXTRACTOR_VERSION,
                },
            }
            operations.append(
                UpdateOne(
                    {"evidence_id": evidence_id},
                    {"$set": doc, "$setOnInsert": set_on_insert},
                    upsert=True,
                )
            )
        if operations:
            result = await self._evidence.bulk_write(operations, ordered=False)
            return result.upserted_count + result.modified_count
        return 0

    async def bulk_enqueue_jobs(self, evidence_ids: list[str]) -> int:
        """批量 enqueue extraction jobs（高并发优化）"""
        if not evidence_ids:
            return 0
        await self.ensure_indexes()
        now = _utc_now()
        operations = []
        for evidence_id in evidence_ids:
            for job_type in [JOB_COMBINED, JOB_VECTOR]:
                job_id = stable_job_id(evidence_id, job_type, EXTRACTOR_VERSION)
                doc = {
                    "job_id": job_id,
                    "evidence_id": evidence_id,
                    "job_type": job_type,
                    "status": STATUS_PENDING,
                    "retry_count": 0,
                    "error": None,
                    "extractor_version": EXTRACTOR_VERSION,
                    "locked_by": None,
                    "locked_at": None,
                    "started_at": None,
                    "finished_at": None,
                    "created_at": now,
                    "updated_at": now,
                }
                operations.append(
                    UpdateOne(
                        {"job_id": job_id},
                        {"$setOnInsert": doc},
                        upsert=True,
                    )
                )
        if operations:
            result = await self._jobs.bulk_write(operations, ordered=False)
            return result.upserted_count
        return 0

    async def claim_next_job(
        self,
        job_type: str | None = None,
        worker_id: str = "",
        stale_after_minutes: int = 30,
    ) -> dict[str, Any] | None:
        await self.ensure_indexes()
        now = _utc_now()
        stale_cutoff = now - timedelta(minutes=stale_after_minutes)
        query: dict[str, Any] = {
            "$or": [
                {"status": STATUS_PENDING},
                {"status": STATUS_RUNNING, "locked_at": {"$lt": stale_cutoff}},
            ]
        }
        if job_type:
            query["job_type"] = job_type

        doc = await self._jobs.find_one_and_update(
            query,
            {
                "$set": {
                    "status": STATUS_RUNNING,
                    "locked_by": worker_id,
                    "locked_at": now,
                    "started_at": now,
                    "updated_at": now,
                    "error": None,
                }
            },
            sort=[("created_at", 1)],
            return_document=ReturnDocument.AFTER,
            projection={"_id": 0},
        )
        return dict(doc) if doc else None

    async def mark_job_done(self, job_id: str, result: dict | None = None) -> None:
        now = _utc_now()
        doc = await self._jobs.find_one({"job_id": job_id}, {"_id": 0})
        await self._jobs.update_one(
            {"job_id": job_id},
            {
                "$set": {
                    "status": STATUS_DONE,
                    "result": result or {},
                    "error": None,
                    "finished_at": now,
                    "updated_at": now,
                }
            },
        )
        if doc:
            await self.update_evidence_status(
                doc["evidence_id"],
                doc["job_type"],
                STATUS_DONE,
                doc.get("extractor_version") or EXTRACTOR_VERSION,
            )

    async def mark_job_failed(self, job_id: str, error: str, max_retries: int = 3) -> None:
        now = _utc_now()
        doc = await self._jobs.find_one({"job_id": job_id}, {"_id": 0})
        retry_count = int((doc or {}).get("retry_count") or 0) + 1
        status = STATUS_FAILED if retry_count >= max_retries else STATUS_PENDING
        await self._jobs.update_one(
            {"job_id": job_id},
            {
                "$set": {
                    "status": status,
                    "error": error[:1000],
                    "retry_count": retry_count,
                    "locked_by": None,
                    "locked_at": None,
                    "finished_at": now if status == STATUS_FAILED else None,
                    "updated_at": now,
                }
            },
        )
        if doc:
            await self.update_evidence_status(
                doc["evidence_id"],
                doc["job_type"],
                status,
                doc.get("extractor_version") or EXTRACTOR_VERSION,
            )

    async def update_evidence_status(
        self,
        evidence_id: str,
        job_type: str,
        status: str,
        extractor_version: str = EXTRACTOR_VERSION,
    ) -> None:
        now = _utc_now()
        update = {
            f"extraction_status.{job_type}": status,
            "extraction_status.extractor_version": extractor_version,
            "updated_at": now,
        }
        if status == STATUS_DONE:
            update["extraction_status.last_extracted_at"] = now
        await self._evidence.update_one({"evidence_id": evidence_id}, {"$set": update})

    async def heal_running_jobs(self, older_than_minutes: int = 30) -> int:
        now = _utc_now()
        cutoff = now - timedelta(minutes=older_than_minutes)
        result = await self._jobs.update_many(
            {"status": STATUS_RUNNING, "locked_at": {"$lt": cutoff}},
            {
                "$set": {
                    "status": STATUS_PENDING,
                    "locked_by": None,
                    "locked_at": None,
                    "error": "stale running job reset",
                    "updated_at": now,
                }
            },
        )
        return int(getattr(result, "modified_count", 0))

    async def get_stats(self) -> dict[str, Any]:
        evidence_count = await self._evidence.count_documents({})
        jobs_total = await self._jobs.count_documents({})
        by_status: dict[str, int] = {}
        async for row in self._jobs.aggregate(
            [
                {"$group": {"_id": "$status", "count": {"$sum": 1}}},
            ]
        ):
            by_status[str(row["_id"])] = int(row["count"])
        return {
            "evidence": evidence_count,
            "jobs": jobs_total,
            "jobs_by_status": by_status,
            "pending": by_status.get(STATUS_PENDING, 0),
            "running": by_status.get(STATUS_RUNNING, 0),
            "done": by_status.get(STATUS_DONE, 0),
            "failed": by_status.get(STATUS_FAILED, 0),
        }
