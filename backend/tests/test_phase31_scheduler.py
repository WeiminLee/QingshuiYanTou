"""Phase 31 E / F / H — scheduler 修复验证"""
import asyncio
import inspect
from datetime import datetime, time
from unittest.mock import AsyncMock, MagicMock, patch
import pytest


class TestMaxAttempts:
    """E MAX_ATTEMPTS = 3（原始 + 2 次重试）"""

    def test_constant_equals_3(self):
        from app.data_pipeline.scheduler import MAX_ATTEMPTS
        assert MAX_ATTEMPTS == 3

    @pytest.mark.asyncio
    async def test_retry_3_attempts(self):
        from app.data_pipeline import scheduler as sched

        call_count = {"n": 0}

        async def always_fails():
            call_count["n"] += 1
            raise RuntimeError("boom")

        async def no_sleep(_s):
            return None

        with patch.object(sched.asyncio, "sleep", new=no_sleep):
            result = await sched._run_with_retry(always_fails, "test")
            assert result is False
            assert call_count["n"] == sched.MAX_ATTEMPTS


class TestFireAllOnceCallback:
    """F _fire_all_once 异常 callback 触发 error log"""

    def test_task_exception_logged(self, caplog):
        import logging
        from app.data_pipeline import scheduler as sched

        async def bad_job():
            raise RuntimeError("startup fail")

        async def run_case():
            caplog.set_level(logging.ERROR, logger="app.data_pipeline.scheduler")
            task = asyncio.create_task(bad_job(), name="test_job_unit")
            task.add_done_callback(sched._task_done_callback)

            with pytest.raises(RuntimeError):
                await task

            # 让 callback 有机会执行
            for _ in range(5):
                await asyncio.sleep(0)

        asyncio.run(run_case())

        assert any("test_job_unit" in rec.message for rec in caplog.records), \
            "task_done_callback 必须输出含任务名的 error log"


class TestTradingHoursGate:
    """H _is_trading_hours 工作日 + 9:00-11:30 / 13:00-15:00"""

    def test_weekend_returns_false(self):
        from app.data_pipeline.scheduler import _is_trading_hours, TRADING_TZ
        with patch("app.data_pipeline.scheduler.datetime") as mock_dt:
            # 2026-05-17 是周日
            mock_dt.now.return_value = datetime(2026, 5, 17, 10, 0, tzinfo=TRADING_TZ)
            assert _is_trading_hours() is False

    def test_weekday_morning_returns_true(self):
        from app.data_pipeline.scheduler import _is_trading_hours, TRADING_TZ
        with patch("app.data_pipeline.scheduler.datetime") as mock_dt:
            # 2026-05-13 是周三 10:00
            mock_dt.now.return_value = datetime(2026, 5, 13, 10, 0, tzinfo=TRADING_TZ)
            assert _is_trading_hours() is True

    def test_weekday_lunch_returns_false(self):
        from app.data_pipeline.scheduler import _is_trading_hours, TRADING_TZ
        with patch("app.data_pipeline.scheduler.datetime") as mock_dt:
            # 2026-05-13 周三 12:00（午间休市）
            mock_dt.now.return_value = datetime(2026, 5, 13, 12, 0, tzinfo=TRADING_TZ)
            assert _is_trading_hours() is False

    def test_weekday_afternoon_returns_true(self):
        from app.data_pipeline.scheduler import _is_trading_hours, TRADING_TZ
        with patch("app.data_pipeline.scheduler.datetime") as mock_dt:
            # 2026-05-13 周三 14:00
            mock_dt.now.return_value = datetime(2026, 5, 13, 14, 0, tzinfo=TRADING_TZ)
            assert _is_trading_hours() is True


class TestBatchReindexScheduler:
    """D-07 batch reindex is scheduled nightly, not dispatched at startup."""

    def test_batch_reindex_job_registered_at_0300(self):
        from app.data_pipeline import scheduler as sched

        scheduler = sched.Scheduler()

        with patch.object(sched.AsyncIOScheduler, "start", return_value=None):
            scheduler.start()

        job = scheduler._scheduler.get_job("batch_reindex_daily")
        assert job is not None

        trigger_text = str(job.trigger)
        assert f"hour='{sched.BATCH_REINDEX_HOUR}'" in trigger_text
        assert f"minute='{sched.BATCH_REINDEX_MINUTE}'" in trigger_text
        assert str(job.trigger.timezone) == sched.TIMEZONE

    def test_run_now_does_not_dispatch_batch_reindex(self):
        from app.data_pipeline import scheduler as sched

        source = inspect.getsource(sched.Scheduler._fire_all_once)

        assert "_run_batch_reindex_job" not in source
        assert "batch_reindex_startup" not in source


