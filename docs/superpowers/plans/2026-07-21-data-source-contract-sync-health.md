# Data Source Contract Sync Health Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a local data source contract registry and sync-health API so each daily-reliable source has one declared dependency contract.

**Architecture:** Introduce `app.readiness.contracts` as the single in-code registry for source metadata, then refactor readiness mappings to derive from contracts. Add `app.readiness.sync_health` to combine contract metadata, readiness status, and sync snapshot state into operator-facing health summaries under the existing readiness router.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy async engine, Pydantic v2, pytest, httpx ASGI tests.

## Global Constraints

- Do not replace scheduler, job queue, or `IngestionProgressTracker`.
- Do not migrate existing tables or introduce a new database source-of-truth table in this phase.
- Do not add external providers or call external networks from readiness or sync-health code.
- Do not implement automatic repair, backfill orchestration, or retry policy changes.
- Do not add a frontend dashboard in this phase.
- Do not change Agent prompt behavior beyond preserving the existing freshness gate.
- Contract registry must cover exactly these daily-reliable sources: `kline`, `announcement`, `irm`, `news`, `research_report`.
- Error strings exposed through APIs must be bounded to 300 characters.
- Existing readiness and Agent freshness tests must continue to pass.

---

## File Structure

- Create `backend/app/readiness/contracts.py`: dataclass registry and public helpers for source contracts.
- Modify `backend/app/readiness/schemas.py`: Pydantic response models for contract and sync-health APIs.
- Modify `backend/app/readiness/service.py`: derive source specs, acquisition pairs, monitor tasks, job types, and checkpoint pairs from contracts.
- Create `backend/app/readiness/sync_health.py`: `SyncHealthService` and health classification logic.
- Modify `backend/app/readiness/api.py`: add `/contracts`, `/sync-health`, and `/sync-health/{source}` routes before `/{source}`.
- Create `backend/tests/test_readiness_contracts.py`: registry and mapping tests.
- Create `backend/tests/test_sync_health.py`: sync-health classification tests.
- Modify `backend/tests/test_readiness_api.py`: API tests for contracts and sync-health endpoints.

---

### Task 1: Data Source Contract Registry

**Files:**
- Create: `backend/app/readiness/contracts.py`
- Test: `backend/tests/test_readiness_contracts.py`

**Interfaces:**
- Produces: `AcquisitionTaskRef(source: str, task_name: str)`.
- Produces: `DataSourceContract(...)`.
- Produces: `list_contracts() -> tuple[DataSourceContract, ...]`.
- Produces: `get_contract(source: str) -> DataSourceContract | None`.
- Produces: `REQUIRED_SOURCE_IDS: tuple[str, ...]`.

- [ ] **Step 1: Write failing registry tests**

Create `backend/tests/test_readiness_contracts.py`:

```python
from app.readiness.contracts import REQUIRED_SOURCE_IDS, get_contract, list_contracts
from app.readiness.schemas import ThresholdKind


def test_contract_registry_contains_required_sources():
    contracts = list_contracts()

    assert tuple(contract.source for contract in contracts) == REQUIRED_SOURCE_IDS
    assert REQUIRED_SOURCE_IDS == ("kline", "announcement", "irm", "news", "research_report")


def test_announcement_contract_declares_sync_dependencies():
    contract = get_contract("announcement")

    assert contract is not None
    assert contract.threshold_days == 1
    assert contract.threshold_kind == ThresholdKind.NATURAL_DAY
    assert contract.local_data_signal == "non-IRM announcements.ann_date"
    assert contract.monitor_tasks == ("cninfo", "cninfo_enqueue")
    assert contract.job_types == ("cninfo_announcement_date",)
    assert ("cninfo", "announcements_history") in [
        (task.source, task.task_name) for task in contract.checkpoint_tasks
    ]


def test_irm_contract_declares_queue_and_checkpoint_dependencies():
    contract = get_contract("irm")

    assert contract is not None
    assert contract.monitor_tasks == ("irm", "irm_enqueue")
    assert contract.job_types == ("irm_company",)
    assert ("irm", "qa_fetch") in [
        (task.source, task.task_name) for task in contract.acquisition_tasks
    ]
    assert ("irm_minishare", "irm_daily_backfill") in [
        (task.source, task.task_name) for task in contract.checkpoint_tasks
    ]


def test_unknown_contract_returns_none():
    assert get_contract("unknown") is None
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
cd backend
.venv/bin/python -m pytest tests/test_readiness_contracts.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.readiness.contracts'`.

