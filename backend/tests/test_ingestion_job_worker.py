from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock


def test_handler_runs_cninfo_date_job() -> None:
    from app.data_pipeline.job_handlers import execute_ingestion_job
    from app.data_pipeline.job_queue import (
        JOB_CNINFO_ANNOUNCEMENT_DATE,
        IngestionJobRecord,
    )

    fetcher = SimpleNamespace(
        fetch_announcements=AsyncMock(
            return_value={
                "total": 1831,
                "success": 1831,
                "skipped": 0,
                "downloaded": 10,
                "fail": 0,
            }
        )
    )
    job = IngestionJobRecord(
        id=1,
        job_type=JOB_CNINFO_ANNOUNCEMENT_DATE,
        job_key="20260523",
        status="running",
        payload={"date": "20260523"},
        priority=10,
        attempt_count=0,
        max_attempts=5,
    )

    result = asyncio.run(execute_ingestion_job(job, fetcher=fetcher))

    fetcher.fetch_announcements.assert_awaited_once_with(ann_date="20260523")
    assert result.status == "success"
    assert result.summary["success"] == 1831


def test_handler_runs_cninfo_date_job_partial() -> None:
    from app.data_pipeline.job_handlers import execute_ingestion_job
    from app.data_pipeline.job_queue import (
        JOB_CNINFO_ANNOUNCEMENT_DATE,
        IngestionJobRecord,
    )

    fetcher = SimpleNamespace(
        fetch_announcements=AsyncMock(
            return_value={
                "total": 1831,
                "success": 1800,
                "skipped": 0,
                "downloaded": 10,
                "fail": 31,
            }
        )
    )
    job = IngestionJobRecord(
        id=11,
        job_type=JOB_CNINFO_ANNOUNCEMENT_DATE,
        job_key="20260523",
        status="running",
        payload={"date": "20260523"},
        priority=10,
        attempt_count=0,
        max_attempts=5,
    )

    result = asyncio.run(execute_ingestion_job(job, fetcher=fetcher))

    assert result.status == "failed"
    assert result.error == "fetcher returned fail=31"
    assert result.summary["fail"] == 31


def test_handler_maps_all_failed_fetcher_result_to_failed() -> None:
    from app.data_pipeline.job_handlers import execute_ingestion_job
    from app.data_pipeline.job_queue import (
        JOB_IRM_COMPANY,
        IngestionJobRecord,
    )

    fetcher = SimpleNamespace(
        fetch_irm=AsyncMock(
            return_value={
                "total": 1,
                "success": 0,
                "fail": 1,
                "skipped": 0,
                "duplicates": 0,
                "invalid": 0,
                "fetched_records": 0,
            }
        )
    )
    job = IngestionJobRecord(
        id=12,
        job_type=JOB_IRM_COMPANY,
        job_key="600009.SH",
        status="running",
        payload={"ts_code": "600009.SH"},
        priority=50,
        attempt_count=0,
        max_attempts=5,
    )

    result = asyncio.run(execute_ingestion_job(job, fetcher=fetcher))

    assert result.status == "failed"
    assert result.error == "fetcher returned fail=1"


def test_handler_runs_irm_company_job() -> None:
    from app.data_pipeline.job_handlers import execute_ingestion_job
    from app.data_pipeline.job_queue import JOB_IRM_COMPANY, IngestionJobRecord

    fetcher = SimpleNamespace(
        fetch_irm=AsyncMock(
            return_value={
                "total": 1,
                "success": 2,
                "fail": 0,
                "skipped": 0,
                "duplicates": 1,
                "invalid": 0,
                "fetched_records": 3,
            }
        )
    )
    job = IngestionJobRecord(
        id=2,
        job_type=JOB_IRM_COMPANY,
        job_key="600000.SH",
        status="running",
        payload={"ts_code": "600000.SH"},
        priority=50,
        attempt_count=0,
        max_attempts=5,
    )

    result = asyncio.run(execute_ingestion_job(job, fetcher=fetcher))

    fetcher.fetch_irm.assert_awaited_once_with(
        ts_codes=["600000.SH"],
        extract_to_kg=False,
    )
    assert result.status == "success"
    assert result.summary["fetched_records"] == 3


