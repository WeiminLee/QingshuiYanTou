"""Phase 31 E / F / H — scheduler 修复验证"""
import asyncio
import inspect
from datetime import datetime, time
from unittest.mock import MagicMock, patch
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

    @pytest.mark.asyncio
    async def test_task_exception_logged(self, caplog):
        import logging
        from app.data_pipeline import scheduler as sched

        async def bad_job():
            raise RuntimeError("startup fail")

        caplog.set_level(logging.ERROR, logger="app.data_pipeline.scheduler")
        task = asyncio.create_task(bad_job(), name="test_job_unit")
        task.add_done_callback(sched._task_done_callback)

        with pytest.raises(RuntimeError):
            await task

        # 让 callback 有机会执行
        for _ in range(5):
            await asyncio.sleep(0)

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
