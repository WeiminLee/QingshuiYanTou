"""Tests for durable ingestion job queue."""
from __future__ import annotations

import asyncio
import json


class FakeAsyncResult:
    def __init__(self, rows: list[dict] | None = None, rowcount: int = 0) -> None:
        self._rows = rows or []
        self.rowcount = rowcount

    def mappings(self) -> "FakeAsyncResult":
        return self

    def all(self) -> list[dict]:
        return self._rows


class FakeAsyncConnection:
    def __init__(self, result: FakeAsyncResult | None = None) -> None:
        self.result = result or FakeAsyncResult()
        self.calls: list[tuple[object, dict]] = []

    async def execute(self, sql: object, params: dict) -> FakeAsyncResult:
        self.calls.append((sql, params))
        return self.result


class FakeAsyncBegin:
    def __init__(self, connection: FakeAsyncConnection) -> None:
        self.connection = connection

    async def __aenter__(self) -> FakeAsyncConnection:
        return self.connection

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None


class FakeAsyncEngine:
    def __init__(self, connection: FakeAsyncConnection) -> None:
        self.connection = connection

    def begin(self) -> FakeAsyncBegin:
        return FakeAsyncBegin(self.connection)


def test_ingestion_job_model_declares_queue_contract() -> None:
    from sqlalchemy import UniqueConstraint
    from sqlalchemy.dialects.postgresql import JSONB

    from app.models.models import IngestionJob

    table = IngestionJob.__table__
    columns = table.columns

    assert "job_type" in columns
    assert "job_key" in columns
    assert "status" in columns
    assert "payload" in columns
    assert "priority" in columns
    assert "attempt_count" in columns
    assert "max_attempts" in columns
    assert "next_run_at" in columns
    assert "locked_at" in columns
    assert "locked_by" in columns
    assert "last_error" in columns
    assert "result_summary" in columns
    assert "created_at" in columns
    assert "updated_at" in columns
    assert isinstance(columns["payload"].type, JSONB)
    assert isinstance(columns["result_summary"].type, JSONB)

    unique_constraints = {
        constraint.name: [column.name for column in constraint.columns]
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert unique_constraints["uq_ingestion_jobs_type_key"] == ["job_type", "job_key"]

    indexes = {
        index.name: [column.name for column in index.columns]
        for index in table.indexes
    }
    assert indexes["idx_ingestion_jobs_claim"] == [
        "status",
        "next_run_at",
        "priority",
        "id",
    ]
    assert indexes["idx_ingestion_jobs_type_status"] == ["job_type", "status"]
    assert indexes["idx_ingestion_jobs_locked_at"] == ["locked_at"]

    for column_name in (
        "job_type",
        "job_key",
        "status",
        "payload",
        "priority",
        "attempt_count",
        "max_attempts",
        "next_run_at",
    ):
        assert columns[column_name].nullable is False

    assert str(columns["status"].server_default.arg) == "pending"
    assert "jsonb" in str(columns["payload"].server_default.arg)


def test_enqueue_job_uses_type_and_key_as_idempotency_boundary(monkeypatch) -> None:
    from app.data_pipeline import job_queue

    connection = FakeAsyncConnection()
    monkeypatch.setattr(job_queue, "engine", FakeAsyncEngine(connection))

    queue = job_queue.IngestionJobQueue()
    asyncio.run(
        queue.enqueue_job(
            job_type="cninfo_announcement_date",
            job_key="20260523",
            payload={"date": "20260523"},
            priority=10,
            max_attempts=7,
        )
    )

    sql = str(connection.calls[0][0])
    params = connection.calls[0][1]
    assert "ON CONFLICT (job_type, job_key) DO UPDATE" in sql
    assert params["job_type"] == "cninfo_announcement_date"
    assert params["job_key"] == "20260523"
    assert params["payload"] == json.dumps({"date": "20260523"}, ensure_ascii=False)
    assert params["priority"] == 10
    assert params["max_attempts"] == 7


def test_claim_jobs_uses_skip_locked(monkeypatch) -> None:
    from app.data_pipeline import job_queue

    connection = FakeAsyncConnection(
        FakeAsyncResult(
            [
                {
                    "id": 123,
                    "job_type": "cninfo_announcement_date",
                    "job_key": "20260523",
                    "status": "running",
                    "payload": {"date": "20260523"},
                    "priority": 10,
                    "attempt_count": 0,
                    "max_attempts": 7,
                    "locked_by": "worker-a",
                }
            ]
        )
    )
    monkeypatch.setattr(job_queue, "engine", FakeAsyncEngine(connection))

    jobs = asyncio.run(job_queue.IngestionJobQueue().claim_jobs("worker-a", limit=10))

    sql = str(connection.calls[0][0])
    params = connection.calls[0][1]
    assert "FOR UPDATE SKIP LOCKED" in sql
    assert params == {"worker_id": "worker-a", "limit": 10}
    assert jobs[0].job_type == "cninfo_announcement_date"
    assert jobs[0].payload == {"date": "20260523"}
    assert jobs[0].locked_by == "worker-a"


def test_mark_failure_only_updates_current_lock_holder(monkeypatch) -> None:
    from app.data_pipeline import job_queue

    connection = FakeAsyncConnection(FakeAsyncResult(rowcount=1))
    monkeypatch.setattr(job_queue, "engine", FakeAsyncEngine(connection))

    updated = asyncio.run(
        job_queue.IngestionJobQueue().mark_failure(
            job_id=123,
            worker_id="worker-a",
            error="x" * 5000,
            attempt_count=4,
            max_attempts=5,
        )
    )

    sql = str(connection.calls[0][0])
    params = connection.calls[0][1]
    assert updated is True
    assert "status = 'running'" in sql
    assert "locked_by = :worker_id" in sql
    assert params["worker_id"] == "worker-a"
    assert params["attempt_count"] == 5
    assert params["status"] == "dead"
    assert len(params["last_error"]) == 4000


def test_mark_success_only_finishes_current_lock_holder(monkeypatch) -> None:
    from app.data_pipeline import job_queue

    connection = FakeAsyncConnection(FakeAsyncResult(rowcount=0))
    monkeypatch.setattr(job_queue, "engine", FakeAsyncEngine(connection))

    updated = asyncio.run(
        job_queue.IngestionJobQueue().mark_success(
            job_id=123,
            worker_id="worker-a",
            result_summary={"saved": 3},
        )
    )

    sql = str(connection.calls[0][0])
    params = connection.calls[0][1]
    assert updated is False
    assert "status = 'running'" in sql
    assert "locked_by = :worker_id" in sql
    assert params["worker_id"] == "worker-a"
    assert params["result_summary"] == json.dumps({"saved": 3}, ensure_ascii=False)


def test_requeue_stale_running_counts_timeout_as_attempt(monkeypatch) -> None:
    from app.data_pipeline import job_queue

    connection = FakeAsyncConnection(FakeAsyncResult(rowcount=2))
    monkeypatch.setattr(job_queue, "engine", FakeAsyncEngine(connection))

    updated_count = asyncio.run(job_queue.IngestionJobQueue().requeue_stale_running())

    sql = str(connection.calls[0][0])
    assert updated_count == 2
    assert "attempt_count = attempt_count + 1" in sql
    assert "attempt_count + 1 >= max_attempts" in sql
    assert "THEN 'dead'" in sql


def test_enqueue_job_resets_dead_jobs_for_new_schedule_round(monkeypatch) -> None:
    from app.data_pipeline import job_queue

    connection = FakeAsyncConnection()
    monkeypatch.setattr(job_queue, "engine", FakeAsyncEngine(connection))

    asyncio.run(
        job_queue.IngestionJobQueue().enqueue_job(
            job_type="cninfo_announcement_date",
            job_key="20260523",
            payload={"date": "20260523"},
        )
    )

    sql = str(connection.calls[0][0])
    assert "attempt_count = CASE" in sql
    assert "WHEN ingestion_jobs.status = 'dead' THEN 0" in sql
    assert "last_error = CASE" in sql
    assert "WHEN ingestion_jobs.status = 'dead' THEN NULL" in sql


def test_enqueue_job_can_force_requeue_completed_jobs(monkeypatch) -> None:
    from app.data_pipeline import job_queue

    connection = FakeAsyncConnection()
    monkeypatch.setattr(job_queue, "engine", FakeAsyncEngine(connection))

    asyncio.run(
        job_queue.IngestionJobQueue().enqueue_job(
            job_type="irm_company",
            job_key="600000.SH",
            payload={"ts_code": "600000.SH"},
            force_requeue=True,
        )
    )

    sql = str(connection.calls[0][0])
    params = connection.calls[0][1]
    assert params["force_requeue"] is True
    assert "WHEN :force_requeue AND ingestion_jobs.status <> 'running' THEN 'pending'" in sql
    assert "WHEN :force_requeue AND ingestion_jobs.status <> 'running' THEN 0" in sql
    assert "WHEN :force_requeue AND ingestion_jobs.status <> 'running' THEN NULL" in sql
