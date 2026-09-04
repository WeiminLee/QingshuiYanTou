from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.data_pipeline.pdf_download_contract import PdfDownloadJobPayload


@dataclass
class FakeEvidenceInput:
    source_type: str = "announcement"
    source_name: str = "公告:600000.SH"
    text_excerpt: str = "正文"
    source_id: str = "ann-1"
    subject_hint: dict | None = None
    publish_date: str | date | None = None
    observed_at: str | date | None = None
    source_ref: dict | None = None
    confidence: float | None = 0.95
    metadata: dict | None = None


class FakeQueue:
    def __init__(self, jobs: list[dict]) -> None:
        self.jobs = jobs
        self.claim_calls: list[dict] = []
        self.success_calls: list[tuple[int, str, dict]] = []
        self.failure_calls: list[tuple[int, str, str, int, int, str | None]] = []

    async def claim_jobs(self, worker_id: str, limit: int = 20, job_types: list[str] | None = None):
        self.claim_calls.append({"worker_id": worker_id, "limit": limit, "job_types": job_types})
        claimed = self.jobs[:limit]
        self.jobs = self.jobs[limit:]
        for job in claimed:
            job["status"] = "running"
            job["locked_by"] = worker_id
        return [SimpleNamespace(**job) for job in claimed]

    async def mark_success(self, job_id: int, worker_id: str, result_summary: dict) -> bool:
        self.success_calls.append((job_id, worker_id, result_summary))
        return True

    async def mark_failure(
        self,
        job_id: int,
        worker_id: str,
        error: str,
        attempt_count: int,
        max_attempts: int,
        error_category: str | None = None,
    ) -> bool:
        self.failure_calls.append((job_id, worker_id, error, attempt_count, max_attempts, error_category))
        return True


class FakeStorage:
    def __init__(self, target_path):
        self.target_path = target_path
        self.saved: list[tuple[bytes, str, str, str | None]] = []

    def _get_notice_path(self, ts_code: str, pub_date: str, filename: str):
        return self.target_path

    def save_notice(self, content: bytes, ts_code: str, filename: str, pub_date: str | None = None):
        self.saved.append((content, ts_code, filename, pub_date))
        self.target_path.write_bytes(content)
        return self.target_path


class FakeEvidenceService:
    def __init__(self) -> None:
        self.upserts: list[tuple[object, int]] = []

    async def upsert_evidence(self, input_obj, chunk_index: int = 0):
        self.upserts.append((input_obj, chunk_index))
        return {"evidence_id": f"EV:{chunk_index}"}


def _job_payload() -> PdfDownloadJobPayload:
    return PdfDownloadJobPayload(
        source_url="https://example.invalid/files/report.pdf",
        source_type="announcement",
        source_id="ann-1",
        stock_code="600000.SH",
        publish_date=date(2026, 9, 1),
        filename="600000.SH-20260901.pdf",
    )


def test_default_concurrency_is_one() -> None:
    from app.knowledge.pdf_download_service import PdfDownloadWorker

    assert PdfDownloadWorker().max_concurrency == 1


def test_run_once_downloads_saves_and_builds_evidence(monkeypatch, tmp_path) -> None:
    from app.knowledge import pdf_download_service as service_mod
    from app.knowledge.pdf_download_service import PdfDownloadWorker

    payload = _job_payload()
    job = {
        "id": 1,
        "job_type": "pdf_download",
        "job_key": payload.job_key,
        "status": "pending",
        "payload": payload.to_payload(),
        "priority": 25,
        "attempt_count": 0,
        "max_attempts": 5,
    }
    queue = FakeQueue([job])
    storage = FakeStorage(tmp_path / "600000.SH-20260901.pdf")
    evidence_service = FakeEvidenceService()
    worker = PdfDownloadWorker(queue=queue, storage=storage, evidence_service=evidence_service, worker_id="desktop-1")
    monkeypatch.setattr(worker, "_download_pdf_bytes", AsyncMock(return_value=b"%PDF-1.4\nbody"))
    builder_calls: list[dict] = []

    def fake_builder(record):
        builder_calls.append(record)
        return [
            FakeEvidenceInput(
                source_id=record["id"],
                publish_date=record["ann_date"],
                observed_at=record["ann_date"],
                source_ref={"chapter_index": 0},
            )
        ]

    monkeypatch.setattr(service_mod, "build_announcement_evidence", fake_builder)

    async def main():
        result = await worker.run_once(limit=1)
        assert result == {"claimed": 1, "success": 1, "failed": 0, "skipped": 0}

    asyncio.run(main())

    assert queue.claim_calls[0]["job_types"] == ["pdf_download"]
    assert storage.saved[0][0].startswith(b"%PDF-")
    assert builder_calls[0]["file_path"] == str(storage.target_path)
    assert evidence_service.upserts[0][1] == 0
    assert queue.success_calls[0][0] == 1


