import asyncio

from app.data_pipeline.api import monitor
from app.data_pipeline.api.monitor import (
    get_ingestion_job_summary,
    list_ingestion_job_failures,
)


class FakeMappings:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return FakeMappings(self._rows)


class FakeConnection:
    def __init__(self, rows):
        self._rows = rows
        self.params = None

    async def execute(self, statement, params=None):
        self.params = params
        return FakeResult(self._rows)


class FakeConnectContext:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeEngine:
    def __init__(self, conn):
        self._conn = conn

    def connect(self):
        return FakeConnectContext(self._conn)


def test_get_ingestion_job_summary_groups_by_type_and_status(monkeypatch):
    rows = [
        {"job_type": "cninfo_announcement_date", "status": "pending", "count": 2},
        {"job_type": "cninfo_announcement_date", "status": "failed", "count": 1},
        {"job_type": "irm_company", "status": "success", "count": 100},
    ]
    conn = FakeConnection(rows)
    monkeypatch.setattr(monitor, "engine", FakeEngine(conn))

    result = asyncio.run(get_ingestion_job_summary())

    assert result == {
        "cninfo_announcement_date": {"pending": 2, "failed": 1},
        "irm_company": {"success": 100},
    }


def test_list_ingestion_job_failures_clamps_limit(monkeypatch):
    rows = [
        {
            "id": 1,
            "job_type": "cninfo_announcement_date",
            "job_key": "2026-05-23",
            "status": "failed",
            "attempt_count": 3,
            "max_attempts": 3,
            "next_run_at": None,
            "last_error": "timeout",
            "result_summary": {"processed": 0},
            "updated_at": "2026-05-23T10:00:00",
        }
    ]
    conn = FakeConnection(rows)
    monkeypatch.setattr(monitor, "engine", FakeEngine(conn))

    result = asyncio.run(list_ingestion_job_failures(limit=999))

    assert conn.params == {"limit": 500}
    assert result == [dict(rows[0])]
