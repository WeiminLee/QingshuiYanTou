"""Regression tests for reported production bug candidates."""

import asyncio
import concurrent.futures
import logging
from unittest.mock import AsyncMock, MagicMock, patch


def test_hunyuan_embed_uses_sync_http_client_inside_running_loop():
    """Synchronous embed must not call asyncio.run/threadpool from an event loop."""
    from app.knowledge.vector_client import HunyuanEmbedding

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [{"embedding": [0.1, 0.2, 0.3]}]}

    fake_client = MagicMock()
    fake_client.post.return_value = FakeResponse()

    async def run_inside_loop():
        model = HunyuanEmbedding(api_key="key", api_url="https://example.test/embed")
        with patch("app.knowledge.vector_client.httpx.Client", return_value=fake_client):
            with patch.object(asyncio, "run") as run_mock:
                with patch.object(concurrent.futures, "ThreadPoolExecutor") as pool_mock:
                    assert model.embed("hello") == [0.1, 0.2, 0.3]
                    run_mock.assert_not_called()
                    pool_mock.assert_not_called()

    asyncio.run(run_inside_loop())


def test_async_audit_logger_uses_asyncpg_safe_jsonb_cast():
    """Async SQLAlchemy text params must not use :param::jsonb syntax."""
    from app.logging.logger import AsyncAuditLogger

    captured = {}

    class FakeConn:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def execute(self, sql, params):
            captured["sql"] = str(sql)
            captured["params"] = params

        async def commit(self):
            captured["committed"] = True

    fake_engine = MagicMock()
    fake_engine.connect.return_value = FakeConn()

    with patch("app.logging.logger.engine", fake_engine):
        asyncio.run(AsyncAuditLogger("tests").ainfo("module", "message", key="value"))

    assert "CAST(:extra_data AS jsonb)" in captured["sql"]
    assert ":extra_data::jsonb" not in captured["sql"]
    assert captured["params"]["extra_data"] == '{"key": "value"}'
    assert captured["committed"] is True


def test_fetch_reports_logs_total_skipped_not_only_preexisting(caplog):
    """Report completion log should include duplicates returned by _save_report."""
    from app.data_pipeline.fetcher import DataFetcher

    class EmptyRows:
        def fetchall(self):
            return []

    class FakeConn:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def execute(self, *args, **kwargs):
            return EmptyRows()

    fetcher = DataFetcher()
    fetcher.audit_logger = MagicMock()
    fetcher.audit_logger.ainfo = AsyncMock()
    fetcher.data_source = MagicMock()
    fetcher.data_source.get_reports.return_value = [
        {
            "title": "重复研报",
            "inst_csname": "券商",
            "author": "分析师",
            "url": "",
            "ts_code": "600000.SH",
        }
    ]
    fetcher._save_report = AsyncMock(return_value=None)
    caplog.set_level(logging.INFO, logger="app.data_pipeline.fetcher")

    fake_engine = MagicMock()
    fake_engine.connect.return_value = FakeConn()

    with patch("app.data_pipeline.fetcher.engine", fake_engine):
        with patch("app.data_pipeline.fetcher.get_akshare_limiter") as limiter:
            limiter.return_value.wait_and_acquire = MagicMock()
            result = asyncio.run(fetcher.fetch_reports("20260522"))

    assert result == {"total": 1, "success": 0, "skipped": 1, "fail": 0}
    assert "跳过 1" in caplog.text


def test_irm_checkpoint_uses_consistent_timezone_aware_datetimes():
    """IRM checkpoint timestamps and cutoff should use the same aware timezone."""
    from app.data_pipeline.fetcher import DataFetcher

    captured_find = {}
    captured_update = {}

    class EmptyAsyncCursor:
        def __aiter__(self):
            async def iterator():
                if False:
                    yield {}

            return iterator()

    class FakeCollection:
        def find(self, query, projection):
            captured_find["cutoff"] = query["last_success_at"]["$gt"]
            return EmptyAsyncCursor()

        async def update_one(self, *args, **kwargs):
            captured_update["update"] = args[1]

    fake_db = MagicMock()
    fake_db.__getitem__.return_value = FakeCollection()

    fetcher = DataFetcher()
    with patch("app.data_pipeline.fetcher.get_mongo_db", return_value=fake_db):
        asyncio.run(fetcher._filter_irm_pending(["600000.SH"]))
        asyncio.run(fetcher._save_irm_checkpoint("600000.SH", success=True))

    update_set = captured_update["update"]["$set"]
    assert captured_find["cutoff"].tzinfo is not None
    assert update_set["last_attempt_at"].tzinfo is not None
    assert update_set["last_success_at"].tzinfo is not None
    assert captured_find["cutoff"].tzinfo.zone == "Asia/Shanghai"
    assert update_set["last_attempt_at"].tzinfo.zone == "Asia/Shanghai"
    assert update_set["last_success_at"].tzinfo.zone == "Asia/Shanghai"


def test_cls_telegraph_fetch_error_logs_warning(monkeypatch, caplog):
    from app.data_pipeline import data_source as data_source_mod
    from app.data_pipeline.data_source import DataSourceClient

    def bad_fetch(symbol):
        raise RuntimeError("cls unavailable")

    monkeypatch.setattr(data_source_mod.ak, "stock_info_global_cls", bad_fetch)
    caplog.set_level(logging.WARNING, logger="app.data_pipeline.data_source")

    assert DataSourceClient().get_cls_telegraph() == []
    assert "财联社电报" in caplog.text
    assert "cls unavailable" in caplog.text


