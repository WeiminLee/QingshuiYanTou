# System Memory Agent Context Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first-stage system memory and AgentContext layer for the Signal main flow.

**Architecture:** Add a focused `backend/app/reasoning/context/` package containing DTO schemas, a rules-based MemoryRouter, user/signal context assembly, and prompt rendering. Keep `UserMemoryProvider` as the user-memory owner, extend signal DTOs compatibly, then route Agent `signal_id` context through the new builder.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic, SQLAlchemy async sessions, pytest, existing Mongo/Postgres/Neo4j abstractions.

## Global Constraints

- Do not rewrite `UserMemoryProvider`; treat it as User Memory only.
- Do not add external API key requirements.
- Do not add LLM-based routing in this phase.
- Preserve existing `portfolio_hits` fields for backward compatibility.
- Prefer fail-soft context construction: missing optional sources produce warnings instead of breaking Agent calls.
- Use TDD: failing test first, minimal implementation, passing test, commit.
- Do not include untracked `backend/uv.lock` unless explicitly requested.

---

## File Structure

- Create `backend/app/reasoning/context/__init__.py`: public exports for context DTOs, router, and builder.
- Create `backend/app/reasoning/context/schemas.py`: Pydantic DTOs and small helpers.
- Create `backend/app/reasoning/context/router.py`: rules-based MemoryRouter.
- Create `backend/app/reasoning/context/user_snapshot.py`: read portfolio/preferences/watchlist into `UserSnapshotDTO`.
- Create `backend/app/reasoning/context/builder.py`: assemble `AgentContextDTO` and render `prompt_context`.
- Create `backend/tests/reasoning/test_memory_router.py`: route classification tests.
- Create `backend/tests/reasoning/test_agent_context_builder.py`: builder, user hits, fail-soft tests.
- Modify `backend/app/signals/schemas.py`: add v1 DTO-compatible fields while preserving old fields.
- Modify `backend/app/signals/service.py`: add `schema_version`, `source`, `primary_signal`, `memory`, `user_hits`.
- Modify `backend/app/signals/context_provider.py`: format new AgentContext or SignalContext DTO output.
- Modify `backend/app/reasoning/langchain_agent/client.py`: replace direct signal context fetch with `AgentContextBuilder`.
- Modify `backend/app/reasoning/runtime/turn_context.py`: store structured `agent_context`.
- Modify relevant tests under `backend/tests/signals/` and `backend/tests/reasoning/`.

---

### Task 1: MemoryRouter

**Files:**
- Create: `backend/app/reasoning/context/__init__.py`
- Create: `backend/app/reasoning/context/router.py`
- Test: `backend/tests/reasoning/test_memory_router.py`

**Interfaces:**
- Produces: `MemoryRoute` Pydantic model with `route: str`, `reason: str`, `required_context: list[str]`.
- Produces: `MemoryRouter.classify(question: str, *, user_id: str = "", thread_id: str = "", signal_id: str | None = None, page_context: dict | None = None) -> MemoryRoute`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/reasoning/test_memory_router.py`:

```python
from app.reasoning.context.router import MemoryRouter


def test_signal_id_routes_to_relation_reasoning():
    result = MemoryRouter().classify("请分析这个信号", signal_id="SIG:abc")

    assert result.route == "relation_reasoning"
    assert result.reason == "signal_id provided"
    assert "signal_context" in result.required_context


def test_portfolio_question_routes_to_factual_lookup():
    result = MemoryRouter().classify("我是否持有中际旭创？")

    assert result.route == "factual_lookup"
    assert result.required_context == ["user_snapshot"]


def test_long_history_question_routes_to_broad_synthesis():
    result = MemoryRouter().classify("总结过去一个月我关注方向的变化")

    assert result.route == "broad_synthesis"
    assert "user_snapshot" in result.required_context


def test_default_routes_to_relation_reasoning():
    result = MemoryRouter().classify("光模块怎么看？")

    assert result.route == "relation_reasoning"
    assert result.reason == "default"
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
cd backend && pytest tests/reasoning/test_memory_router.py -q
```

Expected: import failure because `app.reasoning.context.router` does not exist.

- [ ] **Step 3: Implement minimal router**

Create `backend/app/reasoning/context/router.py`:

```python
from __future__ import annotations

from pydantic import BaseModel, Field


class MemoryRoute(BaseModel):
    route: str
    reason: str
    required_context: list[str] = Field(default_factory=list)


