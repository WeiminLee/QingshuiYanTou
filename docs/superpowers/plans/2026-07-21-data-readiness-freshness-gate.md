# Data Readiness Freshness Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add daily-reliable data readiness reporting and inject freshness constraints into Agent reasoning.

**Architecture:** Create a focused `app.readiness` package that calculates source freshness from local storage only. Expose read-only readiness APIs, then add a narrow Agent integration in `run_lead_agent()` so research answers receive a compact freshness context without touching every tool.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy async engine, Pydantic v2, pytest, LangChain message primitives.

## Global Constraints

- Do not redesign `DataFetcher` or scheduler internals.
- Do not migrate announcement, IRM, news, or report ingestion into a new unified raw-record schema.
- Do not add a frontend dashboard in this phase.
- Do not implement automatic backfill or retry orchestration beyond using existing sync state.
- Do not block the entire API when data is stale. The gate should degrade reasoning, not make the system unavailable.
- Readiness uses local database state only and never calls external data providers.
- Required sources: `kline`, `announcement`, `irm`, `news`, `research_report`.
- Default thresholds: `kline` 1 trading day; `announcement` 1 natural day; `irm` 1 natural day; `news` 1 natural day; `research_report` 3 natural days.

---

## File Structure

- Create `backend/app/readiness/__init__.py`: package exports.
- Create `backend/app/readiness/schemas.py`: Pydantic response models and status constants.
- Create `backend/app/readiness/service.py`: source specifications, lag calculation, status aggregation, DB-backed readiness service.
- Create `backend/app/readiness/api.py`: FastAPI router for `/api/v1/readiness`.
- Modify `backend/app/main.py`: include readiness router with optional read authentication.
- Create `backend/tests/test_readiness_service.py`: unit tests for lag/status/formatting using fake repositories.
- Create `backend/tests/test_readiness_api.py`: API tests with monkeypatched service.
- Create `backend/app/reasoning/langchain_agent/freshness.py`: compact prompt block formatter and fail-soft readiness loader.
- Modify `backend/app/reasoning/langchain_agent/client.py`: load freshness block and pass it into `apply_prompt_template()`.
- Modify `backend/app/reasoning/langchain_agent/prompts/lead_system_prompt.py`: accept and render `freshness_context`.
- Create `backend/tests/reasoning/test_freshness_gate.py`: formatter and prompt injection tests.

---

### Task 1: Readiness Calculation Core

**Files:**
- Create: `backend/app/readiness/__init__.py`
- Create: `backend/app/readiness/schemas.py`
- Create: `backend/app/readiness/service.py`
- Test: `backend/tests/test_readiness_service.py`

**Interfaces:**
- Produces: `SourceStatus`, `ThresholdKind`, `ReadinessSource`, `ReadinessSummary` in `app.readiness.schemas`.
- Produces: `DataReadinessService.get_all(now: datetime | None = None) -> ReadinessSummary`.
- Produces: `DataReadinessService.get_source(source: str, now: datetime | None = None) -> ReadinessSource | None`.
- Produces: `format_readiness_for_agent(summary: ReadinessSummary) -> str`.

- [ ] **Step 1: Write failing unit tests**

Create `backend/tests/test_readiness_service.py`:

```python
from datetime import UTC, date, datetime

import pytest

from app.readiness.schemas import SourceStatus
from app.readiness.service import (
    DataReadinessService,
    SourceDataSnapshot,
    SourceSyncSnapshot,
    count_weekday_lag,
    format_readiness_for_agent,
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
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
cd backend
.venv/bin/python -m pytest tests/test_readiness_service.py -q
```

Expected: FAIL during import because `app.readiness` does not exist.

- [ ] **Step 3: Implement schemas**

Create `backend/app/readiness/__init__.py`:

```python
"""Data readiness and freshness gate package."""

from app.readiness.schemas import ReadinessSource, ReadinessSummary, SourceStatus
from app.readiness.service import DataReadinessService

__all__ = ["DataReadinessService", "ReadinessSource", "ReadinessSummary", "SourceStatus"]
```

Create `backend/app/readiness/schemas.py`:

