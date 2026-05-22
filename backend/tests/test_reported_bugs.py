"""Regression tests for reported production bug candidates."""
import asyncio
import concurrent.futures
import logging
from datetime import timezone
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


def test_irm_checkpoint_uses_timezone_aware_utc():
    """IRM checkpoint timestamps and cutoff should be UTC-aware datetimes."""
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

    assert captured_find["cutoff"].tzinfo is timezone.utc
    update_set = captured_update["update"]["$set"]
    assert update_set["last_attempt_at"].tzinfo is timezone.utc
    assert update_set["last_success_at"].tzinfo is timezone.utc


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