def test_handler_rejects_unknown_job_type_without_constructing_fetcher(monkeypatch) -> None:
    from app.data_pipeline import job_handlers
    from app.data_pipeline.job_queue import IngestionJobRecord

    constructed = []

    def fake_fetcher() -> object:
        constructed.append(True)
        return object()

    monkeypatch.setattr(job_handlers, "DataFetcher", fake_fetcher)
    job = IngestionJobRecord(
        id=3,
        job_type="unsupported",
        job_key="bad",
        status="running",
        payload={},
        priority=1,
        attempt_count=0,
        max_attempts=1,
    )

    try:
        asyncio.run(job_handlers.execute_ingestion_job(job))
    except ValueError as exc:
        assert "unsupported ingestion job_type" in str(exc)
    else:
        raise AssertionError("expected ValueError")

    assert constructed == []


def test_handler_missing_payload_key_raises_without_constructing_fetcher(monkeypatch) -> None:
    from app.data_pipeline import job_handlers
    from app.data_pipeline.job_queue import JOB_CNINFO_ANNOUNCEMENT_DATE, IngestionJobRecord

    constructed = []

    def fake_fetcher() -> object:
        constructed.append(True)
        return object()

    monkeypatch.setattr(job_handlers, "DataFetcher", fake_fetcher)
    job = IngestionJobRecord(
        id=4,
        job_type=JOB_CNINFO_ANNOUNCEMENT_DATE,
        job_key="bad",
        status="running",
        payload={},
        priority=1,
        attempt_count=0,
        max_attempts=1,
    )

    try:
        asyncio.run(job_handlers.execute_ingestion_job(job))
    except KeyError:
        pass
    else:
        raise AssertionError("expected KeyError")

    assert constructed == []


def test_worker_marks_success(monkeypatch) -> None:
    from app.data_pipeline import job_worker
    from app.data_pipeline.job_handlers import JobExecutionResult

    queue = SimpleNamespace(
        requeue_stale_running=AsyncMock(return_value=0),
        claim_jobs=AsyncMock(
            return_value=[
                SimpleNamespace(
                    id=1,
                    attempt_count=0,
                    max_attempts=5,
                )
            ]
        ),
        mark_success=AsyncMock(return_value=True),
        mark_partial=AsyncMock(),
        mark_failure=AsyncMock(),
    )

    async def fake_execute(job) -> JobExecutionResult:
        return JobExecutionResult(status="success", summary={"success": 1})

    monkeypatch.setattr(job_worker, "execute_ingestion_job", fake_execute)

    result = asyncio.run(job_worker.IngestionJobWorker(queue=queue, worker_id="test-worker").run_once(limit=5))

    assert result == {
        "claimed": 1,
        "success": 1,
        "partial": 0,
        "failed": 0,
        "lost_lock": 0,
    }
    queue.requeue_stale_running.assert_awaited_once_with(older_than_minutes=60)
    queue.claim_jobs.assert_awaited_once_with("test-worker", limit=5)
    queue.mark_success.assert_awaited_once_with(1, "test-worker", {"success": 1})
    queue.mark_partial.assert_not_awaited()
    queue.mark_failure.assert_not_awaited()


def test_worker_marks_failure_on_exception(monkeypatch) -> None:
    from app.data_pipeline import job_worker

    queue = SimpleNamespace(
        requeue_stale_running=AsyncMock(return_value=0),
        claim_jobs=AsyncMock(
            return_value=[
                SimpleNamespace(
                    id=3,
                    attempt_count=2,
                    max_attempts=5,
                )
            ]
        ),
        mark_success=AsyncMock(),
        mark_partial=AsyncMock(),
        mark_failure=AsyncMock(return_value=True),
    )

    async def fake_execute(job) -> None:
        raise RuntimeError("cninfo 599")

    monkeypatch.setattr(job_worker, "execute_ingestion_job", fake_execute)

    result = asyncio.run(job_worker.IngestionJobWorker(queue=queue, worker_id="test-worker").run_once())

    assert result == {
        "claimed": 1,
        "success": 0,
        "partial": 0,
        "failed": 1,
        "lost_lock": 0,
    }
    queue.mark_failure.assert_awaited_once_with(
        3,
        "test-worker",
        "cninfo 599",
        2,
        5,
    )
    queue.mark_success.assert_not_awaited()
    queue.mark_partial.assert_not_awaited()