```python
from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class SourceStatus(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    MISSING = "missing"
    FAILED = "failed"


class ThresholdKind(StrEnum):
    NATURAL_DAY = "natural_day"
    TRADING_DAY = "trading_day"


class ReadinessSource(BaseModel):
    source: str
    display_name: str
    status: SourceStatus
    latest_data_date: str | None = None
    latest_success_at: str | None = None
    lag_days: int | None = None
    threshold_days: int
    threshold_kind: ThresholdKind
    coverage_scope: str = "unknown"
    required_for_reasoning: bool = True
    last_error: str | None = None
    recommendation: str


class ReadinessSummary(BaseModel):
    as_of: str
    overall_status: str = Field(pattern="^(fresh|degraded|unavailable)$")
    sources: list[ReadinessSource]
    summary: str
```

- [ ] **Step 4: Implement readiness service**

Create `backend/app/readiness/service.py`:

```python
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Protocol

from sqlalchemy import text

from app.core.database import engine
from app.readiness.schemas import ReadinessSource, ReadinessSummary, SourceStatus, ThresholdKind

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SourceSpec:
    source: str
    display_name: str
    threshold_days: int
    threshold_kind: ThresholdKind
    coverage_scope: str = "unknown"
    required_for_reasoning: bool = True


@dataclass(frozen=True)
class SourceSyncSnapshot:
    latest_success_at: datetime | None = None
    latest_status: str | None = None
    last_error: str | None = None


@dataclass(frozen=True)
class SourceDataSnapshot:
    source: str
    latest_data_date: date | None
    sync: SourceSyncSnapshot


class ReadinessRepository(Protocol):
    async def get_latest_data_date(self, source: str) -> date | None:
        ...

    async def get_sync_snapshot(self, source: str) -> SourceSyncSnapshot:
        ...


SOURCE_SPECS: dict[str, SourceSpec] = {
    "kline": SourceSpec("kline", "K-line", 1, ThresholdKind.TRADING_DAY, "unknown", True),
    "announcement": SourceSpec("announcement", "Announcements", 1, ThresholdKind.NATURAL_DAY, "unknown", True),
    "irm": SourceSpec("irm", "IR Q&A", 1, ThresholdKind.NATURAL_DAY, "unknown", True),
    "news": SourceSpec("news", "News", 1, ThresholdKind.NATURAL_DAY, "unknown", True),
    "research_report": SourceSpec(
        "research_report",
        "Research Reports",
        3,
        ThresholdKind.NATURAL_DAY,
        "unknown",
        True,
    ),
}

SYNC_PATTERNS: dict[str, tuple[str, ...]] = {
    "kline": ("kline",),
    "announcement": ("cninfo", "announcement", "minishare_ann"),
    "irm": ("irm",),
    "news": ("news",),
    "research_report": ("report", "research"),
}


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def count_weekday_lag(latest: date, current: date) -> int:
    if latest >= current:
        return 0
    days = 0
    probe = latest
    while probe < current:
        probe = date.fromordinal(probe.toordinal() + 1)
        if probe.weekday() < 5:
            days += 1
    return days


class SqlReadinessRepository:
    async def get_latest_data_date(self, source: str) -> date | None:
        sql_by_source = {
            "kline": "SELECT MAX(trade_date) FROM daily_data",
            "announcement": (
                "SELECT MAX(ann_date) FROM announcements "
                "WHERE announcement_type IS NULL OR announcement_type NOT LIKE 'irm:%%'"
            ),
            "irm": "SELECT MAX(ann_date) FROM announcements WHERE announcement_type LIKE 'irm:%%'",
            "news": "SELECT MAX(DATE(publish_at)) FROM events",
            "research_report": "SELECT MAX(trade_date) FROM research_report_meta",
        }
        sql = sql_by_source.get(source)
        if not sql:
            return None
        async with engine.connect() as conn:
            result = await conn.execute(text(sql))
            value = result.scalar()
        if isinstance(value, datetime):
            return value.date()
        return value

    async def get_sync_snapshot(self, source: str) -> SourceSyncSnapshot:
        patterns = SYNC_PATTERNS.get(source, (source,))
        like_clauses = []
        params = {}
        for i, pattern in enumerate(patterns):
            params[f"pattern_{i}"] = f"%{pattern}%"
            like_clauses.append(
                f"(LOWER(source) LIKE :pattern_{i} OR LOWER(task_name) LIKE :pattern_{i})"
            )
        where = " OR ".join(like_clauses)
        sql = text(
            f"""
            SELECT status, completed_at, last_error, updated_at
            FROM ingestion_runs
            WHERE {where}
            ORDER BY updated_at DESC NULLS LAST, started_at DESC NULLS LAST
            LIMIT 1
            """
        )
        try:
            async with engine.connect() as conn:
                result = await conn.execute(sql, params)
                row = result.mappings().first()
        except Exception as exc:
            logger.warning("[Readiness] sync metadata lookup failed for %s: %s", source, exc)
            return SourceSyncSnapshot(last_error=f"sync metadata lookup failed: {str(exc)[:300]}")
        if not row:
            return SourceSyncSnapshot()
        completed_at = row.get("completed_at")
        latest_success_at = completed_at if row.get("status") == "success" else None
        return SourceSyncSnapshot(
            latest_success_at=latest_success_at,
            latest_status=row.get("status"),
            last_error=row.get("last_error"),
        )


class DataReadinessService:
    def __init__(self, repository: ReadinessRepository | None = None):
        self.repository = repository or SqlReadinessRepository()

    async def get_all(self, now: datetime | None = None) -> ReadinessSummary:
        as_of = _as_utc(now or _now_utc())
        snapshots: list[SourceDataSnapshot] = []
        for source in SOURCE_SPECS:
            snapshots.append(await self._load_snapshot(source))
        return self.build_summary(as_of, snapshots)

    async def get_source(self, source: str, now: datetime | None = None) -> ReadinessSource | None:
        if source not in SOURCE_SPECS:
            return None
        as_of = _as_utc(now or _now_utc())
        summary = self.build_summary(as_of, [await self._load_snapshot(source)])
        return summary.sources[0]

    async def _load_snapshot(self, source: str) -> SourceDataSnapshot:
        try:
            latest = await self.repository.get_latest_data_date(source)
        except Exception as exc:
            logger.warning("[Readiness] data lookup failed for %s: %s", source, exc)
            return SourceDataSnapshot(
                source=source,
                latest_data_date=None,
                sync=SourceSyncSnapshot(latest_status="failed", last_error=str(exc)[:300]),
            )
        try:
            sync = await self.repository.get_sync_snapshot(source)
        except Exception as exc:
            logger.warning("[Readiness] sync lookup failed for %s: %s", source, exc)
            sync = SourceSyncSnapshot(last_error=str(exc)[:300])
        return SourceDataSnapshot(source=source, latest_data_date=latest, sync=sync)

    def build_summary(self, now: datetime, sources: list[SourceDataSnapshot]) -> ReadinessSummary:
        as_of = _as_utc(now)
        items = [self._build_source(as_of, snapshot) for snapshot in sources]
        overall = self._overall_status(items)
        stale_count = sum(1 for item in items if item.status == SourceStatus.STALE)
        unavailable_count = sum(1 for item in items if item.status in {SourceStatus.MISSING, SourceStatus.FAILED})
        if overall == "fresh":
            summary = "全部关键数据源处于日级可靠窗口内。"
        elif overall == "degraded":
            summary = f"{stale_count} 个关键数据源已滞后，Agent 结论需要声明数据截至日期。"
        else:
            summary = f"{unavailable_count} 个关键数据源缺失或失败，Agent 不应给出强时效结论。"
        return ReadinessSummary(
            as_of=as_of.isoformat(),
            overall_status=overall,
            sources=items,
            summary=summary,
        )

    def _build_source(self, now: datetime, snapshot: SourceDataSnapshot) -> ReadinessSource:
        spec = SOURCE_SPECS[snapshot.source]
        latest = snapshot.latest_data_date
        lag_days: int | None = None
        if latest is None:
            status = SourceStatus.MISSING
            recommendation = "本地没有该数据源记录，需要先完成同步。"
        else:
            current_date = now.date()
            if spec.threshold_kind == ThresholdKind.TRADING_DAY:
                lag_days = count_weekday_lag(latest, current_date)
            else:
                lag_days = max(0, (current_date - latest).days)
            if lag_days <= spec.threshold_days:
                status = SourceStatus.FRESH
                recommendation = "数据处于日级可靠窗口内。"
            else:
                status = SourceStatus.STALE
                recommendation = f"数据已滞后 {lag_days} 天，回答需要声明基于截至 {latest.isoformat()} 的数据。"
        if status in {SourceStatus.STALE, SourceStatus.MISSING} and snapshot.sync.latest_status in {
            "failed",
            "dead",
        }:
            status = SourceStatus.FAILED
            recommendation = f"最近同步失败，回答前应先修复并同步该数据源。"
        last_error = snapshot.sync.last_error
        if last_error and len(last_error) > 300:
            last_error = last_error[:300]
        return ReadinessSource(
            source=spec.source,
            display_name=spec.display_name,
            status=status,
            latest_data_date=latest.isoformat() if latest else None,
            latest_success_at=(
                _as_utc(snapshot.sync.latest_success_at).isoformat()
                if snapshot.sync.latest_success_at
                else None
            ),
            lag_days=lag_days,
            threshold_days=spec.threshold_days,
            threshold_kind=spec.threshold_kind,
            coverage_scope=spec.coverage_scope,
            required_for_reasoning=spec.required_for_reasoning,
            last_error=last_error,
            recommendation=recommendation,
        )

    def _overall_status(self, items: list[ReadinessSource]) -> str:
        required = [item for item in items if item.required_for_reasoning]
        if any(item.status in {SourceStatus.MISSING, SourceStatus.FAILED} for item in required):
            return "unavailable"
        if any(item.status == SourceStatus.STALE for item in required):
            return "degraded"
        return "fresh"


def format_readiness_for_agent(summary: ReadinessSummary) -> str:
    lines = [
        "<data_readiness>",
        f"as_of={summary.as_of}",
        f"overall_status={summary.overall_status}",
        "rules:",
        "- fresh: 可以正常回答。",
        "- stale: 必须声明基于截至日期的数据，并降低结论强度。",
        "- missing/failed: 不得给出强时效结论，应提示先同步对应数据。",
        "sources:",
    ]
    for item in summary.sources:
        cutoff = item.latest_data_date or "none"
        detail = (
            f"- {item.source}: {item.status.value}; latest_data_date={cutoff}; "
            f"lag_days={item.lag_days}; threshold={item.threshold_days} {item.threshold_kind.value}; "
            f"recommendation={item.recommendation}"
        )
        if item.last_error:
            detail += f"; last_error={item.last_error}"
        lines.append(detail)
    if summary.overall_status == "degraded":
        lines.append("answer_boundary=基于截至最新可用日期的数据，避免强时效判断。")
    elif summary.overall_status == "unavailable":
        lines.append("answer_boundary=关键数据缺失或同步失败，不得输出强结论。")
    else:
        lines.append("answer_boundary=关键数据源处于日级可靠窗口内。")
    lines.append("</data_readiness>")
    return "\n".join(lines)
```

