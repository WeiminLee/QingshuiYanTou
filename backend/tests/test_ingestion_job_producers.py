"""Tests for ingestion job producers."""

from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytz


def test_enqueue_recent_cninfo_jobs_defaults_to_7_days() -> None:
    from app.data_pipeline.job_producers import enqueue_recent_cninfo_jobs
    from app.data_pipeline.job_queue import JOB_CNINFO_ANNOUNCEMENT_DATE

    queue = MagicMock()
    queue.enqueue_job = AsyncMock()
    now = pytz.timezone("Asia/Shanghai").localize(datetime(2026, 5, 23, 14, 0, 0))

    result = asyncio.run(enqueue_recent_cninfo_jobs(queue=queue, now=now))

    assert result == {"enqueued": 7}
    assert queue.enqueue_job.await_count == 7
    call_args = queue.enqueue_job.await_args_list
    assert [call.kwargs["job_key"] for call in call_args] == [
        "20260517",
        "20260518",
        "20260519",
        "20260520",
        "20260521",
        "20260522",
        "20260523",
    ]
    assert [call.kwargs["job_type"] for call in call_args] == [JOB_CNINFO_ANNOUNCEMENT_DATE] * 7
    assert call_args[-1].kwargs["payload"] == {"date": "20260523"}


def test_enqueue_irm_company_jobs_uses_stock_list(monkeypatch) -> None:
    from app.data_pipeline.job_producers import enqueue_irm_company_jobs
    from app.data_pipeline.job_queue import JOB_IRM_COMPANY

    monkeypatch.setenv("BACKFILL_SCOPE", "all")

    queue = MagicMock()
    queue.enqueue_job = AsyncMock()
    stock_codes = ["600000.SH", "000001.SZ", ""]

    result = asyncio.run(enqueue_irm_company_jobs(queue=queue, stock_codes=stock_codes))

    assert result == {"enqueued": 2}
    assert queue.enqueue_job.await_count == 2
    call_args = queue.enqueue_job.await_args_list
    assert [call.kwargs["job_key"] for call in call_args] == [
        "600000.SH",
        "000001.SZ",
    ]
    assert [call.kwargs["job_type"] for call in call_args] == [
        JOB_IRM_COMPANY,
        JOB_IRM_COMPANY,
    ]
    assert [call.kwargs["force_requeue"] for call in call_args] == [True, True]


def test_enqueue_irm_company_jobs_skips_index_like_codes(monkeypatch) -> None:
    from app.data_pipeline.job_producers import enqueue_irm_company_jobs

    monkeypatch.setenv("BACKFILL_SCOPE", "all")

    queue = MagicMock()
    queue.enqueue_job = AsyncMock()
    stock_codes = ["000001.SH", "399001.SZ", "600000.SH", "000001.SZ"]

    result = asyncio.run(enqueue_irm_company_jobs(queue=queue, stock_codes=stock_codes))

    assert result == {"enqueued": 2}
    assert [call.kwargs["job_key"] for call in queue.enqueue_job.await_args_list] == [
        "600000.SH",
        "000001.SZ",
    ]


def test_enqueue_irm_company_jobs_missing_tech_mvp_whitelist_fails_closed(monkeypatch, tmp_path) -> None:
    import pytest

    from app.data_pipeline.backfill_config import reset_settings_cache
    from app.data_pipeline.job_producers import enqueue_irm_company_jobs

    monkeypatch.setenv("BACKFILL_SCOPE", "tech_mvp")
    monkeypatch.setenv("BACKFILL_WHITELIST_FILE", str(tmp_path / "missing-tech-list.txt"))
    reset_settings_cache()

    queue = MagicMock()
    queue.enqueue_job = AsyncMock()
    stock_codes = ["600000.SH"]

    with pytest.raises(RuntimeError, match="BACKFILL_SCOPE=tech_mvp"):
        asyncio.run(enqueue_irm_company_jobs(queue=queue, stock_codes=stock_codes))

    queue.enqueue_job.assert_not_awaited()
    reset_settings_cache()
