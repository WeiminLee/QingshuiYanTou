"""Desktop PDF download worker for durable ingestion jobs."""

from __future__ import annotations

import asyncio
import logging
import socket
import uuid
from datetime import date
from pathlib import Path
from urllib.request import Request, urlopen
from typing import Any

from app.data_pipeline.file_storage import FileStorage, HTTP_HEADERS
from app.data_pipeline.pdf_download_contract import PdfDownloadJobPayload

logger = logging.getLogger(__name__)
JOB_PDF_DOWNLOAD = "pdf_download"


def _publish_date_token(value: date) -> str:
    return value.strftime("%Y%m%d")


def _job_attr(job: IngestionJobRecord | dict[str, Any], name: str, default: Any = None) -> Any:
    if isinstance(job, dict):
        return job.get(name, default)
    return getattr(job, name, default)


def build_announcement_evidence(record: dict[str, Any]):
    from app.knowledge.evidence_builders_simple import build_announcement_evidence as _build

    return _build(record)


class PdfDownloadWorker:
    def __init__(
        self,
        queue: Any | None = None,
        storage: FileStorage | None = None,
        evidence_service: Any | None = None,
        worker_id: str | None = None,
        max_concurrency: int = 1,
        request_timeout_seconds: int = 30,
    ) -> None:
        self.queue = queue
        self.storage = storage or FileStorage()
        self.evidence_service = evidence_service
        self.worker_id = worker_id or f"pdf-download-{socket.gethostname()}-{uuid.uuid4().hex[:8]}"
        self.max_concurrency = max(1, max_concurrency)
        self.request_timeout_seconds = max(1, request_timeout_seconds)

    async def run_once(self, limit: int | None = None) -> dict[str, int]:
        if limit is not None and limit <= 0:
            return {"claimed": 0, "success": 0, "failed": 0, "skipped": 0}

        claimed = success = failed = skipped = 0
        queue = self.queue or self._make_default_queue()
        while True:
            if limit is not None and claimed >= limit:
                break
            remaining = None if limit is None else max(0, limit - claimed)
            batch_limit = self.max_concurrency if remaining is None else min(self.max_concurrency, remaining)
            if batch_limit <= 0:
                break

            jobs = await queue.claim_jobs(
                self.worker_id,
                limit=batch_limit,
                job_types=[JOB_PDF_DOWNLOAD],
            )
            if not jobs:
                break

            sem = asyncio.Semaphore(self.max_concurrency)

            async def _run(job: IngestionJobRecord) -> dict[str, Any]:
                async with sem:
                    return await self.process_job(job)

            results = await asyncio.gather(*[_run(job) for job in jobs], return_exceptions=True)
            for job, result in zip(jobs, results):
                claimed += 1
                if isinstance(result, Exception):
                    failed += 1
                    logger.warning("pdf download job raised unexpectedly [%s]: %s", job.id, result)
                    continue
                status = str(result.get("status") or "failed")
                if status == "done":
                    success += 1
                elif status == "skipped":
                    skipped += 1
                else:
                    failed += 1

        return {"claimed": claimed, "success": success, "failed": failed, "skipped": skipped}

    async def run_loop(
        self,
        interval_seconds: float = 30.0,
        limit_per_loop: int | None = None,
        stop_event: asyncio.Event | None = None,
    ) -> None:
        stop_event = stop_event or asyncio.Event()
        while not stop_event.is_set():
            result = await self.run_once(limit=limit_per_loop)
            logger.info("pdf download worker loop: %s", result)
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
            except TimeoutError:
                continue

    async def process_job(self, job: IngestionJobRecord | dict[str, Any]) -> dict[str, Any]:
        queue = self.queue or self._make_default_queue()
        job_id = int(_job_attr(job, "id"))
        attempt_count = int(_job_attr(job, "attempt_count", 0))
        max_attempts = int(_job_attr(job, "max_attempts", 1))
        payload_raw = dict(_job_attr(job, "payload", {}))

        try:
            payload = PdfDownloadJobPayload.from_payload(payload_raw)
        except Exception as exc:  # noqa: BLE001
            await queue.mark_failure(
                job_id,
                self.worker_id,
                f"invalid pdf download payload: {exc}",
                attempt_count,
                max_attempts,
                error_category="parse_error",
            )
            return {"status": "failed", "error": str(exc)}

        pdf_path = self._notice_path(payload)
        existing_file = pdf_path.exists()
        if not existing_file:
            try:
                content = await self._download_pdf_bytes(payload.source_url)
            except Exception as exc:  # noqa: BLE001
                await queue.mark_failure(
                    job_id,
                    self.worker_id,
                    f"download failed: {exc}",
                    attempt_count,
                    max_attempts,
                    error_category="http_retryable",
                )
                return {"status": "failed", "error": str(exc)}

            if not content or not content.startswith(b"%PDF-"):
                await queue.mark_failure(
                    job_id,
                    self.worker_id,
                    "invalid pdf content",
                    attempt_count,
                    max_attempts,
                    error_category="parse_error",
                )
                return {"status": "failed", "error": "invalid pdf content"}

            try:
                saved_path = self.storage.save_notice(
                    content,
                    payload.stock_code,
                    payload.filename,
                    pub_date=_publish_date_token(payload.publish_date),
                )
            except Exception as exc:  # noqa: BLE001
                await queue.mark_failure(
                    job_id,
                    self.worker_id,
                    f"save failed: {exc}",
                    attempt_count,
                    max_attempts,
                    error_category="http_retryable",
                )
                return {"status": "failed", "error": str(exc)}

            if saved_path is None:
                await queue.mark_failure(
                    job_id,
                    self.worker_id,
                    "pdf save rejected",
                    attempt_count,
                    max_attempts,
                    error_category="parse_error",
                )
                return {"status": "failed", "error": "pdf save rejected"}
            pdf_path = Path(saved_path)

        try:
            record = self._build_announcement_record(payload, pdf_path)
            evidence_inputs = self._build_announcement_evidence(record)
        except Exception as exc:  # noqa: BLE001
            await queue.mark_failure(
                job_id,
                self.worker_id,
                f"evidence build failed: {exc}",
                attempt_count,
                max_attempts,
                error_category="parse_error",
            )
            return {"status": "failed", "error": str(exc)}

        for default_index, input_obj in enumerate(evidence_inputs):
            source_ref = dict(getattr(input_obj, "source_ref", {}) or {})
            chunk_index = int(source_ref.get("chapter_index", default_index) or default_index)
            if self.evidence_service is None:
                self.evidence_service = self._make_default_evidence_service()
            await self.evidence_service.upsert_evidence(input_obj, chunk_index=chunk_index)

        summary = {
            "source_id": payload.source_id,
            "saved_path": str(pdf_path),
            "evidence_inputs": len(evidence_inputs),
            "downloaded": int(not existing_file),
        }
        marked = await queue.mark_success(job_id, self.worker_id, summary)
        if not marked:
            return {"status": "failed", "error": "lost job lock"}
        return {"status": "done", **summary}

    def _notice_path(self, payload: PdfDownloadJobPayload) -> Path:
        pub_date = _publish_date_token(payload.publish_date)
        if hasattr(self.storage, "_get_notice_path"):
            return Path(self.storage._get_notice_path(payload.stock_code, pub_date, payload.filename))
        return Path(payload.filename)

    def _build_announcement_record(self, payload: PdfDownloadJobPayload, pdf_path: Path) -> dict[str, Any]:
        return {
            "id": payload.source_id,
            "ann_date": payload.publish_date.isoformat(),
            "ts_code": payload.stock_code,
            "name": payload.stock_code,
            "title": payload.filename,
            "announcement_type": payload.source_type,
            "pdf_url": payload.source_url,
            "file_path": str(pdf_path),
        }

    def _make_default_queue(self) -> Any:
        import os
        if os.getenv("KNOWLEDGE_API_URL") and os.getenv("KNOWLEDGE_API_KEY"):
            from app.knowledge.worker_api_client import KnowledgeApiClient
            return KnowledgeApiClient(os.environ["KNOWLEDGE_API_URL"], os.environ["KNOWLEDGE_API_KEY"])
        from app.data_pipeline.job_queue import IngestionJobQueue

        return IngestionJobQueue()

    def _build_announcement_evidence(self, record: dict[str, Any]):
        return build_announcement_evidence(record)

    def _make_default_evidence_service(self) -> Any:
        import os
        if os.getenv("KNOWLEDGE_API_URL") and os.getenv("KNOWLEDGE_API_KEY"):
            from app.knowledge.worker_api_client import KnowledgeApiClient
            return KnowledgeApiClient(os.environ["KNOWLEDGE_API_URL"], os.environ["KNOWLEDGE_API_KEY"])
        from app.knowledge.evidence_service import EvidenceService

        return EvidenceService()

    async def _download_pdf_bytes(self, url: str) -> bytes:
        request = Request(url, headers=HTTP_HEADERS)

        def _read() -> bytes:
            with urlopen(request, timeout=self.request_timeout_seconds) as response:
                return response.read()

        return await asyncio.to_thread(_read)