- [ ] **Step 5: Run tests to verify pass**

Run:

```bash
cd backend
.venv/bin/python -m pytest tests/test_readiness_service.py -q
```

Expected: PASS for all readiness service tests.

- [ ] **Step 6: Commit**

```bash
git add backend/app/readiness backend/tests/test_readiness_service.py
git commit -m "feat: add data readiness service"
```

---

### Task 2: Readiness API

**Files:**
- Create: `backend/app/readiness/api.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_readiness_api.py`

**Interfaces:**
- Consumes: `DataReadinessService.get_all()` and `DataReadinessService.get_source(source)`.
- Produces: `router = APIRouter()` in `app.readiness.api`.
- Produces: `GET /api/v1/readiness` and `GET /api/v1/readiness/{source}`.

- [ ] **Step 1: Write failing API tests**

Create `backend/tests/test_readiness_api.py`:

```python
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.readiness.schemas import ReadinessSource, ReadinessSummary, SourceStatus, ThresholdKind


class FakeReadinessService:
    async def get_all(self, now=None):
        return ReadinessSummary(
            as_of=datetime(2026, 7, 21, 9, 0, tzinfo=UTC).isoformat(),
            overall_status="fresh",
            summary="全部关键数据源处于日级可靠窗口内。",
            sources=[
                ReadinessSource(
                    source="kline",
                    display_name="K-line",
                    status=SourceStatus.FRESH,
                    latest_data_date="2026-07-20",
                    latest_success_at=None,
                    lag_days=1,
                    threshold_days=1,
                    threshold_kind=ThresholdKind.TRADING_DAY,
                    recommendation="数据处于日级可靠窗口内。",
                )
            ],
        )

    async def get_source(self, source: str, now=None):
        if source != "kline":
            return None
        return (await self.get_all(now)).sources[0]


@pytest.mark.asyncio
async def test_readiness_summary_endpoint(monkeypatch):
    import app.readiness.api as api

    monkeypatch.setattr(api, "DataReadinessService", lambda: FakeReadinessService())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/readiness")

    assert resp.status_code == 200
    body = resp.json()
    assert body["overall_status"] == "fresh"
    assert body["sources"][0]["source"] == "kline"


@pytest.mark.asyncio
async def test_readiness_source_endpoint(monkeypatch):
    import app.readiness.api as api

    monkeypatch.setattr(api, "DataReadinessService", lambda: FakeReadinessService())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/readiness/kline")

    assert resp.status_code == 200
    assert resp.json()["source"] == "kline"


@pytest.mark.asyncio
async def test_readiness_unknown_source_404(monkeypatch):
    import app.readiness.api as api

    monkeypatch.setattr(api, "DataReadinessService", lambda: FakeReadinessService())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/readiness/unknown")

    assert resp.status_code == 404
    assert resp.json()["detail"] == "unknown readiness source: unknown"
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
cd backend
.venv/bin/python -m pytest tests/test_readiness_api.py -q
```

