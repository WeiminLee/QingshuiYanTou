from datetime import UTC, date, datetime, timezone, timedelta

import pytest

from app.readiness.schemas import SourceStatus
from app.readiness.service import (
    DataReadinessService,
    SourceDataSnapshot,
    SourceSyncSnapshot,
    build_checkpoint_query,
    build_ingestion_jobs_query,
    build_sync_query,
    build_monitor_query,
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
            "latest_attempt_at": datetime(2026, 7, 21, 1, 0, tzinfo=UTC),
            "last_error": "timeout",
        }
    )

    assert snapshot.latest_status == "failed"
    assert snapshot.latest_success_at == previous_success


def test_merge_sync_snapshots_prefers_newest_attempt_status():
    from app.readiness.service import merge_sync_snapshots

    older_ingestion_success = SourceSyncSnapshot(
        latest_success_at=datetime(2026, 7, 20, 3, 0, tzinfo=UTC),
        latest_attempt_at=datetime(2026, 7, 20, 3, 0, tzinfo=UTC),
        latest_status="success",
    )
    newer_scheduler_failure = SourceSyncSnapshot(
        latest_success_at=datetime(2026, 7, 20, 3, 0, tzinfo=UTC),
        latest_attempt_at=datetime(2026, 7, 21, 9, 0, tzinfo=UTC),
        latest_status="failed",
        last_error="scheduler failed",
    )

    merged = merge_sync_snapshots([older_ingestion_success, newer_scheduler_failure])

    assert merged.latest_status == "failed"
    assert merged.last_error == "scheduler failed"
    assert merged.latest_success_at == older_ingestion_success.latest_success_at


def test_merge_sync_snapshots_does_not_carry_old_error_after_new_success():
    from app.readiness.service import merge_sync_snapshots

    older_failure = SourceSyncSnapshot(
        latest_attempt_at=datetime(2026, 7, 20, 3, 0, tzinfo=UTC),
        latest_status="failed",
        last_error="old scheduler failed",
    )
    newer_success = SourceSyncSnapshot(
        latest_success_at=datetime(2026, 7, 21, 3, 0, tzinfo=UTC),
        latest_attempt_at=datetime(2026, 7, 21, 3, 0, tzinfo=UTC),
        latest_status="success",
    )

    merged = merge_sync_snapshots([older_failure, newer_success])

    assert merged.latest_status == "success"
    assert merged.last_error is None


def test_merge_sync_snapshots_preserves_metadata_lookup_warning_after_new_success():
    from app.readiness.service import merge_sync_snapshots

    newer_success = SourceSyncSnapshot(
        latest_success_at=datetime(2026, 7, 21, 3, 0, tzinfo=UTC),
        latest_attempt_at=datetime(2026, 7, 21, 3, 0, tzinfo=UTC),
        latest_status="success",
    )
    lookup_warning = SourceSyncSnapshot(last_error="sync job lookup failed: relation missing")

    merged = merge_sync_snapshots([newer_success, lookup_warning])

    assert merged.latest_status == "success"
    assert merged.last_error == "sync job lookup failed: relation missing"


def test_monitor_query_covers_daily_scheduler_task_names():
    query, params = build_monitor_query("kline")

    sql = str(query).lower()
    assert "sync_task_status" in sql
    assert "task_name" in sql
    assert "kline" in params.values()


def test_monitor_query_covers_enqueue_and_news_scheduler_task_names():
    _, ann_params = build_monitor_query("announcement")
    _, irm_params = build_monitor_query("irm")
    _, news_params = build_monitor_query("news")

    assert "cninfo_enqueue" in ann_params.values()
    assert "irm_enqueue" in irm_params.values()
    assert "news_sync" in news_params.values()


def test_ingestion_job_query_covers_durable_queue_types():
    query, params = build_ingestion_jobs_query("announcement")

    sql = str(query).lower()
    assert "ingestion_jobs" in sql
    assert "cninfo_announcement_date" in params.values()
    assert "failed" in sql
    assert "dead" in sql


def test_checkpoint_query_covers_acquisition_checkpoint_sources():
    query, params = build_checkpoint_query("announcement")

    sql = str(query).lower()
    assert "ingestion_checkpoints" in sql
    assert "cninfo" in params.values()
    assert "announcements_history" in params.values()


def test_shanghai_midnight_uses_local_business_date():
    summary = DataReadinessService(repository=FakeRepository()).build_summary(
        now=datetime(2026, 7, 22, 0, 30, tzinfo=timezone(timedelta(hours=8))),
        sources=[
            SourceDataSnapshot(
                source="announcement",
                latest_data_date=date(2026, 7, 20),
                sync=SourceSyncSnapshot(),
            )
        ],
    )

    item = summary.sources[0]
    assert item.lag_days == 2
    assert item.status == SourceStatus.STALE


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
async def test_readiness_degrades_fresh_data_when_latest_sync_failed():
    repo = FakeRepository(
        data={"announcement": date(2026, 7, 20)},
        sync={
            "announcement": SourceSyncSnapshot(
                latest_success_at=datetime(2026, 7, 20, 22, 0, tzinfo=UTC),
                latest_status="failed",
                last_error="latest acquisition failed",
            )
        },
    )
    service = DataReadinessService(repository=repo)

    item = await service.get_source("announcement", now=datetime(2026, 7, 21, 9, 0, tzinfo=UTC))

    assert item is not None
    assert item.status == SourceStatus.STALE
    assert item.last_error == "latest acquisition failed"
    assert "最近同步失败" in item.recommendation


@pytest.mark.asyncio
async def test_readiness_recommendation_mentions_sync_metadata_warning():
    repo = FakeRepository(
        data={"news": date(2026, 7, 21)},
        sync={"news": SourceSyncSnapshot(last_error="sync metadata lookup failed: relation missing")},
    )
    service = DataReadinessService(repository=repo)

    item = await service.get_source("news", now=datetime(2026, 7, 21, 9, 0, tzinfo=UTC))

    assert item is not None
    assert item.status == SourceStatus.FRESH
    assert "同步元数据查询失败" in item.recommendation


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