- [ ] **Step 3: Implement contract registry**

Create `backend/app/readiness/contracts.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.readiness.schemas import ThresholdKind

UpdateFrequency = Literal["intraday", "daily", "periodic"]


@dataclass(frozen=True)
class AcquisitionTaskRef:
    source: str
    task_name: str


@dataclass(frozen=True)
class DataSourceContract:
    source: str
    display_name: str
    description: str
    update_frequency: UpdateFrequency
    expected_arrival: str
    threshold_days: int
    threshold_kind: ThresholdKind
    coverage_scope: str
    required_for_reasoning: bool
    local_data_signal: str
    monitor_tasks: tuple[str, ...]
    acquisition_tasks: tuple[AcquisitionTaskRef, ...]
    job_types: tuple[str, ...]
    checkpoint_tasks: tuple[AcquisitionTaskRef, ...]
    owner_module: str


REQUIRED_SOURCE_IDS = ("kline", "announcement", "irm", "news", "research_report")


_CONTRACTS: tuple[DataSourceContract, ...] = (
    DataSourceContract(
        source="kline",
        display_name="K-line",
        description="Daily OHLCV and market data used by technical and price reasoning.",
        update_frequency="daily",
        expected_arrival="trading day close + local sync",
        threshold_days=1,
        threshold_kind=ThresholdKind.TRADING_DAY,
        coverage_scope="unknown",
        required_for_reasoning=True,
        local_data_signal="daily_data.trade_date",
        monitor_tasks=("kline",),
        acquisition_tasks=(
            AcquisitionTaskRef("kline", "kline"),
            AcquisitionTaskRef("tushare", "kline"),
        ),
        job_types=(),
        checkpoint_tasks=(
            AcquisitionTaskRef("kline", "kline"),
            AcquisitionTaskRef("tushare", "kline"),
        ),
        owner_module="app.data_pipeline.scheduler",
    ),
    DataSourceContract(
        source="announcement",
        display_name="Announcements",
        description="Listed-company announcements used by evidence, graph, and event reasoning.",
        update_frequency="daily",
        expected_arrival="daily after close",
        threshold_days=1,
        threshold_kind=ThresholdKind.NATURAL_DAY,
        coverage_scope="unknown",
        required_for_reasoning=True,
        local_data_signal="non-IRM announcements.ann_date",
        monitor_tasks=("cninfo", "cninfo_enqueue"),
        acquisition_tasks=(
            AcquisitionTaskRef("cninfo", "announcements"),
            AcquisitionTaskRef("cninfo", "announcements_history"),
            AcquisitionTaskRef("minishare_ann", "ann_history"),
        ),
        job_types=("cninfo_announcement_date",),
        checkpoint_tasks=(
            AcquisitionTaskRef("cninfo", "announcements"),
            AcquisitionTaskRef("cninfo", "announcements_history"),
            AcquisitionTaskRef("minishare_ann", "ann_history"),
        ),
        owner_module="app.data_pipeline.fetcher",
    ),
    DataSourceContract(
        source="irm",
        display_name="IR Q&A",
        description="Investor-relation Q&A used for management interaction and expectation clues.",
        update_frequency="daily",
        expected_arrival="daily evening",
        threshold_days=1,
        threshold_kind=ThresholdKind.NATURAL_DAY,
        coverage_scope="unknown",
        required_for_reasoning=True,
        local_data_signal="IRM rows in announcements.ann_date",
        monitor_tasks=("irm", "irm_enqueue"),
        acquisition_tasks=(
            AcquisitionTaskRef("irm", "qa_fetch"),
            AcquisitionTaskRef("irm_minishare", "irm_daily_backfill"),
        ),
        job_types=("irm_company",),
        checkpoint_tasks=(
            AcquisitionTaskRef("irm", "qa_fetch"),
            AcquisitionTaskRef("irm_minishare", "irm_daily_backfill"),
        ),
        owner_module="app.data_pipeline.fetcher",
    ),
    DataSourceContract(
        source="news",
        display_name="News",
        description="News events used by event and signal reasoning.",
        update_frequency="intraday",
        expected_arrival="every 5 minutes",
        threshold_days=1,
        threshold_kind=ThresholdKind.NATURAL_DAY,
        coverage_scope="unknown",
        required_for_reasoning=True,
        local_data_signal="events.publish_at",
        monitor_tasks=("news", "news_sync"),
        acquisition_tasks=(
            AcquisitionTaskRef("news", "news"),
            AcquisitionTaskRef("akshare", "news"),
        ),
        job_types=(),
        checkpoint_tasks=(
            AcquisitionTaskRef("news", "news"),
            AcquisitionTaskRef("akshare", "news"),
        ),
        owner_module="app.data_pipeline.scheduler",
    ),
    DataSourceContract(
        source="research_report",
        display_name="Research Reports",
        description="Sell-side research report metadata and content used by evidence reasoning.",
        update_frequency="daily",
        expected_arrival="daily early morning",
        threshold_days=3,
        threshold_kind=ThresholdKind.NATURAL_DAY,
        coverage_scope="unknown",
        required_for_reasoning=True,
        local_data_signal="research_report_meta.trade_date",
        monitor_tasks=("reports",),
        acquisition_tasks=(AcquisitionTaskRef("minishare", "reports_history"),),
        job_types=(),
        checkpoint_tasks=(AcquisitionTaskRef("minishare", "reports_history"),),
        owner_module="app.data_pipeline.fetcher",
    ),
)

_CONTRACT_BY_SOURCE = {contract.source: contract for contract in _CONTRACTS}


def list_contracts() -> tuple[DataSourceContract, ...]:
    return _CONTRACTS


def get_contract(source: str) -> DataSourceContract | None:
    return _CONTRACT_BY_SOURCE.get(source)
```

