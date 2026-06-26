"""Worker for claiming and executing durable ingestion jobs."""

from __future__ import annotations

import asyncio
import socket
import uuid

from app.data_pipeline.job_handlers import execute_ingestion_job
from app.data_pipeline.job_queue import (
    JOB_PARTIAL,
    JOB_SUCCESS,
    IngestionJobQueue,
    IngestionJobRecord,
)


class IngestionJobWorker:
    def __init__(
        self,
        queue: IngestionJobQueue | None = None,
        worker_id: str | None = None,
        job_timeout_seconds: int = 300,
    ) -> None:
        self.queue = queue or IngestionJobQueue()
        self.worker_id = worker_id or f"{socket.gethostname()}-{uuid.uuid4().hex[:8]}"
        self.job_timeout_seconds = job_timeout_seconds

    async def run_once(self, limit: int = 20) -> dict[str, int]:
        await self.queue.requeue_stale_running(older_than_minutes=60)
        jobs = await self.queue.claim_jobs(self.worker_id, limit=limit)
        counters = {
            "claimed": len(jobs),
            "success": 0,
            "partial": 0,
            "failed": 0,
            "lost_lock": 0,
        }
        for job in jobs:
            await self._run_job(job, counters)
        return counters

    async def run_loop(self, limit: int = 20, interval_seconds: float = 5.0) -> None:
        while True:
            counters = await self.run_once(limit=limit)
            if counters["claimed"] == 0:
                await asyncio.sleep(interval_seconds)

    async def _run_job(
        self,
        job: IngestionJobRecord,
        counters: dict[str, int],
    ) -> None:
        try:
            result = await asyncio.wait_for(
                execute_ingestion_job(job),
                timeout=self.job_timeout_seconds,
            )
            if result.status == JOB_SUCCESS:
                marked = await self.queue.mark_success(
                    job.id,
                    self.worker_id,
                    result.summary,
                )
                counters["success" if marked else "lost_lock"] += 1
                return
            if result.status == JOB_PARTIAL:
                marked = await self.queue.mark_partial(
                    job.id,
                    self.worker_id,
                    result.summary,
                    result.error,
                )
                counters["partial" if marked else "lost_lock"] += 1
                return
            await self._mark_failure(job, result.error or result.status, counters)
        except TimeoutError:
            error = f"job timed out after {self.job_timeout_seconds}s"
            await self._mark_failure(job, error, counters)
        except Exception as exc:
            await self._mark_failure(job, str(exc), counters)

    async def _mark_failure(
        self,
        job: IngestionJobRecord,
        error: str,
        counters: dict[str, int],
    ) -> None:
        marked = await self.queue.mark_failure(
            job.id,
            self.worker_id,
            error,
            job.attempt_count,
            job.max_attempts,
        )
        counters["failed" if marked else "lost_lock"] += 1
