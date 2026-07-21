from datetime import UTC, date, datetime

import pytest

from app.readiness.schemas import SourceStatus
from app.readiness.service import (
    DataReadinessService,
    SourceDataSnapshot,
    SourceSyncSnapshot,
    build_sync_query,
    count_weekday_lag,
    format_readiness_for_agent,
    source_sync_snapshot_from_row,
)


class FakeRepository:
    def __init__(self, data=None, sync=None):
        self.data = data or {}
        self.sync = sync or {}

    async def get_latest_data_date(self, source: str):
        return self.data.get(source)

    async def get_sync_snapshot(self, source: str):
        return self.sync.get(source, SourceSyncSnapshot())


def test_count_weekday_lag_skips_weekend():
    assert count_weekday_lag(date(2026, 7, 17), date(2026, 7, 20)) == 1


def test_irm_sync_query_targets_acquisition_tasks_only():
    query, params = build_sync_query("irm")

    sql = str(query).lower()
    assert "kg_extract" not in sql
    assert "%irm%" not in params.values()
    assert {"qa_fetch", "irm_daily_backfill"}.issubset(params.values())
    assert "lower(source) =" in sql
    assert "lower(task_name) =" in sql


def test_sync_snapshot_preserves_previous_success_after_latest_failure():
    previous_success = datetime(2026, 7, 20, 22, 0, tzinfo=UTC)
    snapshot = source_sync_snapshot_from_row(
        {
            "status": "failed",
            "completed_at": datetime(2026, 7, 21, 1, 0, tzinfo=UTC),
            "latest_success_at": previous_success,
            "last_error": "timeout",
        }
    )

    assert snapshot.latest_status == "failed"
    assert snapshot.latest_success_at == previous_success


@pytest.mark.asyncio
async def test_readiness_marks_fresh_source():
    repo = FakeRepository(
        data={"announcement": date(2026, 7, 20)},
        sync={"announcement": SourceSyncSnapshot(latest_success_at=datetime(2026, 7, 20, 23, 0, tzinfo=UTC))},
    )
    service = DataReadinessService(repository=repo)

    item = await service.get_source("announcement", now=datetime(2026, 7, 21, 9, 0, tzinfo=UTC))

    assert item is not None
    assert item.source == "announcement"
    assert item.status == SourceStatus.FRESH
    assert item.latest_data_date == "2026-07-20"
    assert item.lag_days == 1
    assert item.recommendation == "数据处于日级可靠窗口内。"


@pytest.mark.asyncio
async def test_readiness_marks_missing_source():
    service = DataReadinessService(repository=FakeRepository())

    item = await service.get_source("news", now=datetime(2026, 7, 21, 9, 0, tzinfo=UTC))

    assert item is not None
    assert item.status == SourceStatus.MISSING
    assert item.latest_data_date is None
    assert item.recommendation == "本地没有该数据源记录，需要先完成同步。"


@pytest.mark.asyncio
async def test_readiness_marks_failed_when_stale_and_latest_sync_failed():
    repo = FakeRepository(
        data={"irm": date(2026, 7, 10)},
        sync={
            "irm": SourceSyncSnapshot(
                latest_success_at=datetime(2026, 7, 10, 22, 0, tzinfo=UTC),
                latest_status="failed",
                last_error="timeout while fetching irm",
            )
        },
    )
    service = DataReadinessService(repository=repo)

    item = await service.get_source("irm", now=datetime(2026, 7, 21, 9, 0, tzinfo=UTC))

    assert item is not None
    assert item.status == SourceStatus.FAILED
    assert item.last_error == "timeout while fetching irm"
    assert "同步失败" in item.recommendation


@pytest.mark.asyncio
async def test_overall_status_degraded_for_stale_required_source():
    repo = FakeRepository(
        data={
            "kline": date(2026, 7, 20),
            "announcement": date(2026, 7, 19),
            "irm": date(2026, 7, 20),
            "news": date(2026, 7, 20),
            "research_report": date(2026, 7, 19),
        }
    )
    service = DataReadinessService(repository=repo)

    summary = await service.get_all(now=datetime(2026, 7, 21, 9, 0, tzinfo=UTC))

    assert summary.overall_status == "degraded"
    assert any(s.source == "announcement" and s.status == SourceStatus.STALE for s in summary.sources)


def test_format_readiness_for_agent_lists_boundaries():
    summary = DataReadinessService(repository=FakeRepository()).build_summary(
        now=datetime(2026, 7, 21, 9, 0, tzinfo=UTC),
        sources=[
            SourceDataSnapshot(
                source="announcement",
                latest_data_date=date(2026, 7, 19),
                sync=SourceSyncSnapshot(),
            )
        ],
    )

    text = format_readiness_for_agent(summary)

    assert "<data_readiness>" in text
    assert "overall_status=degraded" in text
    assert "announcement: stale" in text
    assert "基于截至" in text