- [ ] **Step 4: Run registry tests**

Run:

```bash
cd backend
.venv/bin/python -m pytest tests/test_readiness_contracts.py -q
```

Expected: `4 passed`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/readiness/contracts.py backend/tests/test_readiness_contracts.py
git commit -m "feat: add data source contract registry"
```

---

### Task 2: Refactor Readiness to Use Contracts

**Files:**
- Modify: `backend/app/readiness/service.py`
- Modify: `backend/tests/test_readiness_service.py`
- Test: `backend/tests/test_readiness_service.py`
- Test: `backend/tests/test_readiness_contracts.py`

**Interfaces:**
- Consumes: `list_contracts()` and `get_contract()` from Task 1.
- Preserves: `SOURCE_SPECS`, `SYNC_ACQUISITION_PAIRS`, `MONITOR_TASK_NAMES`, `INGESTION_JOB_TYPES`.
- Produces: `CHECKPOINT_ACQUISITION_PAIRS`.

- [ ] **Step 1: Write failing mapping test**

Append to `backend/tests/test_readiness_contracts.py`:

```python
def test_readiness_mappings_are_derived_from_contract_registry():
    from app.readiness import service

    announcement = get_contract("announcement")
    assert announcement is not None

    assert service.SOURCE_SPECS["announcement"].threshold_days == announcement.threshold_days
    assert service.MONITOR_TASK_NAMES["announcement"] == announcement.monitor_tasks
    assert service.INGESTION_JOB_TYPES["announcement"] == announcement.job_types
    assert service.SYNC_ACQUISITION_PAIRS["announcement"] == tuple(
        (task.source, task.task_name) for task in announcement.acquisition_tasks
    )
    assert service.CHECKPOINT_ACQUISITION_PAIRS["announcement"] == tuple(
        (task.source, task.task_name) for task in announcement.checkpoint_tasks
    )
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
cd backend
.venv/bin/python -m pytest tests/test_readiness_contracts.py::test_readiness_mappings_are_derived_from_contract_registry -q
```

Expected: FAIL because `CHECKPOINT_ACQUISITION_PAIRS` does not exist yet or mappings are still handwritten.

- [ ] **Step 3: Refactor `service.py` imports and mapping definitions**

In `backend/app/readiness/service.py`, add:

```python
from app.readiness.contracts import list_contracts
```

Replace the current hard-coded `SOURCE_SPECS`, `SYNC_ACQUISITION_PAIRS`, `MONITOR_TASK_NAMES`, and `INGESTION_JOB_TYPES` blocks with:

```python
SOURCE_SPECS: dict[str, SourceSpec] = {
    contract.source: SourceSpec(
        contract.source,
        contract.display_name,
        contract.threshold_days,
        contract.threshold_kind,
        contract.coverage_scope,
        contract.required_for_reasoning,
    )
    for contract in list_contracts()
}

SYNC_ACQUISITION_PAIRS: dict[str, tuple[tuple[str, str], ...]] = {
    contract.source: tuple((task.source, task.task_name) for task in contract.acquisition_tasks)
    for contract in list_contracts()
}

