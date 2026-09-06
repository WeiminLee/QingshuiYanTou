"""Async worker that consumes Evidence extraction jobs."""

from __future__ import annotations

import asyncio
import logging
import socket
import time
from typing import Any

from app.knowledge.evidence import JOB_COMBINED, JOB_SIGNAL, JOB_VECTOR
from app.knowledge.evidence_service import EvidenceService
from app.knowledge.extraction.irm_classifier import classify_irm_evidence, extraction_tier
from app.knowledge.kg_extractor import extract_evidence_async
from app.knowledge.vector_client import upsert_evidence_chunk_vector
from app.signals.auto_ingestion import ingest_evidence_signals

logger = logging.getLogger(__name__)


class EvidenceExtractionWorker:
    def __init__(
        self,
        service: EvidenceService | None = None,
        worker_id: str | None = None,
        batch_size: int = 5,
        max_concurrency: int = 5,
    ):
        if service is None:
            import os
            if os.getenv("KNOWLEDGE_API_URL") and os.getenv("KNOWLEDGE_API_KEY"):
                from app.knowledge.remote_evidence_service import RemoteEvidenceService
                service = RemoteEvidenceService(os.environ["KNOWLEDGE_API_URL"], os.environ["KNOWLEDGE_API_KEY"])
            else:
                service = EvidenceService()
        self.service = service
        self.worker_id = worker_id or f"worker-{socket.gethostname()}-{int(time.time())}"
        self.batch_size = batch_size
        self.max_concurrency = max_concurrency

    async def run_once(self, limit: int | None = None, job_type: str = "combined") -> dict[str, int]:
        if limit is not None and limit <= 0:
            return {"claimed": 0, "success": 0, "failed": 0, "skipped": 0, "job_type": job_type}

        claimed = 0
        success = 0
        failed = 0
        skipped = 0
        counter_lock = asyncio.Lock()

        def _bump(status: str) -> None:
            nonlocal success, failed, skipped
            if status == "done":
                success += 1
            elif status == "skipped":
                skipped += 1
            else:
                failed += 1

        async def _worker_slot() -> None:
            """滑动窗口 slot：领一个、跑一个、立刻领下一个，不再等整批。"""
            nonlocal claimed
            while True:
                async with counter_lock:
                    if limit is not None and claimed >= limit:
                        return
                    claimed += 1  # 预留额度，保证不超过 limit
                job = await self.service.claim_next_job(job_type=job_type, worker_id=self.worker_id)
                if not job:
                    async with counter_lock:
                        claimed -= 1  # 无 job 可领，退还额度
                    return
                try:
                    res = await self.process_job(job)
                except Exception as exc:  # noqa: BLE001  # process_job 已自捕获，此处兜底
                    res = exc
                if isinstance(res, Exception):
                    logger.warning("Evidence job failed unexpectedly [%s]: %s", job.get("job_id"), res)
                    status = "failed"
                else:
                    status = str(res.get("status", "failed"))
                async with counter_lock:
                    _bump(status)

        await asyncio.gather(*[_worker_slot() for _ in range(self.max_concurrency)])
        return {
            "claimed": claimed,
            "success": success,
            "failed": failed,
            "skipped": skipped,
            "job_type": job_type,
        }

    async def run_loop(
        self,
        interval_seconds: int = 30,
        limit_per_loop: int | None = None,
        job_type: str = "combined",
    ) -> None:
        while True:
            result = await self.run_once(limit=limit_per_loop, job_type=job_type)
            logger.info("Evidence worker loop: %s", result)
            await asyncio.sleep(interval_seconds)

    async def process_job(self, job: dict[str, Any]) -> dict[str, Any]:
        evidence_id = str(job.get("evidence_id") or "")
        job_id = str(job.get("job_id") or "")
        job_type = str(job.get("job_type") or "combined")
        evidence = await self.service.get_evidence(evidence_id)
        if not evidence:
            await self.service.mark_job_failed(job_id, "Evidence not found")
            return {"status": "failed", "error": "Evidence not found"}

        heartbeat_task = asyncio.create_task(self._heartbeat(job_id))
        try:
            if job_type == JOB_COMBINED:
                if evidence.get("source_type") == "irm":
                    category = classify_irm_evidence(evidence)
                    tier = extraction_tier(category)
                    if tier == 0:
                        await self.service.mark_job_skipped(
                            job_id, f"IRM classified as '{category}'; no KG extraction"
                        )
                        return {"status": "skipped", "reason": category}
                # Remote workers write KG through the cloud API; local fallback keeps legacy path.
                import os
                if os.getenv("KNOWLEDGE_API_URL") and os.getenv("KNOWLEDGE_API_KEY"):
                    import httpx
                    async with httpx.AsyncClient(timeout=180) as client:
                        resp = await client.post(
                            os.environ["KNOWLEDGE_API_URL"].rstrip("/") + "/api/v1/knowledge/kg/extract/text",
                            headers={"X-API-Key": os.environ["KNOWLEDGE_API_KEY"]},
                            json={"text": evidence.get("text_excerpt", ""), "ts_code": (evidence.get("subject_hint") or {}).get("ts_code") or "UNKNOWN", "source_name": evidence.get("source_name", "evidence"), "source_type": evidence.get("source_type", "announcement"), "article_ref": evidence_id},
                        )
                        resp.raise_for_status(); result = resp.json()
                else:
                    result = await extract_evidence_async(evidence)
                await self.service.mark_job_done(job_id, result)
                return {"status": "done", **result}
            if job_type == JOB_VECTOR:
                ok = upsert_evidence_chunk_vector(evidence)
                result = {"vector_ok": ok}
                if ok:
                    await self.service.mark_job_done(job_id, result)
                    return {"status": "done", **result}
                await self.service.mark_job_failed(job_id, "vector upsert failed")
                return {"status": "failed", **result}
            if job_type == JOB_SIGNAL:
                result = await ingest_evidence_signals(evidence)
                await self.service.mark_job_done(job_id, result)
                return {"status": "done", **result}
            await self.service.mark_job_failed(job_id, f"unsupported job_type: {job_type}")
            return {"status": "failed", "error": f"unsupported job_type: {job_type}"}
        except Exception as exc:  # noqa: BLE001
            await self.service.mark_job_failed(job_id, str(exc))
            return {"status": "failed", "error": str(exc)}
        finally:
            heartbeat_task.cancel()
            await asyncio.gather(heartbeat_task, return_exceptions=True)

    async def _heartbeat(self, job_id: str) -> None:
        """Keep a long-running claim alive; silently stop on service errors."""
        while True:
            await asyncio.sleep(60)
            try:
                owned = await self.service.heartbeat_job(job_id, self.worker_id)
                if not owned:
                    logger.warning("Evidence job lock ownership lost [%s]", job_id)
                    return
            except Exception as exc:  # noqa: BLE001
                logger.warning("Evidence job heartbeat failed [%s]: %s", job_id, exc)