def test_irm_checkpoint_write_failure_logs_warning(caplog):
    from app.data_pipeline.fetcher import DataFetcher

    fake_db = MagicMock()
    fake_db.__getitem__.side_effect = RuntimeError("mongo down")
    caplog.set_level(logging.WARNING, logger="app.data_pipeline.fetcher")

    with patch("app.data_pipeline.fetcher.get_mongo_db", return_value=fake_db):
        asyncio.run(DataFetcher()._save_irm_checkpoint("600000.SH", success=True))

    assert "IRM checkpoint 写入失败" in caplog.text
    assert "mongo down" in caplog.text


def test_infer_period_supports_all_quarters():
    from app.knowledge.kg_extractor import _infer_period_from_announcement

    assert _infer_period_from_announcement("", "2025年第一季度报告") == ("2025Q1", "quarterly")
    assert _infer_period_from_announcement("", "2025年第二季度报告") == ("2025Q2", "quarterly")
    assert _infer_period_from_announcement("", "2025年第三季度报告") == ("2025Q3", "quarterly")
    assert _infer_period_from_announcement("", "2025年第四季度报告") == ("2025Q4", "quarterly")


def test_rag_entity_type_vote_ignores_blank_values():
    from app.knowledge.extraction.rag_extractor import RAGExtractor

    extractor = RAGExtractor()
    result = asyncio.run(
        extractor._merge_single_entity(
            "测试公司",
            [
                {"entity_type": "", "description": "空类型", "source_id": "1"},
                {"entity_type": None, "description": "无类型", "source_id": "2"},
                {"entity_type": "Company", "description": "公司类型", "source_id": "3"},
            ],
        )
    )

    assert result["entity_type"] == "Company"


def test_safe_float_rejects_nan_and_infinity():
    from app.data_pipeline.fetcher import _safe_float

    assert _safe_float("nan") is None
    assert _safe_float(float("nan")) is None
    assert _safe_float("inf") is None
    assert _safe_float("-inf") is None
    assert _safe_float("12.5") == 12.5


def test_relation_weight_normalization_handles_bad_values():
    from app.knowledge.kg_extractor import _normalize_relation_weight

    assert _normalize_relation_weight("bad") == 0.5
    assert _normalize_relation_weight(None) == 0.5
    assert _normalize_relation_weight(float("nan")) == 0.5
    assert _normalize_relation_weight(8) == 0.8
    assert _normalize_relation_weight(0.7) == 0.7


def test_rate_limiter_singletons_are_thread_safe():
    from app.data_pipeline import rate_limiter

    originals = (
        rate_limiter._akshare_limiter,
        rate_limiter._cninfo_pdf_limiter,
        rate_limiter._cninfo_api_limiter,
        rate_limiter._akshare_async_limiter,
    )
    try:
        rate_limiter._akshare_limiter = None
        rate_limiter._cninfo_pdf_limiter = None
        rate_limiter._cninfo_api_limiter = None
        rate_limiter._akshare_async_limiter = None

        def collect(factory):
            with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
                return list(pool.map(lambda _i: factory(), range(64)))

        akshare_instances = collect(rate_limiter.get_akshare_limiter)
        pdf_instances = collect(rate_limiter.get_cninfo_pdf_limiter)
        cninfo_api_instances = collect(rate_limiter.get_cninfo_api_limiter)
        akshare_async_instances = collect(rate_limiter.get_akshare_async_limiter)

        assert len({id(item) for item in akshare_instances}) == 1
        assert len({id(item) for item in pdf_instances}) == 1
        assert len({id(item) for item in cninfo_api_instances}) == 1
        assert len({id(item) for item in akshare_async_instances}) == 1
    finally:
        (
            rate_limiter._akshare_limiter,
            rate_limiter._cninfo_pdf_limiter,
            rate_limiter._cninfo_api_limiter,
            rate_limiter._akshare_async_limiter,
        ) = originals


def test_stock_kline_fetch_failure_counts_as_fail():
    from app.data_pipeline.fetcher import DataFetcher

    fetcher = DataFetcher()
    fetcher.data_source = MagicMock()
    fetcher.data_source.get_stock_kline.side_effect = RuntimeError("baostock broken")

    result = asyncio.run(
        fetcher.fetch_stock_kline(
            "600000.SH",
            start_date="20260520",
            end_date="20260521",
        )
    )

    assert result == {"total": 0, "success": 0, "skipped": 0, "fail": 1}


def test_data_source_stock_kline_can_raise_on_api_error(monkeypatch):
    from app.data_pipeline import data_source as data_source_mod
    from app.data_pipeline.data_source import DataSourceClient

    class FakeResult:
        error_code = "100"
        error_msg = "service unavailable"

        def next(self):
            return False

    fake_bs = MagicMock()
    fake_bs.query_history_k_data_plus.return_value = FakeResult()
    fake_bs.login.return_value = None
    monkeypatch.setattr(data_source_mod, "bs", fake_bs)

    client = DataSourceClient()

    try:
        client.get_stock_kline(
            "600000.SH",
            "20260520",
            "20260521",
            raise_on_error=True,
        )
    except RuntimeError as exc:
        assert "service unavailable" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")
