"""Regression tests for the cloud data pipeline repair work."""

from __future__ import annotations

import asyncio
from datetime import date, datetime
from unittest.mock import AsyncMock


class _ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar(self):
        return self.value


class _RunIdResult:
    def __init__(self, value):
        self.value = value

    def fetchone(self):
        return (self.value,)


class _RowResult:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row


class _RecordingConnection:
    def __init__(self, *, scalar_value=None, run_id=7):
        self.scalar_value = scalar_value
        self.run_id = run_id
        self.statements: list[tuple[str, dict | None]] = []

    async def execute(self, statement, params=None):
        self.statements.append((str(statement), params))
        sql = str(statement).lower()
        if "returning id" in sql:
            return _RunIdResult(self.run_id)
        if "select consecutive_failures" in sql:
            return _RowResult((0,))
        if "select started_at, consecutive_failures" in sql:
            return _RowResult((None, 0))
        if "max(trade_date)" in sql:
            return _ScalarResult(self.scalar_value)
        return _ScalarResult(None)


class _ConnectionContext:
    def __init__(self, connection):
        self.connection = connection

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, *args):
        return False


class _RecordingEngine:
    def __init__(self, connection):
        self.connection = connection

    def connect(self):
        return _ConnectionContext(self.connection)

    def begin(self):
        return _ConnectionContext(self.connection)


def test_task_result_updates_the_run_created_by_task_start(monkeypatch):
    from app.data_pipeline import monitor
    from app.data_pipeline.monitor import TaskStatus

    connection = _RecordingConnection(run_id=42)
    monkeypatch.setattr(monitor, "engine", _RecordingEngine(connection))
    monkeypatch.setattr(monitor, "check_and_send_alerts", AsyncMock())

    run_id = asyncio.run(monitor.record_task_start("kline"))
    asyncio.run(
        monitor.record_task_result(
            "kline",
            TaskStatus.SUCCESS,
            total=3,
            success=3,
            run_id=run_id,
        )
    )

    update_calls = [
        (sql, params)
        for sql, params in connection.statements
        if "update sync_task_status" in sql.lower()
    ]
    assert len(update_calls) == 1
    assert update_calls[0][1]["run_id"] == 42


def test_kline_catchup_is_needed_when_latest_trade_date_is_stale(monkeypatch):
    from app.data_pipeline import scheduler

    connection = _RecordingConnection(scalar_value=date(2026, 8, 14))
    monkeypatch.setattr(scheduler, "engine", _RecordingEngine(connection), raising=False)
    monkeypatch.setattr(
        scheduler,
        "datetime",
        type(
            "FixedDatetime",
            (),
            {
                "now": staticmethod(lambda *_args, **_kwargs: datetime(2026, 8, 18, 10, 0)),
            },
        ),
    )

    assert asyncio.run(scheduler._kline_catchup_needed()) is True


def test_cloud_schema_repair_covers_news_and_signal_tables():
    from scripts.ensure_cloud_schema import SCHEMA_STATEMENTS

    sql = "\n".join(SCHEMA_STATEMENTS).lower()

    assert "create table if not exists events" in sql
    assert "create table if not exists signals" in sql
    assert "create table if not exists signal_propagations" in sql
    assert "create table if not exists catalyst_events" in sql
    assert "add column if not exists signal_kind" in sql
    assert "add column if not exists event_date" in sql


def test_irm_json_decode_failure_is_classified_as_retryable_provider_error(monkeypatch):
    import app.data_pipeline.data_source as data_source_mod
    from app.data_pipeline.data_source import DataSourceClient, IrmProviderError

    def bad_fetch(symbol):
        raise ValueError("Expecting value: line 1 column 1 (char 0)")

    monkeypatch.setattr(data_source_mod.ak, "stock_sns_sseinfo", bad_fetch)

    try:
        DataSourceClient().get_irm("600000.SH")
    except IrmProviderError as exc:
        assert exc.retryable is True
        assert exc.category == "non_json_response"
    else:
        raise AssertionError("non-JSON provider responses must be classified as retryable")