Expected: FAIL because `/api/v1/readiness` is not registered.

- [ ] **Step 3: Implement API router**

Create `backend/app/readiness/api.py`:

```python
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.readiness.schemas import ReadinessSource, ReadinessSummary
from app.readiness.service import DataReadinessService

router = APIRouter(tags=["数据可用性"])


@router.get("", response_model=ReadinessSummary)
async def get_readiness_summary() -> ReadinessSummary:
    return await DataReadinessService().get_all()


@router.get("/{source}", response_model=ReadinessSource)
async def get_readiness_source(source: str) -> ReadinessSource:
    item = await DataReadinessService().get_source(source)
    if item is None:
        raise HTTPException(status_code=404, detail=f"unknown readiness source: {source}")
    return item
```

Modify `backend/app/main.py` imports:

```python
from app.readiness.api import router as readiness_router
```

Register after other read routes:

```python
app.include_router(
    readiness_router,
    prefix="/api/v1/readiness",
    dependencies=[Depends(verify_api_key_optional)],
)
```

- [ ] **Step 4: Run API tests**

Run:

```bash
cd backend
.venv/bin/python -m pytest tests/test_readiness_api.py -q
```

Expected: PASS.

- [ ] **Step 5: Run service and API tests together**

Run:

```bash
cd backend
.venv/bin/python -m pytest tests/test_readiness_service.py tests/test_readiness_api.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/readiness/api.py backend/app/main.py backend/tests/test_readiness_api.py
git commit -m "feat: expose data readiness api"
```

