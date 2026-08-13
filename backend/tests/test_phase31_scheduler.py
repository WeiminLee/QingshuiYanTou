"""Phase 31 E / F / H — scheduler 修复验证"""

import asyncio
import inspect
from datetime import datetime
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

        assert any("test_job_unit" in rec.message for rec in caplog.records), (
            "task_done_callback 必须输出含任务名的 error log"
        )


class TestTradingHoursGate:
    """H _is_trading_hours 工作日 + 9:00-11:30 / 13:00-15:00"""

    def test_weekend_returns_false(self):
        from app.data_pipeline.scheduler import TRADING_TZ, _is_trading_hours

        with patch("app.data_pipeline.scheduler.datetime") as mock_dt:
            # 2026-05-17 是周日
            mock_dt.now.return_value = datetime(2026, 5, 17, 10, 0, tzinfo=TRADING_TZ)
            assert _is_trading_hours() is False

    def test_weekday_morning_returns_true(self):
        from app.data_pipeline.scheduler import TRADING_TZ, _is_trading_hours

        with patch("app.data_pipeline.scheduler.datetime") as mock_dt:
            # 2026-05-13 是周三 10:00
            mock_dt.now.return_value = datetime(2026, 5, 13, 10, 0, tzinfo=TRADING_TZ)
            assert _is_trading_hours() is True

    def test_weekday_lunch_returns_false(self):
        from app.data_pipeline.scheduler import TRADING_TZ, _is_trading_hours

        with patch("app.data_pipeline.scheduler.datetime") as mock_dt:
            # 2026-05-13 周三 12:00（午间休市）
            mock_dt.now.return_value = datetime(2026, 5, 13, 12, 0, tzinfo=TRADING_TZ)
            assert _is_trading_hours() is False

    def test_weekday_afternoon_returns_true(self):
        from app.data_pipeline.scheduler import TRADING_TZ, _is_trading_hours

        with patch("app.data_pipeline.scheduler.datetime") as mock_dt:
            # 2026-05-13 周三 14:00
            mock_dt.now.return_value = datetime(2026, 5, 13, 14, 0, tzinfo=TRADING_TZ)
            assert _is_trading_hours() is True


class TestBatchReindexScheduler:
    """D-07 batch reindex 目前未注册：reindex_missing_vectors 尚未实现，
    注册它会每晚向 monitor/钉钉误报 SUCCESS(count=0) 假成功（详见 scheduler.start）。"""

    def test_batch_reindex_job_not_registered(self):
        from app.data_pipeline import scheduler as sched

        scheduler = sched.Scheduler()

        with patch.object(sched.AsyncIOScheduler, "start", return_value=None):
            scheduler.start()

        # 未实现前不应注册该任务，避免假成功通知；待 reindex_missing_vectors 落地后再启用
        job = scheduler._scheduler.get_job("batch_reindex_daily")
        assert job is None

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


def test_news_scheduler_records_monitor_status(monkeypatch):
    from app.data_pipeline import monitor
    from app.data_pipeline import scheduler as scheduler_mod

    class FakeNewsService:
        async def fetch_and_save(self):
            return {"fetched": 4, "inserted": 3, "skipped": 1}

    monkeypatch.setattr(
        "app.data_pipeline.services.news_service.get_news_service",
        lambda: FakeNewsService(),
    )
    monkeypatch.setattr(monitor, "init_monitor", AsyncMock())
    monkeypatch.setattr(monitor, "record_task_start", AsyncMock())
    monkeypatch.setattr(monitor, "record_task_result", AsyncMock())

    asyncio.run(scheduler_mod._run_news_job())

    monitor.record_task_start.assert_awaited_once_with("news_sync")
    args = monitor.record_task_result.await_args.args
    kwargs = monitor.record_task_result.await_args.kwargs
    assert args[0] == "news_sync"
    assert kwargs["total"] == 4
    assert kwargs["success"] == 3
    assert kwargs["skipped"] == 1


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
    monkeypatch.setattr(sched, "_run_news_job", fake_job)

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

    # _fire_all_once 启动补漏任务数：report/concept/kline/irm/cninfo/ingestion/sync_stocks/news = 8
    assert created_count == 8


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
    ingestion_worker_drain = next(job for job in jobs if job["id"] == "ingestion_worker_drain")

    assert "cninfo_enqueue_daily" in ids
    assert "irm_enqueue_daily" in ids
    assert "ingestion_worker_drain" in ids
    assert "cninfo_daily" not in ids
    assert "irm_daily" not in ids
    assert ingestion_worker_drain["max_instances"] == 1
    assert ingestion_worker_drain["coalesce"] is True


def test_kline_job_passes_scope_from_settings(monkeypatch):
    """_run_kline_job() 必须将 load_backfill_settings().scope 传给 sync_daily。"""
    from app.data_pipeline import scheduler as scheduler_mod

    received = {}

    async def fake_sync_daily(*, scope):
        received["scope"] = scope
        return {"ok": 1, "skip": 0, "fail": 0, "saved": 1, "total": 1}

    monkeypatch.setattr(
        "scripts.sync_daily_baostock.sync_daily",
        fake_sync_daily,
        raising=False,
    )

    import app.data_pipeline.monitor as monitor
    monkeypatch.setattr(monitor, "init_monitor", AsyncMock())
    monkeypatch.setattr(monitor, "record_task_start", AsyncMock())
    monkeypatch.setattr(monitor, "record_task_result", AsyncMock())

    import app.data_pipeline.dingtalk as dt
    monkeypatch.setattr(dt, "notify_task_start", AsyncMock())
    monkeypatch.setattr(dt, "notify_task_success", AsyncMock())
    monkeypatch.setattr(dt, "notify_task_failed", AsyncMock())

    # 设置 BACKFILL_SCOPE=all
    monkeypatch.setenv("BACKFILL_SCOPE", "all")

    asyncio.run(scheduler_mod._run_kline_job())

    assert received["scope"] == "all"