CHECKPOINT_ACQUISITION_PAIRS: dict[str, tuple[tuple[str, str], ...]] = {
    contract.source: tuple((task.source, task.task_name) for task in contract.checkpoint_tasks)
    for contract in list_contracts()
}

MONITOR_TASK_NAMES: dict[str, tuple[str, ...]] = {
    contract.source: contract.monitor_tasks for contract in list_contracts()
}

INGESTION_JOB_TYPES: dict[str, tuple[str, ...]] = {
    contract.source: contract.job_types for contract in list_contracts()
}
```

- [ ] **Step 4: Make checkpoint query use checkpoint-specific pairs**

In `build_checkpoint_query(source: str)`, replace:

```python
pairs = SYNC_ACQUISITION_PAIRS.get(source, ())
```

with:

```python
pairs = CHECKPOINT_ACQUISITION_PAIRS.get(source, ())
```

- [ ] **Step 5: Run readiness and contract tests**

Run:

```bash
cd backend
.venv/bin/python -m pytest tests/test_readiness_contracts.py tests/test_readiness_service.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/readiness/service.py backend/tests/test_readiness_contracts.py
git commit -m "refactor: derive readiness mappings from contracts"
```

---

### Task 3: Contract API Schemas and Endpoints

**Files:**
- Modify: `backend/app/readiness/schemas.py`
- Modify: `backend/app/readiness/api.py`
- Modify: `backend/tests/test_readiness_api.py`

**Interfaces:**
- Consumes: `list_contracts()` and `get_contract()`.
- Produces: `AcquisitionTaskRefOut`, `DataSourceContractOut`.
- Produces: `GET /api/v1/readiness/contracts`.

- [ ] **Step 1: Write failing API test**

Append to `backend/tests/test_readiness_api.py`:

```python
@pytest.mark.asyncio
async def test_readiness_contracts_endpoint():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/readiness/contracts")

    assert resp.status_code == 200
    body = resp.json()
    assert [item["source"] for item in body] == [
        "kline",
        "announcement",
        "irm",
        "news",
        "research_report",
    ]
    announcement = next(item for item in body if item["source"] == "announcement")
    assert announcement["monitor_tasks"] == ["cninfo", "cninfo_enqueue"]
    assert announcement["job_types"] == ["cninfo_announcement_date"]
    assert {"source": "cninfo", "task_name": "announcements_history"} in announcement["checkpoint_tasks"]
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
cd backend
.venv/bin/python -m pytest tests/test_readiness_api.py::test_readiness_contracts_endpoint -q
```

Expected: FAIL with `404` because `/contracts` is not implemented.

- [ ] **Step 3: Add response schemas**

In `backend/app/readiness/schemas.py`, add:

```python
class AcquisitionTaskRefOut(BaseModel):
    source: str
    task_name: str


class DataSourceContractOut(BaseModel):
    source: str
    display_name: str
    description: str
    update_frequency: str
    expected_arrival: str
    threshold_days: int
    threshold_kind: ThresholdKind
    coverage_scope: str
    required_for_reasoning: bool
    local_data_signal: str
    monitor_tasks: list[str]
    acquisition_tasks: list[AcquisitionTaskRefOut]
    job_types: list[str]
    checkpoint_tasks: list[AcquisitionTaskRefOut]
    owner_module: str
```

- [ ] **Step 4: Add contract serializer and route before `/{source}`**

In `backend/app/readiness/api.py`, update imports:

```python
from app.readiness.contracts import DataSourceContract, list_contracts
from app.readiness.schemas import DataSourceContractOut, ReadinessSource, ReadinessSummary
```

Add this helper above route definitions:

```python
def contract_to_response(contract: DataSourceContract) -> DataSourceContractOut:
    return DataSourceContractOut(
        source=contract.source,
        display_name=contract.display_name,
        description=contract.description,
        update_frequency=contract.update_frequency,
        expected_arrival=contract.expected_arrival,
        threshold_days=contract.threshold_days,
        threshold_kind=contract.threshold_kind,
        coverage_scope=contract.coverage_scope,
        required_for_reasoning=contract.required_for_reasoning,
        local_data_signal=contract.local_data_signal,
        monitor_tasks=list(contract.monitor_tasks),
        acquisition_tasks=list(contract.acquisition_tasks),
        job_types=list(contract.job_types),
        checkpoint_tasks=list(contract.checkpoint_tasks),
        owner_module=contract.owner_module,
    )