---

### Task 3: Agent Freshness Context Formatter

**Files:**
- Create: `backend/app/reasoning/langchain_agent/freshness.py`
- Test: `backend/tests/reasoning/test_freshness_gate.py`

**Interfaces:**
- Consumes: `DataReadinessService.get_all()`.
- Produces: `load_freshness_context() -> str`.
- Produces: `build_unavailable_freshness_context(error: str) -> str`.

- [ ] **Step 1: Write failing formatter tests**

Create `backend/tests/reasoning/test_freshness_gate.py`:

```python
from datetime import UTC, datetime

import pytest

from app.readiness.schemas import ReadinessSource, ReadinessSummary, SourceStatus, ThresholdKind
from app.reasoning.langchain_agent.freshness import (
    build_unavailable_freshness_context,
    load_freshness_context,
)


class FakeService:
    async def get_all(self):
        return ReadinessSummary(
            as_of=datetime(2026, 7, 21, 9, 0, tzinfo=UTC).isoformat(),
            overall_status="degraded",
            summary="1 个关键数据源已滞后，Agent 结论需要声明数据截至日期。",
            sources=[
                ReadinessSource(
                    source="announcement",
                    display_name="Announcements",
                    status=SourceStatus.STALE,
                    latest_data_date="2026-07-19",
                    latest_success_at=None,
                    lag_days=2,
                    threshold_days=1,
                    threshold_kind=ThresholdKind.NATURAL_DAY,
                    recommendation="数据已滞后 2 天，回答需要声明基于截至 2026-07-19 的数据。",
                )
            ],
        )


@pytest.mark.asyncio
async def test_load_freshness_context_formats_summary():
    text = await load_freshness_context(service=FakeService())

    assert "<data_readiness>" in text
    assert "overall_status=degraded" in text
    assert "announcement: stale" in text
    assert "不得输出强结论" not in text


def test_build_unavailable_freshness_context_truncates_error():
    text = build_unavailable_freshness_context("x" * 500)

    assert "overall_status=unavailable" in text
    assert "readiness_error=" in text
    assert len(text) < 700
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
cd backend
.venv/bin/python -m pytest tests/reasoning/test_freshness_gate.py -q
```

