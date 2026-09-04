"""Regression coverage for cloud-only PDF metadata ingestion."""

from __future__ import annotations

import asyncio
from datetime import date
from unittest.mock import AsyncMock, MagicMock

from app.data_pipeline.fetcher import DataFetcher
from app.data_pipeline.job_queue import JOB_PDF_DOWNLOAD


class _FakeResult:
    def __init__(self, row: object | None = None) -> None:
        self._row = row

    def fetchone(self) -> object | None:
        return self._row


class _FakeBegin:
    async def __aenter__(self) -> "_FakeConn":
        return _FakeConn()

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None


class _FakeConn:
    async def execute(self, *args: object, **kwargs: object) -> _FakeResult:
        return _FakeResult(object())


class _FakeEngine:
    def begin(self) -> _FakeBegin:
        return _FakeBegin()


def test_fetcher_announcement_save_enqueues_pdf_job_not_direct_download(monkeypatch) -> None:
    import app.data_pipeline.fetcher as fetcher_module

    fetcher = DataFetcher()
    fetcher.job_queue = MagicMock()
    fetcher.job_queue.enqueue_job = AsyncMock()

    fake_eng = _FakeEngine()
    monkeypatch.setattr(fetcher_module, "engine", fake_eng)

    patched_download = AsyncMock(side_effect=RuntimeError("should not be called"))
    monkeypatch.setattr("app.data_pipeline.fetcher.FileStorage.download_report_external", patched_download)

    rec = {
        "ann_date": "20260101",
        "title": "年度报告",
        "ts_code": "600000.SH",
        "name": "测试公司",
        "url": "https://example.invalid/notice.pdf",
    }

    result = asyncio.run(
        fetcher._save_minishare_ann(
            rec=rec,
            ts_code="600000.SH",
            enqueue_download=True,
        )
    )

    assert result is True
    assert fetcher.job_queue.enqueue_job.await_count == 1
    call = fetcher.job_queue.enqueue_job.await_args
    assert call is not None
    assert call.args[0] == JOB_PDF_DOWNLOAD
    assert call.args[3] == 25
    assert call.args[4] == 8
    payload = call.args[2]
    assert payload["source_url"] == rec["url"]
    assert payload["source_type"] == "minishare_announcements"
    assert payload["stock_code"] == "600000.SH"
    assert payload["publish_date"] == date(2026, 1, 1).isoformat()
    assert patched_download.await_count == 0


def test_fetcher_announcement_job_path_is_cloud_only(monkeypatch) -> None:
    fetcher = DataFetcher()
    fetcher._candidate_pool_cache = {"600000.SH"}
    fetcher._save_minishare_ann = AsyncMock(return_value=True)

    mock_client = MagicMock()
    mock_client.anns_available = True
    mock_client.get_announcements.return_value = [
        {
            "ann_date": "20260101",
            "title": "年度报告",
            "ts_code": "600000.SH",
            "name": "测试公司",
            "url": "https://example.invalid/notice.pdf",
        }
    ]
    fetcher.minishare_client = mock_client

    patched_download = AsyncMock(side_effect=RuntimeError("should not be called"))
    monkeypatch.setattr("app.data_pipeline.fetcher.FileStorage.download_report_external", patched_download)

    result = asyncio.run(fetcher.fetch_minishare_announcements(ann_date="20260101"))
    assert result["success"] == 1
    assert result["fail"] == 0
    fetcher._save_minishare_ann.assert_awaited_once()
    _, call_kwargs = fetcher._save_minishare_ann.await_args
    assert call_kwargs["enqueue_download"] is True
    assert patched_download.await_count == 0
