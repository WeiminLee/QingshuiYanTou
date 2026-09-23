"""Async worker that consumes Evidence extraction jobs."""

from __future__ import annotations

import asyncio
import logging
import socket
import time
from typing import Any

from app.core.database import async_session
from app.knowledge.evidence import JOB_COMBINED, JOB_LINK, JOB_SIGNAL, JOB_VECTOR
from app.knowledge.evidence_service import EvidenceService
from app.knowledge.extraction.irm_classifier import classify_irm_evidence, extraction_tier
from app.knowledge.kg_extractor import extract_evidence_async, extract_evidence_raw
from app.knowledge.linklayer.candidates import emit_radar_signals, generate_candidates, persist_candidates
from app.knowledge.linklayer.ingest import compute_link_actions, ingest_evidence
from app.knowledge.vector_client import build_evidence_vector_record, upsert_evidence_chunk_vector
from app.knowledge.worker_api_client import KnowledgeApiClient
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
                try:
                    job = await self.service.claim_next_job(job_type=job_type, worker_id=self.worker_id)
                except Exception as exc:  # noqa: BLE001  网络/网关抖动不应打崩进程，也不应让 slot 退出
                    logger.warning("Evidence job claim 失败，3s 后重试（保持 slot）: %s", exc)
                    await asyncio.sleep(3)
                    continue
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
            try:
                result = await self.run_once(limit=limit_per_loop, job_type=job_type)
                logger.info("Evidence worker loop: %s", result)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001  单轮异常不应终止常驻 worker
                logger.warning("Evidence worker loop 异常，%ss 后继续: %s", interval_seconds, exc)
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
                # Remote workers: LLM 抽取在 worker 本地，云端只做知识图谱入库（/kg/ingest）。
                # 本地一体（无 KNOWLEDGE_API_URL）走 legacy 路径。
                import os
                if os.getenv("KNOWLEDGE_API_URL") and os.getenv("KNOWLEDGE_API_KEY"):
                    extracted = await extract_evidence_raw(evidence)
                    if extracted["status"] == "empty":
                        result = {
                            "entities_created": 0, "entities_updated": 0,
                            "relations_created": 0, "relations_updated": 0,
                            "chunks_processed": 0,
                            "evidence_id": evidence.get("evidence_id"),
                            "entities_raw": [], "relations_raw": [],
                        }
                    elif extracted["status"] == "cached":
                        cached = extracted["cached"]
                        result = {
                            "entities_created": 0,
                            "entities_updated": len(cached.get("entities", [])),
                            "relations_created": 0,
                            "relations_updated": len(cached.get("relations", [])),
                            "chunks_processed": 1,
                            "evidence_id": extracted["evidence_id"],
                            "entities": cached.get("entities", []),
                            "relations": cached.get("relations", []),
                            "signals": cached.get("signals", []),
                            "from_cache": True,
                        }
                    else:
                        import httpx
                        async with httpx.AsyncClient(timeout=180) as client:
                            resp = await client.post(
                                os.environ["KNOWLEDGE_API_URL"].rstrip("/") + "/api/v1/knowledge/kg/ingest",
                                headers={"X-API-Key": os.environ["KNOWLEDGE_API_KEY"]},
                                json={
                                    "evidence": evidence,
                                    "entities_raw": extracted.get("entities_raw", []),
                                    "relations_raw": extracted.get("relations_raw", []),
                                    "signals": extracted.get("signals", []),
                                    "text": extracted.get("text", ""),
                                },
                            )
                            resp.raise_for_status()
                            result = resp.json()
                else:
                    result = await extract_evidence_async(evidence)
                await self.service.mark_job_done(job_id, result)
                return {"status": "done", **result}
            if job_type == JOB_VECTOR:
                import os
                if os.getenv("KNOWLEDGE_API_URL") and os.getenv("KNOWLEDGE_API_KEY"):
                    record = build_evidence_vector_record(evidence)
                    if record is None:
                        await self.service.mark_job_failed(job_id, "vector build rejected")
                        return {"status": "failed", "vector_ok": False}
                    client = KnowledgeApiClient(
                        os.environ["KNOWLEDGE_API_URL"], os.environ["KNOWLEDGE_API_KEY"]
                    )
                    ok = await client.upsert_vector(evidence_id, record.vector, record.payload)
                else:
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
            if job_type == JOB_LINK:
                import os
                if os.getenv("KNOWLEDGE_API_URL") and os.getenv("KNOWLEDGE_API_KEY"):
                    actions, _ = await compute_link_actions(evidence, use_db=False)
                    client = KnowledgeApiClient(
                        os.environ["KNOWLEDGE_API_URL"], os.environ["KNOWLEDGE_API_KEY"]
                    )
                    response = await client.upsert_links(
                        evidence_id, [a.to_payload() for a in actions]
                    )
                    if response is None:
                        await self.service.mark_job_failed(job_id, "link upsert failed")
                        return {"status": "failed", "links": 0}
                    result = {
                        "links": response.get("links", 0),
                        "candidates": response.get("candidates", 0),
                        "radar_signals": response.get("radar_signals", 0),
                    }
                    await self.service.mark_job_done(job_id, result)
                    return {"status": "done", **result}
                async with async_session() as session:
                    result = await ingest_evidence(evidence_id, _session=session)
                    # 广度触发器（spec §4.3 修订 1）：机械候选 → 台账 → 雷达信号
                    candidates = await generate_candidates(evidence_id, session)
                    result["candidates"] = await persist_candidates(candidates, session)
                    result["radar_signals"] = await emit_radar_signals(candidates, session)
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
