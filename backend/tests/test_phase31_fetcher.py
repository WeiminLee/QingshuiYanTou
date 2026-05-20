"""Phase 31 D-A2..A5 / D-D2 / G / I — fetcher 测试占位

占位测试 — Wave 1+ 各 plan 完成实现后启用。
"""
import pytest


class TestFetchAllStocksConcurrency:
    """D-A2 semaphore 限并发数常量在合理范围"""

    def test_concurrency_in_reasonable_range(self):
        from app.data_pipeline.fetcher import STOCK_KLINE_CONCURRENCY
        assert 4 <= STOCK_KLINE_CONCURRENCY <= 16


class TestBackfillWindow:
    """D-A5 首次回填窗口 = 30 天"""

    def test_backfill_30_days(self):
        from app.data_pipeline.fetcher import STOCK_KLINE_BACKFILL_DAYS
        assert STOCK_KLINE_BACKFILL_DAYS == 30


@pytest.mark.integration
class TestSaveStockKline:
    """D-A3 _save_stock_kline 写 daily_data"""

    @pytest.mark.asyncio
    async def test_save_stock_kline_upsert(self):
        from app.data_pipeline.fetcher import DataFetcher
        fetcher = DataFetcher()
        rec = {
            "date": "2026-05-12", "open": "10.0", "high": "10.5",
            "low": "9.8", "close": "10.2", "preclose": "10.0",
            "volume": "1000000", "amount": "10200000",
            "pctChg": "2.0", "tradestatus": "1", "isST": "0",
        }
        saved = await fetcher._save_stock_kline("600000.SH", "20260512", rec)
        assert saved is True or saved is None


class TestAkshareThrottleApplied:
    """D-D2 fetcher 3 处 akshare 调用前必须 await wait_and_acquire"""

    @pytest.mark.asyncio
    async def test_fetch_reports_calls_akshare_limiter(self):
        from unittest.mock import MagicMock, patch
        from app.data_pipeline.fetcher import DataFetcher

        fetcher = DataFetcher()
        mock_limiter = MagicMock()
        mock_limiter.wait_and_acquire = MagicMock()
        # data_source.get_reports 返回空 list，跳过后续 for 循环
        fetcher.data_source = MagicMock()
        fetcher.data_source.get_reports = MagicMock(return_value=[])

        with patch(
            "app.data_pipeline.fetcher.get_akshare_limiter",
            return_value=mock_limiter,
        ):
            await fetcher.fetch_reports(trade_date="20260501")
        assert mock_limiter.wait_and_acquire.called, \
            "fetch_reports 必须在调用 akshare 前 await wait_and_acquire"

    @pytest.mark.asyncio
    async def test_fetch_irm_worker_calls_akshare_limiter(self):
        from unittest.mock import MagicMock, patch, AsyncMock
        from app.data_pipeline.fetcher import DataFetcher

        fetcher = DataFetcher()
        mock_limiter = MagicMock()
        mock_limiter.wait_and_acquire = MagicMock()
        fetcher.data_source = MagicMock()
        fetcher.data_source.get_stocks_basic = MagicMock(return_value=[])
        fetcher.data_source.get_irm = MagicMock(return_value=[])

        # Phase 31 I: patch _filter_irm_pending to avoid mongo mock complexity
        fetcher._filter_irm_pending = AsyncMock(return_value=["600000.SH"])
        fetcher._ensure_irm_checkpoint_index = AsyncMock()

        with patch(
            "app.data_pipeline.fetcher.get_akshare_limiter",
            return_value=mock_limiter,
        ):
            # 手动传一只代码，绕过 get_stocks_basic
            await fetcher.fetch_irm(ts_codes=["600000.SH"])
        assert mock_limiter.wait_and_acquire.called

    @pytest.mark.asyncio
    async def test_fetch_concept_calls_akshare_limiter(self):
        import sys
        from unittest.mock import MagicMock
        import pandas as pd
        import app.data_pipeline.fetcher as fetcher_mod
        from app.data_pipeline.fetcher import fetch_concept

        mock_limiter = MagicMock()
        mock_limiter.wait_and_acquire = MagicMock()

        # akshare 是在 fetch_concept 函数内部动态 import 的
        # 直接操作 sys.modules 来拦截 import 语句
        mock_ak = MagicMock()
        mock_ak.stock_zt_pool_strong_em = MagicMock(return_value=pd.DataFrame())

        orig_akshare = sys.modules.get("akshare")
        orig_get_limiter = fetcher_mod.get_akshare_limiter
        sys.modules["akshare"] = mock_ak
        fetcher_mod.get_akshare_limiter = lambda: mock_limiter

        try:
            await fetch_concept()
        finally:
            if orig_akshare is not None:
                sys.modules["akshare"] = orig_akshare
            elif "akshare" in sys.modules:
                del sys.modules["akshare"]
            fetcher_mod.get_akshare_limiter = orig_get_limiter

        assert mock_limiter.wait_and_acquire.called, \
            "fetch_concept 必须在调用 akshare 前 await wait_and_acquire"


@pytest.mark.integration
class TestReportSkipExisting:
    """G fetch_reports EXISTS 预查询跳过已存在 ann_id（integration - 需真实 PG）"""

    @pytest.mark.asyncio
    async def test_skip_existing_ann_id(self):
        """需要 PostgreSQL，手动 -m integration 才跑。"""
        from app.data_pipeline.fetcher import DataFetcher
        fetcher = DataFetcher()
        # smoke: 至少不抛异常。真实验证见 Phase Gate 的 manual 触发。
        result = await fetcher.fetch_reports(trade_date="20010101")  # 远古日期，reports 为空
        assert "skipped" in result
        assert "success" in result


class TestIrmCheckpointFilter:
    """I MongoDB checkpoint 20 小时内跳过"""

    @pytest.mark.asyncio
    async def test_filter_skips_recent_success(self):
        from unittest.mock import MagicMock, patch
        from app.data_pipeline.fetcher import DataFetcher

        fetcher = DataFetcher()

        # 构造 mongo mock：ts_code "600000.SH" 在 20h 窗口内 success
        mock_cursor = MagicMock()

        async def _aiter(_self):
            for doc in [{"ts_code": "600000.SH"}]:
                yield doc

        # motor AsyncIOMotorCursor 是 async iter；给它一个 __aiter__
        mock_cursor.__aiter__ = lambda self=mock_cursor: _aiter(self)

        mock_collection = MagicMock()
        mock_collection.find = MagicMock(return_value=mock_cursor)

        mock_db = MagicMock()
        mock_db.__getitem__ = MagicMock(return_value=mock_collection)

        with patch("app.data_pipeline.fetcher.get_mongo_db", return_value=mock_db):
            pending = await fetcher._filter_irm_pending(["600000.SH", "600001.SH"])
            assert "600000.SH" not in pending
            assert "600001.SH" in pending