class MemoryRouter:
    def classify(
        self,
        question: str,
        *,
        user_id: str = "",
        thread_id: str = "",
        signal_id: str | None = None,
        page_context: dict | None = None,
    ) -> MemoryRoute:
        text = question or ""
        if signal_id:
            return MemoryRoute(
                route="relation_reasoning",
                reason="signal_id provided",
                required_context=["user_snapshot", "signal_context", "readiness_context"],
            )
        if any(key in text for key in ["过去", "最近一个月", "总结", "复盘", "长期", "变化趋势"]):
            return MemoryRoute(
                route="broad_synthesis",
                reason="long history keyword",
                required_context=["user_snapshot"],
            )
        if any(key in text for key in ["我是否", "我有没有", "我的持仓", "我的关注"]):
            return MemoryRoute(
                route="factual_lookup",
                reason="user fact keyword",
                required_context=["user_snapshot"],
            )
        if any(key in text for key in ["这个信号", "传导", "影响我的持仓", "产业链", "二阶"]):
            return MemoryRoute(
                route="relation_reasoning",
                reason="relation keyword",
                required_context=["user_snapshot", "signal_context", "readiness_context"],
            )
        return MemoryRoute(
            route="relation_reasoning",
            reason="default",
            required_context=["user_snapshot", "readiness_context"],
        )
```

Create `backend/app/reasoning/context/__init__.py`:

```python
from app.reasoning.context.router import MemoryRoute, MemoryRouter

__all__ = ["MemoryRoute", "MemoryRouter"]
```

- [ ] **Step 4: Run tests to verify pass**

Run:

```bash
cd backend && pytest tests/reasoning/test_memory_router.py -q
```

Expected: `4 passed`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/reasoning/context/__init__.py backend/app/reasoning/context/router.py backend/tests/reasoning/test_memory_router.py
git commit -m "feat: add memory route classifier"
```

---

### Task 2: Context DTO Schemas

**Files:**
- Create: `backend/app/reasoning/context/schemas.py`
- Modify: `backend/app/reasoning/context/__init__.py`
- Test: `backend/tests/reasoning/test_agent_context_schemas.py`

**Interfaces:**
- Produces DTO classes: `UserSnapshotDTO`, `UserHitDTO`, `SignalMemoryDTO`, `SignalContextDTO`, `ReadinessContextDTO`, `AgentContextDTO`.
- Later tasks import these classes from `app.reasoning.context.schemas`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/reasoning/test_agent_context_schemas.py`:

```python
from app.reasoning.context.schemas import AgentContextDTO, SignalMemoryDTO, UserSnapshotDTO


def test_user_snapshot_defaults_are_empty_lists():
    dto = UserSnapshotDTO(user_id="lwm")

    assert dto.schema_version == "user.snapshot.v1"
    assert dto.portfolio == []
    assert dto.watchlist == []
    assert dto.preferences == []


def test_signal_memory_defaults_are_stable():
    dto = SignalMemoryDTO(signal_id="SIG:abc")

    assert dto.schema_version == "signal.memory.v1"
    assert dto.lifecycle_status == "active"
    assert dto.user_status == "new"
    assert dto.reinforced_count == 0
    assert dto.source_count == 1


def test_agent_context_defaults_include_warnings():
    dto = AgentContextDTO(
        context_type="signal_research",
        route="relation_reasoning",
        user_id="lwm",
        thread_id="t1",
        question="q",
    )

    assert dto.schema_version == "agent.context.v1"
    assert dto.warnings == []
    assert dto.prompt_context == ""
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
cd backend && pytest tests/reasoning/test_agent_context_schemas.py -q
```

Expected: import failure because `schemas.py` does not exist.

- [ ] **Step 3: Implement schemas**

Create `backend/app/reasoning/context/schemas.py`:

```python
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class UserSnapshotDTO(BaseModel):
    schema_version: str = "user.snapshot.v1"
    user_id: str
    portfolio: list[dict[str, Any]] = Field(default_factory=list)
    watchlist: list[dict[str, Any]] = Field(default_factory=list)
    preferences: list[dict[str, Any]] = Field(default_factory=list)


class UserHitDTO(BaseModel):
    portfolio: list[str] = Field(default_factory=list)
    watchlist: list[str] = Field(default_factory=list)
    preferences: list[str] = Field(default_factory=list)


class SignalMemoryDTO(BaseModel):
    schema_version: str = "signal.memory.v1"
    signal_id: str
    lifecycle_status: str = "active"
    user_status: str = "new"
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None
    reinforced_count: int = 0
    contradicted_count: int = 0
    source_count: int = 1


class ReadinessContextDTO(BaseModel):
    overall_status: str = "unknown"
    answer_boundary: str = ""


class SignalContextDTO(BaseModel):
    schema_version: str = "signal.context.v1"
    signal: dict[str, Any] = Field(default_factory=dict)
    source: dict[str, Any] = Field(default_factory=dict)
    primary_signal: dict[str, Any] = Field(default_factory=dict)
    memory: SignalMemoryDTO | None = None
    user_hits: UserHitDTO = Field(default_factory=UserHitDTO)
    portfolio_hits: list[str] = Field(default_factory=list)
    propagations: list[dict[str, Any]] = Field(default_factory=list)


class AgentContextDTO(BaseModel):
    schema_version: str = "agent.context.v1"
    context_type: str
    route: str
    user_id: str
    thread_id: str
    question: str
    user_snapshot: UserSnapshotDTO | None = None
    signal_context: SignalContextDTO | None = None
    readiness_context: ReadinessContextDTO = Field(default_factory=ReadinessContextDTO)
    prompt_context: str = ""
    warnings: list[str] = Field(default_factory=list)
