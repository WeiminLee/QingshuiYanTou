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
class TestAkshareThrottleApplied:
    """D-D2 fetcher 3 处 akshare 调用前必须 await wait_and_acquire"""
    @pytest.mark.integration
    def test_fetch_irm_worker_uses_minishare_only(self):
        import asyncio
        from unittest.mock import AsyncMock, MagicMock

        from app.data_pipeline.fetcher import DataFetcher

        fetcher = DataFetcher()
        fetcher.data_source = MagicMock()
        fetcher.data_source.get_irm.side_effect = AssertionError("IRM must not use akshare")
        fetcher.minishare_client = MagicMock()
        fetcher.minishare_client.irm_available = True
        fetcher.minishare_client.get_irm.return_value = []

        # Phase 31 I: patch _filter_irm_pending to avoid mongo mock complexity
        fetcher._filter_irm_pending = AsyncMock(return_value=["600000.SH"])
        fetcher._ensure_irm_checkpoint_index = AsyncMock()

        asyncio.run(fetcher.fetch_irm(ts_codes=["600000.SH"]))

        fetcher.minishare_client.get_irm.assert_called_once()
        assert not fetcher.data_source.get_irm.called

    @pytest.mark.integration
    def test_fetch_irm_counts_data_source_exception_as_failure(self):
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch

        from app.data_pipeline.fetcher import DataFetcher

        fetcher = DataFetcher()
        fetcher.minishare_client = MagicMock()
        fetcher.minishare_client.irm_available = True
        fetcher.minishare_client.get_irm = MagicMock(side_effect=RuntimeError("irm api bad response"))
        fetcher._filter_irm_pending = AsyncMock(return_value=["600000.SH"])
        fetcher._ensure_irm_checkpoint_index = AsyncMock()
        fetcher._save_irm_checkpoint = AsyncMock()
        result = asyncio.run(fetcher.fetch_irm(ts_codes=["600000.SH"]))

        assert result["total"] == 1
        assert result["fail"] == 1
        assert result["success"] == 0
        assert result["last_error"] == "irm api bad response"

    def test_fetch_irm_without_minishare_is_explicit_failure(self):
        import asyncio
        from unittest.mock import AsyncMock, MagicMock

        from app.data_pipeline.fetcher import DataFetcher

        fetcher = DataFetcher()
        fetcher.minishare_client = MagicMock()
        fetcher.minishare_client.irm_available = False
        fetcher._filter_irm_pending = AsyncMock(return_value=["600000.SH"])
        fetcher._ensure_irm_checkpoint_index = AsyncMock()

        result = asyncio.run(fetcher.fetch_irm(ts_codes=["600000.SH"]))

        assert result["fail"] == 1
        assert "MINISHARE_IRM_TOKEN" in result["last_error"]
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