Expected: FAIL because `app.reasoning.langchain_agent.freshness` does not exist.

- [ ] **Step 3: Implement freshness loader**

Create `backend/app/reasoning/langchain_agent/freshness.py`:

```python
from __future__ import annotations

import logging
from typing import Any

from app.readiness.service import DataReadinessService, format_readiness_for_agent

logger = logging.getLogger(__name__)


def build_unavailable_freshness_context(error: str) -> str:
    short_error = (error or "unknown readiness error")[:300]
    return "\n".join(
        [
            "<data_readiness>",
            "overall_status=unavailable",
            f"readiness_error={short_error}",
            "answer_boundary=数据可用性检查失败，不得输出强时效结论；需要提示用户先确认同步状态。",
            "</data_readiness>",
        ]
    )


async def load_freshness_context(service: Any | None = None) -> str:
    active_service = service or DataReadinessService()
    try:
        summary = await active_service.get_all()
    except Exception as exc:
        logger.warning("[FreshnessGate] readiness lookup failed: %s", exc)
        return build_unavailable_freshness_context(str(exc))
    return format_readiness_for_agent(summary)
```

- [ ] **Step 4: Run formatter tests**

Run:

```bash
cd backend
.venv/bin/python -m pytest tests/reasoning/test_freshness_gate.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/reasoning/langchain_agent/freshness.py backend/tests/reasoning/test_freshness_gate.py
git commit -m "feat: add agent freshness context formatter"
```

---

### Task 4: Prompt and Agent Integration

**Files:**
- Modify: `backend/app/reasoning/langchain_agent/prompts/lead_system_prompt.py`
- Modify: `backend/app/reasoning/langchain_agent/client.py`
- Test: `backend/tests/reasoning/test_freshness_gate.py`

**Interfaces:**
- Consumes: `load_freshness_context() -> str`.
- Modifies: `apply_prompt_template(..., freshness_context: str = "") -> str`.
- Produces: system prompt containing `<data_readiness>` when freshness context exists.

- [ ] **Step 1: Add failing prompt integration tests**

Append to `backend/tests/reasoning/test_freshness_gate.py`:

```python
def test_prompt_template_includes_freshness_context():
    from app.reasoning.langchain_agent.prompts.lead_system_prompt import apply_prompt_template

    prompt = apply_prompt_template(
        background_context="",
        graph_context="",
        signal_context="",
        freshness_context="<data_readiness>\noverall_status=degraded\n</data_readiness>",
    )

    assert "<data_readiness>" in prompt
    assert "overall_status=degraded" in prompt
    assert "数据新鲜度" in prompt
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
cd backend
.venv/bin/python -m pytest tests/reasoning/test_freshness_gate.py::test_prompt_template_includes_freshness_context -q
```

Expected: FAIL because `apply_prompt_template()` does not accept `freshness_context`.

- [ ] **Step 3: Modify prompt template function**

In `backend/app/reasoning/langchain_agent/prompts/lead_system_prompt.py`, update `apply_prompt_template` signature to include:

```python
freshness_context: str = "",
```

Inside the function, append this section when the context is non-empty:

```python
    if freshness_context:
        sections.append(
            "\n## 数据新鲜度与结论边界\n"
            f"{freshness_context}\n"
            "你必须遵守以上 data_readiness 约束：如果状态为 stale，需要声明数据截至日期并降低结论强度；"
            "如果状态为 missing 或 failed，不得输出强时效结论。"
        )
```

Use the local variable name that the function already uses for prompt sections. If the current implementation does not have a `sections` list, add the freshness block immediately before the final return by concatenating it to the rendered prompt:

```python
    if freshness_context:
        prompt += (
            "\n\n## 数据新鲜度与结论边界\n"
            f"{freshness_context}\n"
            "你必须遵守以上 data_readiness 约束：如果状态为 stale，需要声明数据截至日期并降低结论强度；"
            "如果状态为 missing 或 failed，不得输出强时效结论。"
        )
```