def test_cninfo_scheduler_enqueues_recent_jobs(monkeypatch):
    from app.data_pipeline import monitor
    from app.data_pipeline import scheduler as scheduler_mod

    called = {}

    async def fake_enqueue_recent_cninfo_jobs(*, days):
        called["days"] = days
        return {"enqueued": 3}

    monkeypatch.setattr(
        scheduler_mod,
        "enqueue_recent_cninfo_jobs",
        fake_enqueue_recent_cninfo_jobs,
        raising=False,
    )
    monkeypatch.setattr(monitor, "init_monitor", AsyncMock())
    monkeypatch.setattr(monitor, "record_task_start", AsyncMock())
    monkeypatch.setattr(monitor, "record_task_result", AsyncMock())

    asyncio.run(scheduler_mod._run_cninfo_enqueue_job())

    assert called == {"days": 7}


def test_irm_scheduler_enqueues_company_jobs(monkeypatch):
    from app.data_pipeline import monitor
    from app.data_pipeline import scheduler as scheduler_mod

    called = {"count": 0}

    async def fake_enqueue_irm_company_jobs():
        called["count"] += 1
        return {"enqueued": 5}

    monkeypatch.setattr(
        scheduler_mod,
        "enqueue_irm_company_jobs",
        fake_enqueue_irm_company_jobs,
        raising=False,
    )
    monkeypatch.setattr(monitor, "init_monitor", AsyncMock())
    monkeypatch.setattr(monitor, "record_task_start", AsyncMock())
    monkeypatch.setattr(monitor, "record_task_result", AsyncMock())

    asyncio.run(scheduler_mod._run_irm_enqueue_job())

    assert called == {"count": 1}


def test_fire_all_once_uses_running_loop(monkeypatch):
    from app.data_pipeline import scheduler as sched

    created = []
    created_count = None

    async def fake_job():
        return None

    monkeypatch.setattr(sched, "_run_report_job", fake_job)
    monkeypatch.setattr(sched, "_run_concept_job", fake_job)
    monkeypatch.setattr(sched, "_run_kline_job", fake_job)
    monkeypatch.setattr(sched, "_run_irm_enqueue_job", fake_job)
    monkeypatch.setattr(sched, "_run_cninfo_enqueue_job", fake_job)
    monkeypatch.setattr(sched, "_run_ingestion_worker_job", fake_job)
    monkeypatch.setattr(sched, "_run_sync_stocks_job", fake_job)

    async def run_case():
        nonlocal created_count
        loop = asyncio.get_running_loop()
        original_create_task = loop.create_task

        def tracking_create_task(coro, *, name=None, context=None):
            task = original_create_task(coro, name=name, context=context)
            created.append(task)
            return task

        monkeypatch.setattr(loop, "create_task", tracking_create_task)
        get_event_loop_mock = MagicMock(side_effect=RuntimeError("deprecated path used"))
        monkeypatch.setattr(
            sched.asyncio,
            "get_event_loop",
            get_event_loop_mock,
        )
        sched.Scheduler(run_now=False)._fire_all_once()
        await asyncio.gather(*created)
        created_count = len(created)
        get_event_loop_mock.assert_not_called()

    asyncio.run(run_case())

    assert created_count == 7


def test_ingestion_worker_job_drains_once(monkeypatch):
    from app.data_pipeline import scheduler as scheduler_mod

    calls = {}

    class FakeWorker:
        def __init__(self, *, job_timeout_seconds):
            calls["job_timeout_seconds"] = job_timeout_seconds

        async def run_once(self, *, limit):
            calls["limit"] = limit
            return {"processed": 2}

    monkeypatch.setattr(scheduler_mod, "IngestionJobWorker", FakeWorker, raising=False)

    asyncio.run(scheduler_mod._run_ingestion_worker_job())

    assert calls == {"job_timeout_seconds": 300, "limit": 5}


def test_scheduler_registers_ingestion_worker_drain(monkeypatch):
    from app.data_pipeline import scheduler as scheduler_mod

    jobs = []

    class FakeScheduler:
        def __init__(self, *, timezone):
            self.timezone = timezone

        def add_job(self, _func, _trigger, **kwargs):
            jobs.append(kwargs)

        def start(self):
            return None

    monkeypatch.setattr(scheduler_mod, "AsyncIOScheduler", FakeScheduler)

    scheduler_mod.Scheduler(run_now=False).start()

    ids = [job["id"] for job in jobs]
    ingestion_worker_drain = next(
        job for job in jobs if job["id"] == "ingestion_worker_drain"
    )

    assert "cninfo_enqueue_daily" in ids
    assert "irm_enqueue_daily" in ids
    assert "ingestion_worker_drain" in ids
    assert "cninfo_daily" not in ids
    assert "irm_daily" not in ids
    assert ingestion_worker_drain["max_instances"] == 1
    assert ingestion_worker_drain["coalesce"] is True