```

Add this route before `@router.get("/{source}")`:

```python
@router.get("/contracts", response_model=list[DataSourceContractOut])
async def get_readiness_contracts() -> list[DataSourceContractOut]:
    return [contract_to_response(contract) for contract in list_contracts()]
```

- [ ] **Step 5: Run API tests**

Run:

```bash
cd backend
.venv/bin/python -m pytest tests/test_readiness_api.py tests/test_readiness_contracts.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/readiness/schemas.py backend/app/readiness/api.py backend/tests/test_readiness_api.py
git commit -m "feat: expose data source contracts api"
```

---

### Task 4: Sync Health Service

**Files:**
- Modify: `backend/app/readiness/schemas.py`
- Create: `backend/app/readiness/sync_health.py`
- Test: `backend/tests/test_sync_health.py`

**Interfaces:**
- Consumes: `DataReadinessService`, `ReadinessRepository`, `SqlReadinessRepository`, `list_contracts()`, `get_contract()`.
- Produces: `SyncHealthStatus`.
- Produces: `SyncHealthContract`, `SyncHealthSource`, `SyncHealthSummary`.
- Produces: `SyncHealthService.get_all(now: datetime | None = None) -> SyncHealthSummary`.
- Produces: `SyncHealthService.get_source(source: str, now: datetime | None = None) -> SyncHealthSource | None`.

- [ ] **Step 1: Write failing service tests**

Create `backend/tests/test_sync_health.py`:

```python
from datetime import UTC, date, datetime

import pytest

from app.readiness.schemas import SourceStatus, SyncHealthStatus
from app.readiness.service import SourceSyncSnapshot
from app.readiness.sync_health import SyncHealthService


class FakeRepository:
    def __init__(self, data=None, sync=None, data_error=None, sync_error=None):
        self.data = data or {}
        self.sync = sync or {}
        self.data_error = data_error
        self.sync_error = sync_error

    async def get_latest_data_date(self, source: str):
        if self.data_error:
            raise self.data_error
        return self.data.get(source)

    async def get_sync_snapshot(self, source: str):
        if self.sync_error:
            raise self.sync_error
        return self.sync.get(source, SourceSyncSnapshot())


@pytest.mark.asyncio
async def test_sync_health_marks_fresh_source_healthy():
    repo = FakeRepository(
        data={"news": date(2026, 7, 21)},
        sync={
            "news": SourceSyncSnapshot(
                latest_success_at=datetime(2026, 7, 21, 1, 0, tzinfo=UTC),
                latest_attempt_at=datetime(2026, 7, 21, 1, 0, tzinfo=UTC),
                latest_status="success",
            )
        },
    )
    service = SyncHealthService(repository=repo)

    item = await service.get_source("news", now=datetime(2026, 7, 21, 9, 0, tzinfo=UTC))

    assert item is not None
    assert item.overall == SyncHealthStatus.HEALTHY
    assert item.readiness_status == SourceStatus.FRESH
    assert item.contract.monitor_tasks == ["news", "news_sync"]


@pytest.mark.asyncio
async def test_sync_health_marks_stale_source_degraded():
    repo = FakeRepository(data={"announcement": date(2026, 7, 19)})
    service = SyncHealthService(repository=repo)

    item = await service.get_source("announcement", now=datetime(2026, 7, 21, 9, 0, tzinfo=UTC))

    assert item is not None
    assert item.overall == SyncHealthStatus.DEGRADED
    assert item.readiness_status == SourceStatus.STALE


@pytest.mark.asyncio
async def test_sync_health_marks_unresolved_failure_failed():
    repo = FakeRepository(
        data={"irm": date(2026, 7, 21)},
        sync={
            "irm": SourceSyncSnapshot(
                latest_attempt_at=datetime(2026, 7, 21, 2, 0, tzinfo=UTC),
                latest_status="failed",
                last_error="job failed",
                unresolved_failure=True,
            )
        },
    )
    service = SyncHealthService(repository=repo)

    item = await service.get_source("irm", now=datetime(2026, 7, 21, 9, 0, tzinfo=UTC))

    assert item is not None
    assert item.overall == SyncHealthStatus.FAILED
    assert item.unresolved_failure is True
    assert item.last_error == "job failed"


