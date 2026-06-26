"""Tests for EvidenceExtractionWorker."""

from __future__ import annotations

import asyncio

from app.knowledge.evidence import (
    JOB_COMBINED,
    JOB_VECTOR,
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_PENDING,
)
from app.knowledge.evidence_worker import EvidenceExtractionWorker


class FakeService:
    def __init__(self):
        self.evidence = {
            "EV:1": {
                "evidence_id": "EV:1",
                "source_type": "irm",
                "source_name": "互动易:1",
                "text_excerpt": "公司公告称量产并导入客户。",
                "subject_hint": {"ts_code": "300001.SZ"},
                "source_ref": {},
                "observed_at": "2026-05-21T00:00:00",
                "publish_date": "2026-05-21",
                "confidence": 0.85,
            },
            "EV:2": {
                "evidence_id": "EV:2",
                "source_type": "irm",
                "source_name": "互动易:2",
                "text_excerpt": "订单排产到 2027 年。",
                "subject_hint": {"ts_code": "300002.SZ"},
                "source_ref": {},
                "observed_at": "2026-05-21T00:00:00",
                "publish_date": "2026-05-21",
                "confidence": 0.85,
            },
        }
        self.jobs = []
        self.done = []
        self.failed = []

    async def get_evidence(self, evidence_id: str):
        return self.evidence.get(evidence_id)

    async def claim_next_job(self, job_type: str | None = None, worker_id: str = "", stale_after_minutes: int = 30):
        for job in self.jobs:
            if job["status"] == STATUS_PENDING and (job_type is None or job["job_type"] == job_type):
                job["status"] = "running"
                return job
        return None

    async def mark_job_done(self, job_id: str, result: dict | None = None) -> None:
        self.done.append((job_id, result or {}))
        for job in self.jobs:
            if job["job_id"] == job_id:
                await self.update_evidence_status(job["evidence_id"], job["job_type"], STATUS_DONE)
                break

    async def mark_job_failed(self, job_id: str, error: str, max_retries: int = 3) -> None:
        self.failed.append((job_id, error))
        for job in self.jobs:
            if job["job_id"] == job_id:
                await self.update_evidence_status(job["evidence_id"], job["job_type"], STATUS_FAILED)
                break

    async def update_evidence_status(
        self, evidence_id: str, job_type: str, status: str, extractor_version: str = "evidence-v1"
    ) -> None:
        self.evidence[evidence_id].setdefault("status_updates", []).append((job_type, status))


def _worker(service=None) -> EvidenceExtractionWorker:
    return EvidenceExtractionWorker(
        service=service or FakeService(), batch_size=2, max_concurrency=2, worker_id="test-worker"
    )


def test_run_once_limit_zero_returns_zero() -> None:
    async def main():
        worker = _worker()
        result = await worker.run_once(limit=0)
        assert result == {
            "claimed": 0,
            "success": 0,
            "failed": 0,
            "skipped": 0,
            "job_type": "combined",
        }

    asyncio.run(main())


def test_successful_combined_job_marks_done_and_updates_evidence() -> None:
    async def main():
        service = FakeService()
        service.jobs = [
            {
                "job_id": "J1",
                "evidence_id": "EV:1",
                "job_type": JOB_COMBINED,
                "status": STATUS_PENDING,
            }
        ]
        worker = _worker(service)
        result = await worker.run_once(limit=1, job_type=JOB_COMBINED)
        assert result["claimed"] == 1
        assert result["success"] == 1
        assert service.done
        assert service.evidence["EV:1"]["status_updates"][-1] == (JOB_COMBINED, STATUS_DONE)

    asyncio.run(main())


def test_missing_evidence_marks_job_failed() -> None:
    async def main():
        service = FakeService()
        service.jobs = [
            {
                "job_id": "J1",
                "evidence_id": "EV:missing",
                "job_type": JOB_COMBINED,
                "status": STATUS_PENDING,
            }
        ]
        worker = _worker(service)
        result = await worker.run_once(limit=1, job_type=JOB_COMBINED)
        assert result["failed"] == 1
        assert service.failed

    asyncio.run(main())


def test_extractor_exception_marks_failed() -> None:
    async def main():
        service = FakeService()
        service.jobs = [
            {
                "job_id": "J1",
                "evidence_id": "EV:1",
                "job_type": JOB_COMBINED,
                "status": STATUS_PENDING,
            }
        ]
        worker = _worker(service)
        from app.knowledge import evidence_worker as ew

        orig = ew.extract_evidence_async

        async def boom(*args, **kwargs):
            raise RuntimeError("boom")

        ew.extract_evidence_async = boom
        try:
            result = await worker.run_once(limit=1, job_type=JOB_COMBINED)
            assert result["failed"] == 1
            assert service.failed
            assert service.evidence["EV:1"]["status_updates"][-1] == (JOB_COMBINED, STATUS_FAILED)
        finally:
            ew.extract_evidence_async = orig

    asyncio.run(main())


def test_two_jobs_processed() -> None:
    async def main():
        service = FakeService()
        service.jobs = [
            {
                "job_id": "J1",
                "evidence_id": "EV:1",
                "job_type": JOB_COMBINED,
                "status": STATUS_PENDING,
            },
            {
                "job_id": "J2",
                "evidence_id": "EV:2",
                "job_type": JOB_COMBINED,
                "status": STATUS_PENDING,
            },
        ]
        worker = _worker(service)
        result = await worker.run_once(limit=2, job_type=JOB_COMBINED)
        assert result["claimed"] == 2
        assert result["success"] == 2

    asyncio.run(main())


def test_vector_job_success() -> None:
    async def main():
        service = FakeService()
        service.jobs = [
            {
                "job_id": "J3",
                "evidence_id": "EV:1",
                "job_type": JOB_VECTOR,
                "status": STATUS_PENDING,
            }
        ]
        worker = _worker(service)
        result = await worker.run_once(limit=1, job_type=JOB_VECTOR)
        assert result["success"] == 1

    asyncio.run(main())