def test_existing_file_skips_download_and_still_builds_evidence(monkeypatch, tmp_path) -> None:
    from app.knowledge import pdf_download_service as service_mod
    from app.knowledge.pdf_download_service import PdfDownloadWorker

    payload = _job_payload()
    target = tmp_path / "existing.pdf"
    target.write_bytes(b"%PDF-1.4\nalready-here")
    job = {
        "id": 2,
        "job_type": "pdf_download",
        "job_key": payload.job_key,
        "status": "pending",
        "payload": payload.to_payload(),
        "priority": 25,
        "attempt_count": 0,
        "max_attempts": 5,
    }
    queue = FakeQueue([job])
    storage = FakeStorage(target)
    def _should_not_redownload(*args, **kwargs):
        raise AssertionError("should not redownload")

    storage.save_notice = _should_not_redownload  # type: ignore[method-assign]
    evidence_service = FakeEvidenceService()
    worker = PdfDownloadWorker(queue=queue, storage=storage, evidence_service=evidence_service, worker_id="desktop-1")
    monkeypatch.setattr(worker, "_download_pdf_bytes", AsyncMock(side_effect=AssertionError("should not download")))
    builder_calls: list[dict] = []

    def fake_builder(record):
        builder_calls.append(record)
        return [FakeEvidenceInput(source_id=record["id"], source_ref={"chapter_index": 0})]

    monkeypatch.setattr(service_mod, "build_announcement_evidence", fake_builder)

    async def main():
        result = await worker.run_once(limit=1)
        assert result == {"claimed": 1, "success": 1, "failed": 0, "skipped": 0}

    asyncio.run(main())

    assert builder_calls[0]["file_path"] == str(target)
    assert evidence_service.upserts
    assert queue.success_calls


def test_invalid_pdf_marks_job_failed_and_does_not_build_evidence(monkeypatch, tmp_path) -> None:
    from app.knowledge import pdf_download_service as service_mod
    from app.knowledge.pdf_download_service import PdfDownloadWorker

    payload = _job_payload()
    job = {
        "id": 3,
        "job_type": "pdf_download",
        "job_key": payload.job_key,
        "status": "pending",
        "payload": payload.to_payload(),
        "priority": 25,
        "attempt_count": 1,
        "max_attempts": 5,
    }
    queue = FakeQueue([job])
    storage = FakeStorage(tmp_path / "bad.pdf")
    evidence_service = FakeEvidenceService()
    worker = PdfDownloadWorker(queue=queue, storage=storage, evidence_service=evidence_service, worker_id="desktop-1")
    monkeypatch.setattr(worker, "_download_pdf_bytes", AsyncMock(return_value=b"<html>not pdf</html>"))
    monkeypatch.setattr(service_mod, "build_announcement_evidence", lambda record: (_ for _ in ()).throw(AssertionError("should not build")))

    async def main():
        result = await worker.run_once(limit=1)
        assert result == {"claimed": 1, "success": 0, "failed": 1, "skipped": 0}

    asyncio.run(main())

    assert queue.failure_calls[0][-1] == "parse_error"
    assert not evidence_service.upserts


def test_retryable_failure_marks_job_failed(monkeypatch, tmp_path) -> None:
    from app.knowledge import pdf_download_service as service_mod
    from app.knowledge.pdf_download_service import PdfDownloadWorker

    payload = _job_payload()
    job = {
        "id": 4,
        "job_type": "pdf_download",
        "job_key": payload.job_key,
        "status": "pending",
        "payload": payload.to_payload(),
        "priority": 25,
        "attempt_count": 0,
        "max_attempts": 5,
    }
    queue = FakeQueue([job])
    storage = FakeStorage(tmp_path / "timeout.pdf")
    evidence_service = FakeEvidenceService()
    worker = PdfDownloadWorker(queue=queue, storage=storage, evidence_service=evidence_service, worker_id="desktop-1")
    monkeypatch.setattr(worker, "_download_pdf_bytes", AsyncMock(side_effect=TimeoutError("boom")))
    monkeypatch.setattr(service_mod, "build_announcement_evidence", lambda record: (_ for _ in ()).throw(AssertionError("should not build")))

    async def main():
        result = await worker.run_once(limit=1)
        assert result == {"claimed": 1, "success": 0, "failed": 1, "skipped": 0}

    asyncio.run(main())

    assert queue.failure_calls[0][-1] == "http_retryable"
    assert not evidence_service.upserts