def test_worker_retries_partial_fetcher_result(monkeypatch) -> None:
    from app.data_pipeline import job_worker
    from app.data_pipeline.job_handlers import JobExecutionResult

    job = SimpleNamespace(
        id=9,
        attempt_count=1,
        max_attempts=5,
    )
    queue = SimpleNamespace(
        requeue_stale_running=AsyncMock(return_value=0),
        claim_jobs=AsyncMock(return_value=[job]),
        mark_success=AsyncMock(),
        mark_partial=AsyncMock(),
        mark_failure=AsyncMock(return_value=True),
    )

    async def fake_execute(_job) -> JobExecutionResult:
        return JobExecutionResult(
            status="failed",
            summary={"success": 1800, "fail": 31},
            error="fetcher returned fail=31",
        )

    monkeypatch.setattr(job_worker, "execute_ingestion_job", fake_execute)

    result = asyncio.run(job_worker.IngestionJobWorker(queue=queue, worker_id="test-worker").run_once(limit=5))

    assert result["failed"] == 1
    queue.mark_failure.assert_awaited_once_with(
        9,
        "test-worker",
        "fetcher returned fail=31",
        1,
        5,
    )
    queue.mark_partial.assert_not_awaited()


def test_worker_marks_partial(monkeypatch) -> None:
    from app.data_pipeline import job_worker
    from app.data_pipeline.job_handlers import JobExecutionResult

    queue = SimpleNamespace(
        requeue_stale_running=AsyncMock(return_value=0),
        claim_jobs=AsyncMock(
            return_value=[
                SimpleNamespace(
                    id=2,
                    attempt_count=0,
                    max_attempts=5,
                )
            ]
        ),
        mark_success=AsyncMock(),
        mark_partial=AsyncMock(return_value=True),
        mark_failure=AsyncMock(),
    )

    async def fake_execute(job) -> JobExecutionResult:
        return JobExecutionResult(
            status="partial",
            summary={"success": 9, "fail": 1},
            error="fetcher returned fail=1",
        )

    monkeypatch.setattr(job_worker, "execute_ingestion_job", fake_execute)

    result = asyncio.run(job_worker.IngestionJobWorker(queue=queue, worker_id="test-worker").run_once())

    assert result == {
        "claimed": 1,
        "success": 0,
        "partial": 1,
        "failed": 0,
        "lost_lock": 0,
    }
    queue.mark_partial.assert_awaited_once_with(
        2,
        "test-worker",
        {"success": 9, "fail": 1},
        "fetcher returned fail=1",
    )
    queue.mark_success.assert_not_awaited()
    queue.mark_failure.assert_not_awaited()


def test_worker_counts_lost_lock_when_success_mark_loses_lock(monkeypatch) -> None:
    from app.data_pipeline import job_worker
    from app.data_pipeline.job_handlers import JobExecutionResult

    queue = SimpleNamespace(
        requeue_stale_running=AsyncMock(return_value=0),
        claim_jobs=AsyncMock(
            return_value=[
                SimpleNamespace(
                    id=4,
                    attempt_count=0,
                    max_attempts=5,
                )
            ]
        ),
        mark_success=AsyncMock(return_value=False),
        mark_partial=AsyncMock(),
        mark_failure=AsyncMock(),
    )

    async def fake_execute(job) -> JobExecutionResult:
        return JobExecutionResult(status="success", summary={"success": 1})

    monkeypatch.setattr(job_worker, "execute_ingestion_job", fake_execute)

    result = asyncio.run(job_worker.IngestionJobWorker(queue=queue, worker_id="test-worker").run_once())

    assert result == {
        "claimed": 1,
        "success": 0,
        "partial": 0,
        "failed": 0,
        "lost_lock": 1,
    }
    queue.mark_success.assert_awaited_once_with(4, "test-worker", {"success": 1})
    queue.mark_partial.assert_not_awaited()
    queue.mark_failure.assert_not_awaited()