- [ ] **Step 4: Load freshness context in `run_lead_agent()`**

In `backend/app/reasoning/langchain_agent/client.py`, inside the `if not skip_preflight:` block before `apply_prompt_template(...)`, add:

```python
            freshness_context = ""
            try:
                from app.reasoning.langchain_agent.freshness import load_freshness_context

                freshness_context = await load_freshness_context()
            except Exception as exc:
                logger.warning("[FreshnessGate] failed to load context: %s", exc)
                from app.reasoning.langchain_agent.freshness import build_unavailable_freshness_context

                freshness_context = build_unavailable_freshness_context(str(exc))
```

Then pass it into `apply_prompt_template(...)`:

```python
                freshness_context=freshness_context,
```

For the `skip_preflight` branch, leave `system_prompt = ""` as-is so tests and resume paths that intentionally bypass preflight do not perform DB reads.

- [ ] **Step 5: Run freshness tests**

Run:

```bash
cd backend
.venv/bin/python -m pytest tests/reasoning/test_freshness_gate.py -q
```

Expected: PASS.

- [ ] **Step 6: Run targeted existing Agent prompt tests**

Run:

```bash
cd backend
.venv/bin/python -m pytest tests/reasoning/test_prompt_template.py tests/reasoning/test_message_builder.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/reasoning/langchain_agent/prompts/lead_system_prompt.py backend/app/reasoning/langchain_agent/client.py backend/tests/reasoning/test_freshness_gate.py
git commit -m "feat: inject data freshness into agent prompt"
```

---

### Task 5: Final Verification

**Files:**
- No new files.
- Verify changed files from Tasks 1-4.

**Interfaces:**
- Consumes all previous task outputs.
- Produces a verified implementation ready for user review.

- [ ] **Step 1: Run readiness and freshness tests**

Run:

```bash
cd backend
.venv/bin/python -m pytest tests/test_readiness_service.py tests/test_readiness_api.py tests/reasoning/test_freshness_gate.py -q
```

Expected: PASS.

- [ ] **Step 2: Run focused nearby regression tests**

Run:

```bash
cd backend
.venv/bin/python -m pytest tests/reasoning/test_prompt_template.py tests/reasoning/test_message_builder.py tests/reasoning/test_rest_api_reasoning.py -q
```

Expected: PASS.

- [ ] **Step 3: Run import smoke**

Run:

```bash
cd backend
.venv/bin/python - <<'PY'
import app.main
from app.readiness.service import DataReadinessService
from app.reasoning.langchain_agent.freshness import build_unavailable_freshness_context
print("ok", DataReadinessService.__name__, bool(build_unavailable_freshness_context("x")))
PY
```

Expected output starts with:

```text
ok DataReadinessService True
```

- [ ] **Step 4: Inspect git diff**

Run:

```bash
git diff -- backend/app/readiness backend/app/main.py backend/app/reasoning/langchain_agent backend/tests/test_readiness_service.py backend/tests/test_readiness_api.py backend/tests/reasoning/test_freshness_gate.py
```

Expected: Diff only contains readiness service/API, freshness prompt integration, and related tests.

- [ ] **Step 5: Final commit if previous tasks were not committed individually**

If Tasks 1-4 already produced commits, skip this step. If changes are still uncommitted, run:

```bash
git add backend/app/readiness backend/app/main.py backend/app/reasoning/langchain_agent/freshness.py backend/app/reasoning/langchain_agent/client.py backend/app/reasoning/langchain_agent/prompts/lead_system_prompt.py backend/tests/test_readiness_service.py backend/tests/test_readiness_api.py backend/tests/reasoning/test_freshness_gate.py
git commit -m "feat: add data readiness freshness gate"
```

Expected: A commit containing only this feature's files.

---

## Self-Review

- Spec coverage: The plan implements local readiness status, five source domains, read APIs, fail-soft error handling, Agent context injection, and focused tests. The plan intentionally excludes connector refactors, frontend dashboard, and automatic backfill.
- Placeholder scan: The plan contains no open-ended implementation placeholders. Each code-producing task includes concrete files, code, commands, and expected results.
- Type consistency: `ReadinessSummary`, `ReadinessSource`, `DataReadinessService`, `format_readiness_for_agent`, and `load_freshness_context` are introduced before later tasks consume them.
