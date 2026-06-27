"""Async worker that consumes Evidence extraction jobs."""

from __future__ import annotations

import asyncio
import logging
import socket
import time
from typing import Any

from app.knowledge.evidence import JOB_COMBINED, JOB_VECTOR
from app.knowledge.evidence_service import EvidenceService
from app.knowledge.extraction.irm_classifier import classify_irm_evidence, extraction_tier
from app.knowledge.extraction.signal_extractor import (
    RuleBasedSignalExtractor,
    persist_signals_to_company_props,
)
from app.knowledge.kg_extractor import extract_evidence_async
from app.knowledge.structured_fact_service import extract_rule_based_facts, upsert_structured_fact
from app.knowledge.vector_client import upsert_evidence_chunk_vector

logger = logging.getLogger(__name__)


class EvidenceExtractionWorker:
    def __init__(
        self,
        service: EvidenceService | None = None,
        worker_id: str | None = None,
        batch_size: int = 2,
        max_concurrency: int = 2,
    ):
        self.service = service or EvidenceService()
        self.worker_id = worker_id or f"worker-{socket.gethostname()}-{int(time.time())}"
        self.batch_size = batch_size
        self.max_concurrency = max_concurrency

    async def run_once(self, limit: int | None = None, job_type: str = "combined") -> dict[str, int]:
        if limit is not None and limit <= 0:
            return {"claimed": 0, "success": 0, "failed": 0, "skipped": 0, "job_type": job_type}
        claimed = success = failed = skipped = 0
        while True:
            if limit is not None and claimed >= limit:
                break
            batch_limit = self.batch_size
            if limit is not None:
                batch_limit = min(batch_limit, max(0, limit - claimed))
            if batch_limit <= 0:
                break
            jobs = []
            for _ in range(batch_limit):
                job = await self.service.claim_next_job(job_type=job_type, worker_id=self.worker_id)
                if not job:
                    break
                jobs.append(job)
            if not jobs:
                break
            sem = asyncio.Semaphore(self.max_concurrency)

            async def _run(job: dict[str, Any]) -> dict[str, Any]:
                async with sem:
                    return await self.process_job(job)

            results = await asyncio.gather(*[_run(job) for job in jobs], return_exceptions=True)
            for job, res in zip(jobs, results):
                claimed += 1
                if isinstance(res, Exception):
                    failed += 1
                    logger.warning("Evidence job failed unexpectedly [%s]: %s", job.get("job_id"), res)
                elif res.get("status") == "done":
                    success += 1
                elif res.get("status") == "skipped":
                    skipped += 1
                else:
                    failed += 1
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
                    if tier == 1:
                        return await self._process_rules_only(evidence, job_id, category)
                result = await extract_evidence_async(evidence)
                facts = extract_rule_based_facts(
                    evidence, result.get("entities_raw", []), result.get("relations_raw", [])
                )
                fact_ok = 0
                fact_failed = 0
                for fact in facts:
                    try:
                        upsert_structured_fact(fact)
                        fact_ok += 1
                    except Exception as fact_exc:  # noqa: BLE001
                        fact_failed += 1
                        logger.warning("StructuredFact write failed [%s]: %s", evidence_id, fact_exc)
                result["structured_facts_created"] = fact_ok
                result["structured_facts_failed"] = fact_failed
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
            await self.service.mark_job_failed(job_id, f"unsupported job_type: {job_type}")
            return {"status": "failed", "error": f"unsupported job_type: {job_type}"}
        except Exception as exc:  # noqa: BLE001
            await self.service.mark_job_failed(job_id, str(exc))
            return {"status": "failed", "error": str(exc)}

    async def _process_rules_only(
        self, evidence: dict[str, Any], job_id: str, category: str
    ) -> dict[str, Any]:
        """Process IRM evidence with rules only, no LLM call.

        Used for 'simple' and 'data' categories: run signal extraction
        and keyword-based structured facts without LLM.
        """
        text = str(evidence.get("text_excerpt") or "")
        subject_hint = evidence.get("subject_hint") or {}
        ts_code = str(subject_hint.get("ts_code") or "UNKNOWN")
        source_type = str(evidence.get("source_type") or "irm")
        evidence_id = str(evidence.get("evidence_id") or "")

        signal_types: list[str] = []
        sentiment_score = 0.0
        try:
            extractor = RuleBasedSignalExtractor()
            signal_result = extractor.extract_sync(
                text[:10000], source_type, {"ts_code": ts_code}
            )
            signal_types = signal_result.get("detected_types", [])
            sentiment_score = signal_result.get("sentiment_score", 0.0)
            persist_signals_to_company_props(
                signal_result,
                ts_code=ts_code,
                source_type=source_type,
                source_document_id=evidence_id,
            )
        except Exception as exc:
            logger.warning("IRM rules-only signal extraction failed [%s]: %s", evidence_id, exc)

        facts = extract_rule_based_facts(evidence, [], [])
        fact_ok = 0
        fact_failed = 0
        for fact in facts:
            try:
                upsert_structured_fact(fact)
                fact_ok += 1
            except Exception as exc:
                fact_failed += 1
                logger.warning("IRM rules-only StructuredFact write failed [%s]: %s", evidence_id, exc)

        result = {
            "structured_facts_created": fact_ok,
            "structured_facts_failed": fact_failed,
            "signal_types": signal_types,
            "sentiment_score": sentiment_score,
            "llm_skipped": True,
            "irm_category": category,
        }
        await self.service.mark_job_done(job_id, result)
        return {"status": "done", **result}