```

Modify `backend/app/reasoning/context/__init__.py`:

```python
from app.reasoning.context.router import MemoryRoute, MemoryRouter
from app.reasoning.context.schemas import (
    AgentContextDTO,
    ReadinessContextDTO,
    SignalContextDTO,
    SignalMemoryDTO,
    UserHitDTO,
    UserSnapshotDTO,
)

__all__ = [
    "AgentContextDTO",
    "MemoryRoute",
    "MemoryRouter",
    "ReadinessContextDTO",
    "SignalContextDTO",
    "SignalMemoryDTO",
    "UserHitDTO",
    "UserSnapshotDTO",
]
```

- [ ] **Step 4: Run tests to verify pass**

Run:

```bash
cd backend && pytest tests/reasoning/test_agent_context_schemas.py -q
```

Expected: `3 passed`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/reasoning/context/__init__.py backend/app/reasoning/context/schemas.py backend/tests/reasoning/test_agent_context_schemas.py
git commit -m "feat: add agent context dto schemas"
```

---

### Task 3: UserSnapshot Builder

**Files:**
- Create: `backend/app/reasoning/context/user_snapshot.py`
- Test: `backend/tests/reasoning/test_user_snapshot_builder.py`

**Interfaces:**
- Produces: `async build_user_snapshot(user_id: str) -> tuple[UserSnapshotDTO, list[str]]`.
- Uses account portfolio via `app.account.services.portfolio_service.list_for_user`.
- Uses Mongo preferences collection `agent_preferences`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/reasoning/test_user_snapshot_builder.py`:

```python
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import app.reasoning.context.user_snapshot as us
from app.reasoning.context.user_snapshot import build_user_snapshot


@pytest.mark.asyncio
async def test_build_user_snapshot_reads_portfolio_and_preferences(monkeypatch):
    monkeypatch.setattr(
        us,
        "_list_portfolio",
        AsyncMock(return_value=[SimpleNamespace(ts_code="300308.SZ", stock_name="中际旭创")]),
    )
    pref_collection = MagicMock()
    pref_collection.find_one = AsyncMock(return_value={
        "items": [{"subject": "光模块", "subject_type": "concept", "stance": "关注", "reason": "AI算力"}]
    })
    monkeypatch.setattr(us, "_get_collection", lambda name: pref_collection)

    snapshot, warnings = await build_user_snapshot("lwm")

    assert warnings == []
    assert snapshot.portfolio == [{"ts_code": "300308.SZ", "name": "中际旭创"}]
    assert snapshot.preferences[0]["subject"] == "光模块"