@pytest.mark.asyncio
async def test_sync_health_marks_metadata_warning_degraded():
    repo = FakeRepository(
        data={"research_report": date(2026, 7, 21)},
        sync={"research_report": SourceSyncSnapshot(last_error="sync metadata lookup failed: relation missing")},
    )
    service = SyncHealthService(repository=repo)

    item = await service.get_source("research_report", now=datetime(2026, 7, 21, 9, 0, tzinfo=UTC))

    assert item is not None
    assert item.overall == SyncHealthStatus.DEGRADED
    assert "lookup failed" in (item.last_error or "")


@pytest.mark.asyncio
async def test_sync_health_unknown_source_returns_none():
    service = SyncHealthService(repository=FakeRepository())

    item = await service.get_source("unknown", now=datetime(2026, 7, 21, 9, 0, tzinfo=UTC))

    assert item is None
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
cd backend
.venv/bin/python -m pytest tests/test_sync_health.py -q
```

Expected: FAIL because `app.readiness.sync_health` and `SyncHealthStatus` do not exist.

- [ ] **Step 3: Add sync-health schemas**

In `backend/app/readiness/schemas.py`, add:

```python
class SyncHealthStatus(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILED = "failed"
    UNKNOWN = "unknown"


class SyncHealthContract(BaseModel):
    expected_arrival: str
    threshold_days: int
    threshold_kind: ThresholdKind
    monitor_tasks: list[str]
    job_types: list[str]
    checkpoint_tasks: list[str]


class SyncHealthSource(BaseModel):
    source: str
    display_name: str
    overall: SyncHealthStatus
    contract: SyncHealthContract
    latest_success_at: str | None = None
    latest_attempt_at: str | None = None
    latest_status: str | None = None
    unresolved_failure: bool = False
    last_error: str | None = None
    readiness_status: SourceStatus
    recommendation: str


class SyncHealthSummary(BaseModel):
    as_of: str
    sources: list[SyncHealthSource]
    summary: str
```

- [ ] **Step 4: Implement sync-health service**

Create `backend/app/readiness/sync_health.py`:

```python
from __future__ import annotations

from datetime import datetime

from app.readiness.contracts import DataSourceContract, get_contract, list_contracts
from app.readiness.schemas import (
    SourceStatus,
    SyncHealthContract,
    SyncHealthSource,
    SyncHealthStatus,
    SyncHealthSummary,
)
from app.readiness.service import DataReadinessService, ReadinessRepository, SourceSyncSnapshot, _as_shanghai, _now_utc


def _bounded_error(error: str | None) -> str | None:
    return error[:300] if error else None


def _checkpoint_labels(contract: DataSourceContract) -> list[str]:
    return [f"{task.source}/{task.task_name}" for task in contract.checkpoint_tasks]


def contract_health_view(contract: DataSourceContract) -> SyncHealthContract:
    return SyncHealthContract(
        expected_arrival=contract.expected_arrival,
        threshold_days=contract.threshold_days,
        threshold_kind=contract.threshold_kind,
        monitor_tasks=list(contract.monitor_tasks),
        job_types=list(contract.job_types),
        checkpoint_tasks=_checkpoint_labels(contract),
    )


def classify_sync_health(readiness_status: SourceStatus, sync: SourceSyncSnapshot) -> SyncHealthStatus:
    if sync.unresolved_failure or readiness_status == SourceStatus.FAILED:
        return SyncHealthStatus.FAILED
    if readiness_status in {SourceStatus.STALE, SourceStatus.MISSING}:
        return SyncHealthStatus.DEGRADED
    if sync.last_error and "lookup failed" in sync.last_error:
        return SyncHealthStatus.DEGRADED
    if readiness_status == SourceStatus.FRESH:
        return SyncHealthStatus.HEALTHY
    return SyncHealthStatus.UNKNOWN


class SyncHealthService:
    def __init__(self, repository: ReadinessRepository | None = None):
        self.readiness = DataReadinessService(repository=repository)

    async def get_all(self, now: datetime | None = None) -> SyncHealthSummary:
        as_of = _as_shanghai(now or _now_utc())
        items = []
        for contract in list_contracts():
            item = await self.get_source(contract.source, now=as_of)
            if item is not None:
                items.append(item)
        failed_count = sum(1 for item in items if item.overall == SyncHealthStatus.FAILED)
        degraded_count = sum(1 for item in items if item.overall == SyncHealthStatus.DEGRADED)
        summary = f"{failed_count} 个数据源同步失败，{degraded_count} 个数据源同步降级。"
        if failed_count == 0 and degraded_count == 0:
            summary = "全部数据源同步链路健康。"
        return SyncHealthSummary(as_of=as_of.isoformat(), sources=items, summary=summary)

    async def get_source(self, source: str, now: datetime | None = None) -> SyncHealthSource | None:
        contract = get_contract(source)
        if contract is None:
            return None
        readiness_item = await self.readiness.get_source(source, now=now)
        if readiness_item is None:
            return None
        sync = await self.readiness.repository.get_sync_snapshot(source)
        overall = classify_sync_health(readiness_item.status, sync)
        return SyncHealthSource(
            source=contract.source,
            display_name=contract.display_name,
            overall=overall,
            contract=contract_health_view(contract),
            latest_success_at=sync.latest_success_at.isoformat() if sync.latest_success_at else None,
            latest_attempt_at=sync.latest_attempt_at.isoformat() if sync.latest_attempt_at else None,
            latest_status=sync.latest_status,
            unresolved_failure=sync.unresolved_failure,
            last_error=_bounded_error(sync.last_error),
            readiness_status=readiness_item.status,
            recommendation=readiness_item.recommendation,
        )
```

- [ ] **Step 5: Run sync-health tests**

Run:

```bash
cd backend
.venv/bin/python -m pytest tests/test_sync_health.py -q
```

Expected: `5 passed`.

- [ ] **Step 6: Run readiness regression tests**

Run:

```bash
cd backend
.venv/bin/python -m pytest tests/test_readiness_service.py tests/test_readiness_contracts.py tests/test_sync_health.py -q
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add backend/app/readiness/schemas.py backend/app/readiness/sync_health.py backend/tests/test_sync_health.py
git commit -m "feat: add sync health service"
```

---

### Task 5: Sync Health API

**Files:**
- Modify: `backend/app/readiness/api.py`
- Modify: `backend/tests/test_readiness_api.py`

**Interfaces:**
- Consumes: `SyncHealthService`.
- Produces: `GET /api/v1/readiness/sync-health`.
- Produces: `GET /api/v1/readiness/sync-health/{source}`.

- [ ] **Step 1: Write failing API tests**

Append to `backend/tests/test_readiness_api.py`:

```python
class FakeSyncHealthService:
    async def get_all(self, now=None):
        from app.readiness.schemas import SyncHealthContract, SyncHealthSource, SyncHealthStatus, SyncHealthSummary

        return SyncHealthSummary(
            as_of=datetime(2026, 7, 21, 9, 0, tzinfo=UTC).isoformat(),
            summary="全部数据源同步链路健康。",
            sources=[
                SyncHealthSource(
                    source="kline",
                    display_name="K-line",
                    overall=SyncHealthStatus.HEALTHY,
                    contract=SyncHealthContract(
                        expected_arrival="trading day close + local sync",
                        threshold_days=1,
                        threshold_kind=ThresholdKind.TRADING_DAY,
                        monitor_tasks=["kline"],
                        job_types=[],
                        checkpoint_tasks=["kline/kline", "tushare/kline"],
                    ),
                    readiness_status=SourceStatus.FRESH,
                    recommendation="数据处于日级可靠窗口内。",
                )
            ],
        )

    async def get_source(self, source: str, now=None):
        if source != "kline":
            return None
        return (await self.get_all(now)).sources[0]


@pytest.mark.asyncio
async def test_sync_health_summary_endpoint(monkeypatch):
    import app.readiness.api as api

    monkeypatch.setattr(api, "SyncHealthService", lambda: FakeSyncHealthService())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/readiness/sync-health")

    assert resp.status_code == 200
    body = resp.json()
    assert body["sources"][0]["source"] == "kline"
    assert body["sources"][0]["overall"] == "healthy"


@pytest.mark.asyncio
async def test_sync_health_source_endpoint(monkeypatch):
    import app.readiness.api as api

    monkeypatch.setattr(api, "SyncHealthService", lambda: FakeSyncHealthService())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/readiness/sync-health/kline")

    assert resp.status_code == 200
    assert resp.json()["source"] == "kline"


@pytest.mark.asyncio
async def test_sync_health_unknown_source_404(monkeypatch):
    import app.readiness.api as api

    monkeypatch.setattr(api, "SyncHealthService", lambda: FakeSyncHealthService())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/readiness/sync-health/unknown")

    assert resp.status_code == 404
    assert resp.json()["detail"] == "unknown sync health source: unknown"
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
cd backend
.venv/bin/python -m pytest tests/test_readiness_api.py::test_sync_health_summary_endpoint tests/test_readiness_api.py::test_sync_health_source_endpoint tests/test_readiness_api.py::test_sync_health_unknown_source_404 -q
```

Expected: FAIL with `404` because sync-health routes are not implemented.

- [ ] **Step 3: Add sync-health routes before `/{source}`**

In `backend/app/readiness/api.py`, update imports:

```python
from app.readiness.schemas import DataSourceContractOut, ReadinessSource, ReadinessSummary, SyncHealthSource, SyncHealthSummary
from app.readiness.sync_health import SyncHealthService
```

Add these routes before `@router.get("/{source}")`:

```python
@router.get("/sync-health", response_model=SyncHealthSummary)
async def get_sync_health_summary() -> SyncHealthSummary:
    return await SyncHealthService().get_all()


@router.get("/sync-health/{source}", response_model=SyncHealthSource)
async def get_sync_health_source(source: str) -> SyncHealthSource:
    item = await SyncHealthService().get_source(source)
    if item is None:
        raise HTTPException(status_code=404, detail=f"unknown sync health source: {source}")
    return item
```

- [ ] **Step 4: Run API tests**

Run:

```bash
cd backend
.venv/bin/python -m pytest tests/test_readiness_api.py -q
```

Expected: all readiness API tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/readiness/api.py backend/tests/test_readiness_api.py
git commit -m "feat: expose sync health api"
```

---

### Task 6: Final Verification and Documentation Check

**Files:**
- Read: `docs/superpowers/specs/2026-07-21-data-source-contract-sync-health-design.md`
- Read: `docs/superpowers/plans/2026-07-21-data-source-contract-sync-health.md`

**Interfaces:**
- Verifies all previous task outputs.

- [ ] **Step 1: Run focused phase 3 tests**

Run:

```bash
cd backend
.venv/bin/python -m pytest tests/test_readiness_contracts.py tests/test_sync_health.py tests/test_readiness_api.py -q
```

Expected: all tests pass.

- [ ] **Step 2: Run readiness and Agent freshness regression tests**

Run:

```bash
cd backend
.venv/bin/python -m pytest tests/test_readiness_service.py tests/reasoning/test_freshness_gate.py tests/test_phase31_scheduler.py::test_news_scheduler_records_monitor_status -q
```

Expected: all tests pass.

- [ ] **Step 3: Run reasoning prompt regression tests**

Run:

```bash
cd backend
.venv/bin/python -m pytest tests/reasoning/test_prompt_template.py tests/reasoning/test_message_builder.py tests/reasoning/test_rest_api_reasoning.py -q
```

Expected: all tests pass.

- [ ] **Step 4: Run import smoke**

Run:

```bash
cd backend
.venv/bin/python - <<'PY'
import app.main
from app.readiness.contracts import list_contracts
from app.readiness.sync_health import SyncHealthService
print("ok", len(list_contracts()), SyncHealthService.__name__)
PY
```

Expected output includes:

```text
ok 5 SyncHealthService
```

- [ ] **Step 5: Check diff hygiene**

Run:

```bash
git diff --check
git diff --stat a2b7b4d..HEAD -- backend/app/readiness backend/tests/test_readiness_contracts.py backend/tests/test_sync_health.py backend/tests/test_readiness_api.py docs/superpowers/specs/2026-07-21-data-source-contract-sync-health-design.md docs/superpowers/plans/2026-07-21-data-source-contract-sync-health.md
```

Expected: `git diff --check` has no output. Stat only shows readiness package, readiness tests, and phase 3 docs.

- [ ] **Step 6: Commit plan if not already committed**

If this plan file is still uncommitted, run:

```bash
git add docs/superpowers/plans/2026-07-21-data-source-contract-sync-health.md
git commit -m "docs: add data source contract sync health plan"
```

If the plan was already committed before implementation began, skip this step.

---

## Self-Review

- Spec coverage: Tasks cover the in-code contract registry, readiness mapping refactor, contract API, sync-health service, sync-health API, fail-soft classification, and regression verification. Non-goals are preserved because no task edits scheduler, fetcher, job queue, retry behavior, Agent prompt behavior, external providers, or frontend.
- Placeholder scan: The plan contains no unresolved placeholder markers and every task has concrete paths, test snippets, implementation snippets, commands, and expected outcomes.
- Type consistency: `DataSourceContract`, `AcquisitionTaskRef`, `DataSourceContractOut`, `SyncHealthStatus`, `SyncHealthContract`, `SyncHealthSource`, `SyncHealthSummary`, and `SyncHealthService` are introduced before later tasks consume them.
