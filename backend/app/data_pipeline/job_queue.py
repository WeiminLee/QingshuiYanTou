"""Durable ingestion job queue API."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text

from app.core.database import engine


JOB_PENDING = "pending"
JOB_RUNNING = "running"
JOB_SUCCESS = "success"
JOB_PARTIAL = "partial"
JOB_FAILED = "failed"
JOB_DEAD = "dead"

JOB_CNINFO_ANNOUNCEMENT_DATE = "cninfo_announcement_date"
JOB_IRM_COMPANY = "irm_company"


@dataclass(frozen=True)
class IngestionJobRecord:
    id: int
    job_type: str
    job_key: str
    status: str
    payload: dict[str, Any]
    priority: int
    attempt_count: int
    max_attempts: int
    locked_by: str | None = None


class IngestionJobQueue:
    async def enqueue_job(
        self,
        job_type: str,
        job_key: str,
        payload: dict[str, Any],
        priority: int = 100,
        max_attempts: int = 5,
        next_run_at: datetime | None = None,
        force_requeue: bool = False,
    ) -> None:
        sql = text(
            """
            INSERT INTO ingestion_jobs (
                job_type,
                job_key,
                status,
                payload,
                priority,
                max_attempts,
                next_run_at,
                updated_at
            )
            VALUES (
                :job_type,
                :job_key,
                :status,
                CAST(:payload AS jsonb),
                :priority,
                :max_attempts,
                COALESCE(:next_run_at, NOW()),
                NOW()
            )
            ON CONFLICT (job_type, job_key) DO UPDATE
            SET
                payload = EXCLUDED.payload,
                priority = LEAST(ingestion_jobs.priority, EXCLUDED.priority),
                max_attempts = GREATEST(ingestion_jobs.max_attempts, EXCLUDED.max_attempts),
                next_run_at = CASE
                    WHEN :force_requeue AND ingestion_jobs.status <> 'running'
                        THEN EXCLUDED.next_run_at
                    WHEN ingestion_jobs.status IN ('success', 'running')
                        THEN ingestion_jobs.next_run_at
                    ELSE LEAST(ingestion_jobs.next_run_at, EXCLUDED.next_run_at)
                END,
                status = CASE
                    WHEN :force_requeue AND ingestion_jobs.status <> 'running' THEN 'pending'
                    WHEN ingestion_jobs.status = 'dead' THEN 'pending'
                    ELSE ingestion_jobs.status
                END,
                attempt_count = CASE
                    WHEN :force_requeue AND ingestion_jobs.status <> 'running' THEN 0
                    WHEN ingestion_jobs.status = 'dead' THEN 0
                    ELSE ingestion_jobs.attempt_count
                END,
                last_error = CASE
                    WHEN :force_requeue AND ingestion_jobs.status <> 'running' THEN NULL
                    WHEN ingestion_jobs.status = 'dead' THEN NULL
                    ELSE ingestion_jobs.last_error
                END,
                locked_at = CASE
                    WHEN :force_requeue AND ingestion_jobs.status <> 'running' THEN NULL
                    WHEN ingestion_jobs.status = 'dead' THEN NULL
                    ELSE ingestion_jobs.locked_at
                END,
                locked_by = CASE
                    WHEN :force_requeue AND ingestion_jobs.status <> 'running' THEN NULL
                    WHEN ingestion_jobs.status = 'dead' THEN NULL
                    ELSE ingestion_jobs.locked_by
                END,
                updated_at = NOW()
            """
        )
        params = {
            "job_type": job_type,
            "job_key": job_key,
            "status": JOB_PENDING,
            "payload": json.dumps(payload, ensure_ascii=False),
            "priority": priority,
            "max_attempts": max_attempts,
            "next_run_at": next_run_at,
            "force_requeue": force_requeue,
        }
        async with engine.begin() as connection:
            await connection.execute(sql, params)

    async def claim_jobs(self, worker_id: str, limit: int = 20) -> list[IngestionJobRecord]:
        sql = text(
            """
            WITH picked AS (
                SELECT id
                FROM ingestion_jobs
                WHERE status IN ('pending', 'failed')
                  AND next_run_at <= NOW()
                ORDER BY priority ASC, next_run_at ASC, id ASC
                FOR UPDATE SKIP LOCKED
                LIMIT :limit
            )
            UPDATE ingestion_jobs
            SET
                status = 'running',
                locked_by = :worker_id,
                locked_at = NOW(),
                updated_at = NOW()
            FROM picked
            WHERE ingestion_jobs.id = picked.id
            RETURNING
                ingestion_jobs.id,
                ingestion_jobs.job_type,
                ingestion_jobs.job_key,
                ingestion_jobs.status,
                ingestion_jobs.payload,
                ingestion_jobs.priority,
                ingestion_jobs.attempt_count,
                ingestion_jobs.max_attempts,
                ingestion_jobs.locked_by
            """
        )
        async with engine.begin() as connection:
            result = await connection.execute(
                sql,
                {"worker_id": worker_id, "limit": limit},
            )
            rows = result.mappings().all()

        return [
            IngestionJobRecord(
                id=row["id"],
                job_type=row["job_type"],
                job_key=row["job_key"],
                status=row["status"],
                payload=dict(row["payload"] or {}),
                priority=row["priority"],
                attempt_count=row["attempt_count"],
                max_attempts=row["max_attempts"],
                locked_by=row["locked_by"],
            )
            for row in rows
        ]

    async def mark_success(
        self,
        job_id: int,
        worker_id: str,
        result_summary: dict[str, Any],
    ) -> bool:
        return await self._finish(
            job_id,
            worker_id,
            JOB_SUCCESS,
            result_summary,
            error=None,
        )

    async def mark_partial(
        self,
        job_id: int,
        worker_id: str,
        result_summary: dict[str, Any],
        error: str | None = None,
    ) -> bool:
        return await self._finish(
            job_id,
            worker_id,
            JOB_PARTIAL,
            result_summary,
            error=error,
        )

    async def mark_failure(
        self,
        job_id: int,
        worker_id: str,
        error: str,
        attempt_count: int,
        max_attempts: int,
    ) -> bool:
        next_attempt = attempt_count + 1
        status = JOB_DEAD if next_attempt >= max_attempts else JOB_FAILED
        delay_minutes = min(60, 2 ** max(0, next_attempt - 1))
        sql = text(
            """
            UPDATE ingestion_jobs
            SET
                status = :status,
                attempt_count = :attempt_count,
                locked_at = NULL,
                locked_by = NULL,
                last_error = :last_error,
                next_run_at = NOW() + (:delay_minutes * INTERVAL '1 minute'),
                updated_at = NOW()
            WHERE id = :job_id
              AND status = 'running'
              AND locked_by = :worker_id
            """
        )
        async with engine.begin() as connection:
            result = await connection.execute(
                sql,
                {
                    "job_id": job_id,
                    "worker_id": worker_id,
                    "status": status,
                    "attempt_count": next_attempt,
                    "last_error": error[:4000],
                    "delay_minutes": delay_minutes,
                },
            )
        return bool(result.rowcount and result.rowcount > 0)

    async def _finish(
        self,
        job_id: int,
        worker_id: str,
        status: str,
        result_summary: dict[str, Any],
        error: str | None,
    ) -> bool:
        sql = text(
            """
            UPDATE ingestion_jobs
            SET
                status = :status,
                result_summary = CAST(:result_summary AS jsonb),
                locked_at = NULL,
                locked_by = NULL,
                last_error = :last_error,
                updated_at = NOW()
            WHERE id = :job_id
              AND status = 'running'
              AND locked_by = :worker_id
            """
        )
        async with engine.begin() as connection:
            result = await connection.execute(
                sql,
                {
                    "job_id": job_id,
                    "worker_id": worker_id,
                    "status": status,
                    "result_summary": json.dumps(result_summary, ensure_ascii=False),
                    "last_error": error[:4000] if error is not None else None,
                },
            )
        return bool(result.rowcount and result.rowcount > 0)

    async def requeue_stale_running(self, older_than_minutes: int = 60) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=older_than_minutes)
        sql = text(
            """
            UPDATE ingestion_jobs
            SET
                attempt_count = attempt_count + 1,
                status = CASE
                    WHEN attempt_count + 1 >= max_attempts THEN 'dead'
                    ELSE 'failed'
                END,
                locked_at = NULL,
                locked_by = NULL,
                last_error = 'worker lock expired',
                next_run_at = NOW(),
                updated_at = NOW()
            WHERE status = 'running'
              AND locked_at < :cutoff
            """
        )
        async with engine.begin() as connection:
            result = await connection.execute(sql, {"cutoff": cutoff})
        return int(result.rowcount or 0)