@pytest.mark.asyncio
async def test_build_user_snapshot_fail_soft_on_portfolio_error(monkeypatch):
    async def raise_portfolio(*args, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(us, "_list_portfolio", raise_portfolio)
    pref_collection = MagicMock()
    pref_collection.find_one = AsyncMock(return_value=None)
    monkeypatch.setattr(us, "_get_collection", lambda name: pref_collection)

    snapshot, warnings = await build_user_snapshot("lwm")

    assert snapshot.portfolio == []
    assert "portfolio_read_failed" in warnings
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
cd backend && pytest tests/reasoning/test_user_snapshot_builder.py -q
```

Expected: import failure because `user_snapshot.py` does not exist.

- [ ] **Step 3: Implement builder**

Create `backend/app/reasoning/context/user_snapshot.py`:

```python
from __future__ import annotations

from typing import Any

from app.reasoning.context.schemas import UserSnapshotDTO
from app.reasoning.langchain_agent.memory.user_memory_provider import PREF_COLLECTION


async def _list_portfolio(user_id: str):
    from app.core.database import async_session
    from app.account.services.portfolio_service import list_for_user

    async with async_session() as session:
        return await list_for_user(session, user_id)


def _get_collection(name: str):
    from app.core.mongodb import get_mongo_db

    return get_mongo_db()[name]


async def build_user_snapshot(user_id: str) -> tuple[UserSnapshotDTO, list[str]]:
    warnings: list[str] = []
    portfolio: list[dict[str, Any]] = []
    preferences: list[dict[str, Any]] = []

    try:
        rows = await _list_portfolio(user_id)
        for row in rows:
            portfolio.append(
                {
                    "ts_code": str(getattr(row, "ts_code", "") or ""),
                    "name": str(getattr(row, "stock_name", "") or getattr(row, "name", "") or ""),
                }
            )
    except Exception:
        warnings.append("portfolio_read_failed")

    try:
        doc = await _get_collection(PREF_COLLECTION).find_one({"user_id": user_id})
        preferences = list((doc or {}).get("items", []) or [])
    except Exception:
        warnings.append("preferences_read_failed")

    return UserSnapshotDTO(user_id=user_id, portfolio=portfolio, preferences=preferences), warnings
```

- [ ] **Step 4: Run tests to verify pass**

Run:

```bash
cd backend && pytest tests/reasoning/test_user_snapshot_builder.py -q
```

Expected: `2 passed`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/reasoning/context/user_snapshot.py backend/tests/reasoning/test_user_snapshot_builder.py
git commit -m "feat: build user snapshot context"
```

---

### Task 4: SignalContext DTO Assembly

**Files:**
- Modify: `backend/app/signals/schemas.py`
- Modify: `backend/app/signals/service.py`
- Test: `backend/tests/signals/test_api.py`

**Interfaces:**
- Extends `get_signal_detail(session, signal_id: str) -> dict | None` output with:
  - `schema_version`
  - `source`
  - `primary_signal`
  - `memory`
  - `user_hits`
- Preserves existing fields including `portfolio_hits`.

- [ ] **Step 1: Add failing API/schema assertions**

Append to `backend/tests/signals/test_api.py`:

```python
@pytest.mark.asyncio
async def test_get_signal_detail_accepts_context_dto_fields(monkeypatch):
    async def fake_get_signal_detail(*args, **kwargs):
        return {
            "schema_version": "signal.context.v1",
            "signal_id": "SIG:abc",
            "title": "800G 光模块规模量产",
            "summary": "量产确认",
            "source_type": "announcement",
            "source_title": "公告标题",
            "source_url": None,
            "published_at": datetime(2026, 7, 13, tzinfo=UTC),
            "subject_name": "光模块",
            "subject_type": "product",
            "signal_type": "mass_production",
            "polarity": "positive",
            "strength": 88,
            "confidence": 0.92,
            "value_score": 92,
            "evidence_excerpt": "相关产品进入规模量产",
            "status": "new",
            "portfolio_hits": ["中际旭创"],
            "source": {"type": "announcement", "id": "EV:1", "title": "公告标题", "url": None},
            "primary_signal": {"subject_name": "光模块", "signal_type": "mass_production"},
            "memory": {"schema_version": "signal.memory.v1", "signal_id": "SIG:abc", "lifecycle_status": "active", "user_status": "new"},
            "user_hits": {"portfolio": ["中际旭创"], "watchlist": [], "preferences": ["光模块"]},
            "propagations": [],
        }

    monkeypatch.setattr("app.signals.api.get_signal_detail", fake_get_signal_detail)

    async with AsyncClient(transport=ASGITransport(app=_test_app()), base_url="http://test") as client:
        res = await client.get("/api/v1/signals/SIG:abc")

    assert res.status_code == 200
    body = res.json()
    assert body["schema_version"] == "signal.context.v1"
    assert body["user_hits"]["preferences"] == ["光模块"]
    assert body["memory"]["lifecycle_status"] == "active"
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
cd backend && pytest tests/signals/test_api.py::test_get_signal_detail_accepts_context_dto_fields -q
```

Expected: response validation fails because `SignalDetail` schema lacks new fields.

- [ ] **Step 3: Extend signal schemas and service output**

Modify `backend/app/signals/schemas.py` by adding:

```python
class SignalUserHits(BaseModel):
    portfolio: list[str] = Field(default_factory=list)
    watchlist: list[str] = Field(default_factory=list)
    preferences: list[str] = Field(default_factory=list)


class SignalMemoryOut(BaseModel):
    schema_version: str = "signal.memory.v1"
    signal_id: str
    lifecycle_status: str = "active"
    user_status: str = "new"
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None
    reinforced_count: int = 0
    contradicted_count: int = 0
    source_count: int = 1
```

Then extend `SignalDetail`:

```python
    schema_version: str = "signal.context.v1"
    source: dict[str, Any] = Field(default_factory=dict)
    primary_signal: dict[str, Any] = Field(default_factory=dict)
    memory: SignalMemoryOut | None = None
    user_hits: SignalUserHits = Field(default_factory=SignalUserHits)
```

Modify `backend/app/signals/service.py` `get_signal_detail()` return dict to include:

```python
        "schema_version": "signal.context.v1",
        "source": {
            "type": signal.source_type,
            "id": signal.source_id,
            "title": signal.source_title,
            "url": signal.source_url,
            "published_at": signal.published_at,
        },
        "primary_signal": {
            "subject_name": signal.subject_name,
            "subject_type": signal.subject_type,
            "signal_type": signal.signal_type,
            "polarity": signal.polarity,
            "strength": signal.strength,
            "confidence": _to_float(signal.confidence),
            "evidence_excerpt": signal.evidence_excerpt,
        },
        "memory": {
            "schema_version": "signal.memory.v1",
            "signal_id": signal.signal_id,
            "lifecycle_status": (signal.metadata_ or {}).get("lifecycle", "active"),
            "user_status": signal.status,
            "first_seen_at": signal.created_at,
            "last_seen_at": signal.updated_at or signal.detected_at,
            "reinforced_count": int((signal.metadata_ or {}).get("reinforced_count", 0) or 0),
            "contradicted_count": int((signal.metadata_ or {}).get("contradicted_count", 0) or 0),
            "source_count": int((signal.metadata_ or {}).get("source_count", 1) or 1),
        },
        "user_hits": {
            "portfolio": _portfolio_hits(signal.metadata_),
            "watchlist": [],
            "preferences": [],
        },
```

- [ ] **Step 4: Run targeted tests**

Run:

```bash
cd backend && pytest tests/signals/test_api.py -q
```

Expected: all signal API tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/signals/schemas.py backend/app/signals/service.py backend/tests/signals/test_api.py
git commit -m "feat: expose signal context dto fields"
```

---

### Task 5: AgentContextBuilder and Prompt Rendering

**Files:**
- Create: `backend/app/reasoning/context/builder.py`
- Modify: `backend/app/reasoning/context/__init__.py`
- Test: `backend/tests/reasoning/test_agent_context_builder.py`

**Interfaces:**
- Produces: `AgentContextBuilder.build(user_id: str, thread_id: str, question: str, signal_id: str | None = None, page_context: dict | None = None) -> AgentContextDTO`.
- Produces: `match_user_hits(signal_detail: dict, user_snapshot: UserSnapshotDTO) -> UserHitDTO`.

- [ ] **Step 1: Write failing tests**

Create `backend/tests/reasoning/test_agent_context_builder.py`:

```python
from unittest.mock import AsyncMock

import pytest

import app.reasoning.context.builder as builder_mod
from app.reasoning.context.builder import AgentContextBuilder, match_user_hits
from app.reasoning.context.schemas import UserSnapshotDTO


def test_match_user_hits_uses_signal_path_nodes_and_preferences():
    detail = {
        "subject_name": "中际旭创",
        "propagations": [{"target_name": "光芯片", "signal_path": {"nodes": ["中际旭创", "光模块", "光芯片"]}}],
    }
    snapshot = UserSnapshotDTO(
        user_id="lwm",
        portfolio=[{"ts_code": "300308.SZ", "name": "中际旭创"}],
        preferences=[{"subject": "光模块", "stance": "关注"}],
    )

    hits = match_user_hits(detail, snapshot)

    assert hits.portfolio == ["中际旭创"]
    assert hits.preferences == ["光模块"]


@pytest.mark.asyncio
async def test_builder_with_signal_id_builds_prompt_context(monkeypatch):
    async def fake_snapshot(user_id):
        return UserSnapshotDTO(user_id=user_id, portfolio=[{"name": "中际旭创", "ts_code": "300308.SZ"}]), []

    async def fake_signal(signal_id):
        return {
            "signal_id": signal_id,
            "title": "800G 光模块规模量产",
            "summary": "量产确认",
            "source_type": "announcement",
            "subject_name": "中际旭创",
            "subject_type": "company",
            "signal_type": "mass_production",
            "polarity": "positive",
            "value_score": 92,
            "confidence": 0.92,
            "evidence_excerpt": "相关产品已进入规模量产阶段",
            "memory": {"schema_version": "signal.memory.v1", "signal_id": signal_id, "lifecycle_status": "active", "user_status": "new"},
            "propagations": [{"reasoning": "上游需求增强", "signal_path": {"nodes": ["中际旭创", "光模块"], "edges": [], "hops": 1, "confidence": 0.8}}],
        }

    monkeypatch.setattr(builder_mod, "build_user_snapshot", fake_snapshot)
    monkeypatch.setattr(builder_mod, "_load_signal_detail", fake_signal)
    monkeypatch.setattr(builder_mod, "_load_readiness_context", AsyncMock(return_value={"overall_status": "fresh", "answer_boundary": "fresh"}))

    ctx = await AgentContextBuilder().build(user_id="lwm", thread_id="t1", question="分析信号", signal_id="SIG:abc")

    assert ctx.route == "relation_reasoning"
    assert ctx.signal_context is not None
    assert "800G 光模块规模量产" in ctx.prompt_context
    assert "<agent-context>" in ctx.prompt_context


@pytest.mark.asyncio
async def test_builder_relation_without_signal_warns(monkeypatch):
    async def fake_snapshot(user_id):
        return UserSnapshotDTO(user_id=user_id), []

    monkeypatch.setattr(builder_mod, "build_user_snapshot", fake_snapshot)
    monkeypatch.setattr(builder_mod, "_load_readiness_context", AsyncMock(return_value={"overall_status": "unknown", "answer_boundary": ""}))

    ctx = await AgentContextBuilder().build(user_id="lwm", thread_id="t1", question="光模块怎么看")

    assert "signal_context_missing" in ctx.warnings
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
cd backend && pytest tests/reasoning/test_agent_context_builder.py -q
```

Expected: import failure because `builder.py` does not exist.

- [ ] **Step 3: Implement builder**

Create `backend/app/reasoning/context/builder.py` with focused functions:

```python
from __future__ import annotations

from typing import Any

from app.reasoning.context.router import MemoryRouter
from app.reasoning.context.schemas import (
    AgentContextDTO,
    ReadinessContextDTO,
    SignalContextDTO,
    SignalMemoryDTO,
    UserHitDTO,
    UserSnapshotDTO,
)
from app.reasoning.context.user_snapshot import build_user_snapshot


async def _load_signal_detail(signal_id: str) -> dict | None:
    from app.core.database import async_session
    from app.signals.service import get_signal_detail

    async with async_session() as session:
        return await get_signal_detail(session, signal_id)


async def _load_readiness_context() -> dict[str, str]:
    try:
        from app.reasoning.langchain_agent.freshness import load_freshness_context

        text = await load_freshness_context()
        return {"overall_status": _extract_line(text, "overall_status") or "unknown", "answer_boundary": _extract_line(text, "answer_boundary")}
    except Exception:
        return {"overall_status": "unavailable", "answer_boundary": ""}


def _extract_line(text: str, key: str) -> str:
    prefix = f"{key}="
    for line in (text or "").splitlines():
        if line.startswith(prefix):
            return line[len(prefix):].strip()
    return ""


def match_user_hits(signal_detail: dict, user_snapshot: UserSnapshotDTO) -> UserHitDTO:
    candidates = _candidate_names(signal_detail)
    return UserHitDTO(
        portfolio=_match_items(candidates, user_snapshot.portfolio, ["name", "ts_code"]),
        watchlist=_match_items(candidates, user_snapshot.watchlist, ["name", "ts_code"]),
        preferences=_match_items(candidates, user_snapshot.preferences, ["subject"]),
    )


def _candidate_names(signal_detail: dict) -> list[str]:
    values: list[str] = []
    for key in ["subject_name"]:
        if signal_detail.get(key):
            values.append(str(signal_detail[key]))
    for prop in signal_detail.get("propagations") or []:
        if prop.get("target_name"):
            values.append(str(prop["target_name"]))
        path = prop.get("signal_path") or {}
        values.extend(str(node) for node in path.get("nodes") or [] if node)
    seen: set[str] = set()
    return [item for item in values if item and not (item in seen or seen.add(item))]


def _match_items(candidates: list[str], rows: list[dict[str, Any]], keys: list[str]) -> list[str]:
    hits: list[str] = []
    for row in rows:
        label = str(row.get(keys[0]) or "")
        for key in keys:
            value = str(row.get(key) or "")
            if value and _matches_any(value, candidates):
                hits.append(label or value)
                break
    return list(dict.fromkeys(hits))


def _matches_any(value: str, candidates: list[str]) -> bool:
    if value in candidates:
        return True
    if len(value) >= 2:
        return any(value in candidate or candidate in value for candidate in candidates if len(candidate) >= 2)
    return False


class AgentContextBuilder:
    def __init__(self, router: MemoryRouter | None = None):
        self.router = router or MemoryRouter()

    async def build(
        self,
        *,
        user_id: str,
        thread_id: str,
        question: str,
        signal_id: str | None = None,
        page_context: dict | None = None,
    ) -> AgentContextDTO:
        route = self.router.classify(question, user_id=user_id, thread_id=thread_id, signal_id=signal_id, page_context=page_context)
        user_snapshot, warnings = await build_user_snapshot(user_id)
        readiness = ReadinessContextDTO(**await _load_readiness_context())
        signal_context = None
        if signal_id:
            detail = await _load_signal_detail(signal_id)
            if detail:
                hits = match_user_hits(detail, user_snapshot)
                detail["user_hits"] = hits.model_dump()
                detail["portfolio_hits"] = hits.portfolio or detail.get("portfolio_hits", [])
                memory = detail.get("memory") or {"schema_version": "signal.memory.v1", "signal_id": signal_id}
                signal_context = SignalContextDTO(
                    signal=_signal_summary(detail),
                    source=detail.get("source") or {},
                    primary_signal=detail.get("primary_signal") or {},
                    memory=SignalMemoryDTO(**memory),
                    user_hits=hits,
                    portfolio_hits=detail.get("portfolio_hits") or [],
                    propagations=detail.get("propagations") or [],
                )
            else:
                warnings.append("signal_context_missing")
        elif route.route == "relation_reasoning":
            warnings.append("signal_context_missing")
        if route.route == "broad_synthesis":
            warnings.append("long_history_synthesis_not_enabled")
        ctx = AgentContextDTO(
            context_type="signal_research" if signal_context else "general_research",
            route=route.route,
            user_id=user_id,
            thread_id=thread_id,
            question=question,
            user_snapshot=user_snapshot,
            signal_context=signal_context,
            readiness_context=readiness,
            warnings=warnings,
        )
        ctx.prompt_context = render_prompt_context(ctx)
        return ctx


def _signal_summary(detail: dict) -> dict[str, Any]:
    keys = ["signal_id", "title", "summary", "source_type", "published_at", "subject_name", "subject_type", "signal_type", "polarity", "value_score", "confidence"]
    return {key: detail.get(key) for key in keys if key in detail}


def render_prompt_context(ctx: AgentContextDTO) -> str:
    lines = ["<agent-context>", f"route: {ctx.route}"]
    if ctx.user_snapshot:
        portfolio = "、".join(item.get("name") or item.get("ts_code", "") for item in ctx.user_snapshot.portfolio)
        prefs = "、".join(item.get("subject", "") for item in ctx.user_snapshot.preferences)
        lines.extend(["", "<user-snapshot>", f"- 持仓: {portfolio}" if portfolio else "- 持仓: ", f"- 偏好: {prefs}" if prefs else "- 偏好: ", "</user-snapshot>"])
    if ctx.signal_context:
        sig = ctx.signal_context.signal
        lines.extend(["", "<signal-context>", f"- 信号: {sig.get('title', '')}", f"  signal_id: {sig.get('signal_id', '')}", f"  value_score: {sig.get('value_score', '')}, confidence: {sig.get('confidence', '')}"])
        if ctx.signal_context.primary_signal.get("evidence_excerpt"):
            lines.append(f"  原文锚点: {ctx.signal_context.primary_signal['evidence_excerpt']}")
        if ctx.signal_context.memory:
            lines.append(f"  生命周期: {ctx.signal_context.memory.lifecycle_status}, 用户状态: {ctx.signal_context.memory.user_status}")
        hits = ctx.signal_context.user_hits
        if hits.portfolio or hits.watchlist or hits.preferences:
            lines.append(f"  用户命中: portfolio={','.join(hits.portfolio)}; watchlist={','.join(hits.watchlist)}; preferences={','.join(hits.preferences)}")
        for prop in ctx.signal_context.propagations[:5]:
            path = prop.get("signal_path") or {}
            nodes = " -> ".join(str(node) for node in path.get("nodes") or [] if node)
            if nodes:
                lines.append(f"  传导: {nodes}")
            if prop.get("reasoning"):
                lines.append(f"  理由: {prop['reasoning']}")
        lines.append("</signal-context>")
    lines.extend(["", "<data-readiness-summary>", f"overall_status: {ctx.readiness_context.overall_status}", f"answer_boundary: {ctx.readiness_context.answer_boundary}", "</data-readiness-summary>"])
    if ctx.warnings:
        lines.append(f"warnings: {', '.join(ctx.warnings)}")
    lines.append("</agent-context>")
    return "\n".join(lines)
```

Modify `backend/app/reasoning/context/__init__.py` to export `AgentContextBuilder` and `match_user_hits`.

- [ ] **Step 4: Run tests to verify pass**

Run:

```bash
cd backend && pytest tests/reasoning/test_agent_context_builder.py -q
```

Expected: `3 passed`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/reasoning/context/__init__.py backend/app/reasoning/context/builder.py backend/tests/reasoning/test_agent_context_builder.py
git commit -m "feat: build agent signal context"
```

---

### Task 6: Agent Signal Context Integration

**Files:**
- Modify: `backend/app/reasoning/langchain_agent/client.py`
- Modify: `backend/app/reasoning/runtime/turn_context.py`
- Test: `backend/tests/reasoning/test_v2_agent_integration.py`

**Interfaces:**
- Consumes: `AgentContextBuilder.build(...) -> AgentContextDTO`.
- Produces: `AgentTurnContext.agent_context: dict[str, Any]`.
- `system_prompt` receives `agent_context.prompt_context` through the existing `signal_context` prompt slot.

- [ ] **Step 1: Write failing focused test**

Append to `backend/tests/reasoning/test_v2_agent_integration.py`:

```python
def test_agent_turn_context_accepts_agent_context_metadata():
    from app.reasoning.runtime.turn_context import AgentTurnContext

    ctx = AgentTurnContext(run_id="r1", thread_id="t1", question="q", freshness_context="")
    ctx.agent_context = {"route": "relation_reasoning", "warnings": []}

    assert ctx.agent_context["route"] == "relation_reasoning"
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
cd backend && pytest tests/reasoning/test_v2_agent_integration.py::test_agent_turn_context_accepts_agent_context_metadata -q
```

Expected: failure because `AgentTurnContext` has no `agent_context` field if dataclass slots or strict checks apply; if it passes dynamically, still proceed to explicit field implementation for trace consistency.

- [ ] **Step 3: Add explicit turn context field**

Modify `backend/app/reasoning/runtime/turn_context.py`:

```python
    agent_context: dict[str, Any] = field(default_factory=dict)
```

Add it to `to_trace_inputs()`:

```python
            "agent_context": self.agent_context,
```

- [ ] **Step 4: Integrate builder in client**

In `backend/app/reasoning/langchain_agent/client.py`, replace the `Signal Context 注入` block with:

```python
            agent_context_payload = {}
            if signal_id:
                try:
                    from app.reasoning.context.builder import AgentContextBuilder

                    agent_context = await AgentContextBuilder().build(
                        user_id=user_id or "",
                        thread_id=thread_id,
                        question=question,
                        signal_id=signal_id,
                    )
                    signal_context = agent_context.prompt_context
                    agent_context_payload = agent_context.model_dump(mode="json")
                except Exception:
                    logger.warning("[AgentContext] build failed, running without signal context")
                    signal_context = ""
                    agent_context_payload = {}
```

When constructing `AgentTurnContext`, pass:

```python
            agent_context=agent_context_payload,
```

- [ ] **Step 5: Run targeted tests**

Run:

```bash
cd backend && pytest tests/reasoning/test_v2_agent_integration.py::test_agent_turn_context_accepts_agent_context_metadata tests/reasoning/test_trace_metadata.py -q
```

Expected: targeted tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/reasoning/langchain_agent/client.py backend/app/reasoning/runtime/turn_context.py backend/tests/reasoning/test_v2_agent_integration.py
git commit -m "feat: inject agent context for signal runs"
```

---

### Task 7: Signal Context Provider Compatibility

**Files:**
- Modify: `backend/app/signals/context_provider.py`
- Test: `backend/tests/signals/test_context_provider.py`

**Interfaces:**
- Consumes old `SignalDetail` dicts and new `SignalContextDTO`-shaped dicts.
- Produces existing `<signal-context>` text for backward compatibility.

- [ ] **Step 1: Add failing compatibility test**

Append to `backend/tests/signals/test_context_provider.py`:

```python
def test_format_signal_context_reads_user_hits_and_memory():
    context = format_signal_context(
        {
            "schema_version": "signal.context.v1",
            "signal_id": "SIG:abc",
            "title": "800G 光模块规模量产",
            "source_type": "announcement",
            "value_score": 92,
            "confidence": 0.92,
            "evidence_excerpt": "相关产品已进入规模量产阶段",
            "user_hits": {"portfolio": ["中际旭创"], "watchlist": [], "preferences": ["光模块"]},
            "memory": {"lifecycle_status": "active", "user_status": "new"},
            "propagations": [],
        }
    )

    assert "相关持仓: 中际旭创" in context
    assert "用户偏好: 光模块" in context
    assert "生命周期: active" in context
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
cd backend && pytest tests/signals/test_context_provider.py::test_format_signal_context_reads_user_hits_and_memory -q
```

Expected: fails because formatter only reads `portfolio_hits` and not `memory`.

- [ ] **Step 3: Update formatter**

Modify `backend/app/signals/context_provider.py`:

```python
    user_hits = detail.get("user_hits") or {}
    hits = user_hits.get("portfolio") or detail.get("portfolio_hits") or []
    preferences = user_hits.get("preferences") or []
    memory = detail.get("memory") or {}
```

Before closing tag, append:

```python
    if memory.get("lifecycle_status"):
        parts.append(f"  生命周期: {memory.get('lifecycle_status')}, 用户状态: {memory.get('user_status', '')}")
    if preferences:
        parts.append(f"  用户偏好: {'、'.join(str(item) for item in preferences if item)}")
```

- [ ] **Step 4: Run tests to verify pass**

Run:

```bash
cd backend && pytest tests/signals/test_context_provider.py -q
```

Expected: all context provider tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/signals/context_provider.py backend/tests/signals/test_context_provider.py
git commit -m "feat: format signal memory context"
```

---

### Task 8: Final Regression and Documentation Check

**Files:**
- Modify only if required by test failures.

**Interfaces:**
- Verifies all prior tasks work together.

- [ ] **Step 1: Run focused backend regression**

Run:

```bash
cd backend && pytest tests/reasoning/test_memory_router.py tests/reasoning/test_agent_context_schemas.py tests/reasoning/test_user_snapshot_builder.py tests/reasoning/test_agent_context_builder.py tests/signals/test_api.py tests/signals/test_context_provider.py tests/reasoning/test_freshness_gate.py -q
```

Expected: all selected tests pass.

- [ ] **Step 2: Run lint on touched files**

Run:

```bash
cd backend && ruff check app/reasoning/context app/signals/schemas.py app/signals/service.py app/signals/context_provider.py app/reasoning/runtime/turn_context.py app/reasoning/langchain_agent/client.py tests/reasoning/test_memory_router.py tests/reasoning/test_agent_context_schemas.py tests/reasoning/test_user_snapshot_builder.py tests/reasoning/test_agent_context_builder.py tests/signals/test_api.py tests/signals/test_context_provider.py
```

Expected: no lint errors.

- [ ] **Step 3: Check git diff hygiene**

Run:

```bash
git diff --check
git status --short
```

Expected: `git diff --check` has no output. `git status --short` does not include `backend/uv.lock` staged.

- [ ] **Step 4: Commit any final fixes**

If Step 1 or Step 2 required small fixes, commit them:

```bash
git add backend/app/reasoning/context backend/app/signals backend/app/reasoning/runtime/turn_context.py backend/app/reasoning/langchain_agent/client.py backend/tests
git commit -m "test: verify system memory context"
```

If no fixes were needed, skip the commit.

---

## Self-Review

**Spec coverage:** The plan covers MemoryRouter, AgentContextBuilder, DTOs, signal DTO compatibility, dynamic user hits, Agent integration, fail-soft behavior, and fixture-compatible testing. Long-history synthesis is intentionally downgraded to a warning in Task 5, matching the spec non-goal.

**Completeness scan:** No unresolved markers are left. Every task has concrete files, commands, expected output, and code snippets.

**Type consistency:** `MemoryRouter.classify`, `build_user_snapshot`, `match_user_hits`, and `AgentContextBuilder.build` signatures are consistent across tasks.