def test_worker_counts_lost_lock_when_partial_mark_loses_lock(monkeypatch) -> None:
    from app.data_pipeline import job_worker
    from app.data_pipeline.job_handlers import JobExecutionResult

    queue = SimpleNamespace(
        requeue_stale_running=AsyncMock(return_value=0),
        claim_jobs=AsyncMock(
            return_value=[
                SimpleNamespace(
                    id=5,
                    attempt_count=0,
                    max_attempts=5,
                )
            ]
        ),
        mark_success=AsyncMock(),
        mark_partial=AsyncMock(return_value=False),
        mark_failure=AsyncMock(),
    )

    async def fake_execute(job) -> JobExecutionResult:
        return JobExecutionResult(
            status="partial",
            summary={"success": 9, "fail": 1},
            error="fetcher returned fail=1",
        )

    monkeypatch.setattr(job_worker, "execute_ingestion_job", fake_execute)

    result = asyncio.run(job_worker.IngestionJobWorker(queue=queue, worker_id="test-worker").run_once())

    assert result == {
        "claimed": 1,
        "success": 0,
        "partial": 0,
        "failed": 0,
        "lost_lock": 1,
    }
    queue.mark_partial.assert_awaited_once_with(
        5,
        "test-worker",
        {"success": 9, "fail": 1},
        "fetcher returned fail=1",
    )
    queue.mark_success.assert_not_awaited()
    queue.mark_failure.assert_not_awaited()


def test_worker_counts_lost_lock_when_failure_mark_loses_lock(monkeypatch) -> None:
    from app.data_pipeline import job_worker

    queue = SimpleNamespace(
        requeue_stale_running=AsyncMock(return_value=0),
        claim_jobs=AsyncMock(
            return_value=[
                SimpleNamespace(
                    id=6,
                    attempt_count=2,
                    max_attempts=5,
                )
            ]
        ),
        mark_success=AsyncMock(),
        mark_partial=AsyncMock(),
        mark_failure=AsyncMock(return_value=False),
    )

    async def fake_execute(job) -> None:
        raise RuntimeError("cninfo 599")

    monkeypatch.setattr(job_worker, "execute_ingestion_job", fake_execute)

    result = asyncio.run(job_worker.IngestionJobWorker(queue=queue, worker_id="test-worker").run_once())

    assert result == {
        "claimed": 1,
        "success": 0,
        "partial": 0,
        "failed": 0,
        "lost_lock": 1,
    }
    queue.mark_failure.assert_awaited_once_with(
        6,
        "test-worker",
        "cninfo 599",
        2,
        5,
    )
    queue.mark_success.assert_not_awaited()
    queue.mark_partial.assert_not_awaited()


def test_worker_records_timeout_error_message(monkeypatch) -> None:
    from app.data_pipeline import job_worker

    queue = SimpleNamespace(
        requeue_stale_running=AsyncMock(return_value=0),
        claim_jobs=AsyncMock(
            return_value=[
                SimpleNamespace(
                    id=7,
                    attempt_count=1,
                    max_attempts=5,
                )
            ]
        ),
        mark_success=AsyncMock(),
        mark_partial=AsyncMock(),
        mark_failure=AsyncMock(return_value=True),
    )

    async def fake_execute(job) -> None:
        await asyncio.sleep(0.05)

    monkeypatch.setattr(job_worker, "execute_ingestion_job", fake_execute)

    result = asyncio.run(
        job_worker.IngestionJobWorker(
            queue=queue,
            worker_id="test-worker",
            job_timeout_seconds=0.01,
        ).run_once()
    )

    assert result == {
        "claimed": 1,
        "success": 0,
        "partial": 0,
        "failed": 1,
        "lost_lock": 0,
    }
    queue.mark_failure.assert_awaited_once_with(
        7,
        "test-worker",
        "job timed out after 0.01s",
        1,
        5,
    )
    queue.mark_success.assert_not_awaited()
    queue.mark_partial.assert_not_awaited()
