# Catalyst Alert Signal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build P0 future catalyst alert signals that use local fixtures, generate `catalyst` signals, show them in SignalRadar, and inject them into AgentContext.

**Architecture:** Add a separate `catalyst_events` fact table and service layer, then generate compatible rows in the existing `signals` table with `signal_kind='catalyst'`. API and frontend continue to consume the signal surface, with catalyst-specific DTO fields read from formal columns and metadata.

**Tech Stack:** FastAPI, SQLAlchemy async ORM, Alembic, PostgreSQL JSONB, pytest, Vue 3, Vitest.

## Global Constraints

- P0 must work without external API keys.
- Use fixtures as the default data source and keep a provider interface for real calendar sources.
- Use a five-day future window, inclusive of today and day five.
- Do not make trading recommendations.
- Do not model future scheduled events as observations.
- Existing signal API callers must keep working.
- Do not touch unrelated untracked files, including `backend/uv.lock`.

---

## File Structure

- Create `backend/alembic/versions/026_add_catalyst_alert_signals.py`: database migration for `catalyst_events`, `signals.signal_kind`, and `signals.event_date`.
- Modify `backend/app/signals/models.py`: add `CatalystEvent` ORM and new `Signal` fields/indexes.
- Modify `backend/app/signals/schemas.py`: add catalyst list/detail DTO fields.
- Create `backend/app/signals/catalyst.py`: provider candidates, fixture provider, event upsert, scoring, signal generation.
- Modify `backend/app/signals/service.py`: support `signal_kind`, `include_kinds`, `window_days`, and catalyst detail mapping.
- Modify `backend/app/signals/api.py`: expose list filters and a protected fixture backfill endpoint.
- Modify `backend/app/signals/context_provider.py`: format catalyst context as `[未来催化预警]`.
- Modify `frontend/src/components/SignalRadar.vue`: add all/observed/catalyst filter and catalyst card fields.
- Test `backend/tests/signals/test_catalyst.py`: catalyst provider, upsert, scoring, idempotent signal generation.
- Test `backend/tests/signals/test_api.py`: catalyst filters and detail DTO compatibility.
- Test `backend/tests/signals/test_context_provider.py`: catalyst AgentContext formatting.
- Test `frontend/tests/signal_radar.test.js`: filter UI and catalyst card rendering.

---

### Task 1: Database and ORM Model

**Files:**
- Create: `backend/alembic/versions/026_add_catalyst_alert_signals.py`
- Modify: `backend/app/signals/models.py`
- Test: `backend/tests/signals/test_catalyst.py`

**Interfaces:**
- Produces: `CatalystEvent` ORM with fields from the design spec.
- Produces: `Signal.signal_kind: str` and `Signal.event_date: date | None`.

- [ ] **Step 1: Write the failing model test**

Add to `backend/tests/signals/test_catalyst.py`:

```python
from datetime import date

from app.signals.models import CatalystEvent, Signal


def test_catalyst_event_model_fields():
    event = CatalystEvent(
        event_id="CAT:abc",
        event_type="conference",
        title="英伟达 GTC 开发者大会",
        event_date=date(2026, 7, 28),
        source_type="fixture",
        importance=90,
        subjects=["AI算力", "光模块"],
    )

    assert event.event_id == "CAT:abc"
    assert event.event_type == "conference"
    assert event.status == "scheduled"
    assert event.subjects == ["AI算力", "光模块"]


def test_signal_has_catalyst_columns():
    signal = Signal(
        signal_id="SIG:abc",
        source_type="catalyst_event",
        source_id="CAT:abc",
        subject_name="AI算力",
        subject_type="concept",
        signal_type="conference",
        polarity="neutral",
        strength=90,
        confidence=0.75,
        freshness_score=88,
        value_score=86,
        summary="未来催化预警",
        signal_kind="catalyst",
        event_date=date(2026, 7, 28),
    )

    assert signal.signal_kind == "catalyst"
    assert signal.event_date == date(2026, 7, 28)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/signals/test_catalyst.py::test_catalyst_event_model_fields tests/signals/test_catalyst.py::test_signal_has_catalyst_columns -v`

Expected: FAIL because `CatalystEvent`, `signal_kind`, or `event_date` is missing.

- [ ] **Step 3: Implement ORM and migration**

Add the migration with `catalyst_events`, `signal_kind`, `event_date`, and indexes. Add `CatalystEvent` to `backend/app/signals/models.py`, plus `Signal.signal_kind` and `Signal.event_date`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/signals/test_catalyst.py::test_catalyst_event_model_fields tests/signals/test_catalyst.py::test_signal_has_catalyst_columns -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/alembic/versions/026_add_catalyst_alert_signals.py backend/app/signals/models.py backend/tests/signals/test_catalyst.py
git commit -m "feat: add catalyst event model"
```

---

### Task 2: Catalyst Fixture Provider and Signal Generation

**Files:**
- Create: `backend/app/signals/catalyst.py`
- Modify: `backend/tests/signals/test_catalyst.py`

**Interfaces:**
- Consumes: `CatalystEvent`, `Signal`, `SignalPropagation`.
- Produces: `CatalystEventCandidate`.
- Produces: `FixtureCatalystProvider.list_candidates(today: date | None = None) -> list[CatalystEventCandidate]`.
- Produces: `upsert_catalyst_events(session, candidates) -> list[CatalystEvent]`.
- Produces: `generate_catalyst_signals(session, today: date | None = None, window_days: int = 5) -> dict[str, int]`.

- [ ] **Step 1: Write failing service tests**

Add tests for deterministic fixtures, five-day filtering, idempotent event upsert, idempotent signal generation, and portfolio-hit scoring. Use fake sessions where practical and SQLite-free ORM object tests for pure functions.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/signals/test_catalyst.py -v`

Expected: FAIL because `app.signals.catalyst` does not exist.

- [ ] **Step 3: Implement provider, scoring, and generation**

Implement deterministic fixture candidates, stable IDs, lead-day scoring, alert level rules, metadata shape, and upsert logic. The fixture must include at least one event within five days that maps to `AI算力`, `光模块`, and `CPO`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/signals/test_catalyst.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/signals/catalyst.py backend/tests/signals/test_catalyst.py
git commit -m "feat: generate catalyst alert signals"
```

---

### Task 3: API, DTO, and AgentContext

**Files:**
- Modify: `backend/app/signals/schemas.py`
- Modify: `backend/app/signals/service.py`
- Modify: `backend/app/signals/api.py`
- Modify: `backend/app/signals/context_provider.py`
- Modify: `backend/tests/signals/test_api.py`
- Create: `backend/tests/signals/test_context_provider.py`

**Interfaces:**
- Consumes: `generate_catalyst_signals`.
- Produces: list filters `signal_kind`, `include_kinds`, `window_days`.
- Produces: endpoint `POST /signals/backfill/catalysts`.
- Produces: detail fields `signal_kind`, `event_date`, and `catalyst`.

- [ ] **Step 1: Write failing API and context tests**

Add tests that monkeypatch `list_signals` and verify query parameters are passed through. Add a context-provider test where a catalyst detail formats `[未来催化预警]`, `event_date`, `lead_days`, `alert_level`, subjects, holdings, and KG path.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/signals/test_api.py tests/signals/test_context_provider.py -v`

Expected: FAIL because schemas and filters do not yet include catalyst fields.

- [ ] **Step 3: Implement DTO/API/context changes**

Update schema models with optional catalyst fields. Update list filtering in `service.py`. Add `/backfill/catalysts` protected endpoint. Add catalyst formatting branch in `context_provider.py`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/signals/test_api.py tests/signals/test_context_provider.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/signals/schemas.py backend/app/signals/service.py backend/app/signals/api.py backend/app/signals/context_provider.py backend/tests/signals/test_api.py backend/tests/signals/test_context_provider.py
git commit -m "feat: expose catalyst signals"
```

---

### Task 4: SignalRadar Catalyst UI

**Files:**
- Modify: `frontend/src/components/SignalRadar.vue`
- Modify: `frontend/tests/signal_radar.test.js`

**Interfaces:**
- Consumes: `listSignals({ signal_kind, include_kinds, window_days, scope, limit })`.
- Consumes: list item fields `signal_kind`, `event_date`, `lead_days`, `alert_level`, `impact_scope`.

- [ ] **Step 1: Write failing frontend tests**

Add tests that catalyst cards show `未来预警`, lead days, hit names, and that clicking `未来预警` filter calls `listSignals` with `signal_kind: "catalyst"` and `window_days: 5`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npm test -- signal_radar.test.js --runInBand`

Expected: FAIL because the filter and catalyst card rendering do not exist.

- [ ] **Step 3: Implement UI**

Add a compact segmented filter `全部 / 已发生 / 未来预警`. Keep card layout stable. Catalyst cards use `alert_level` for border tone and show `未来预警`, `N天后/今日`, user hits, and first path when present.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npm test -- signal_radar.test.js --runInBand`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/SignalRadar.vue frontend/tests/signal_radar.test.js
git commit -m "feat: show catalyst alerts in radar"
```

---

### Task 5: Final Verification

**Files:**
- No new files unless tests reveal defects.

**Interfaces:**
- Consumes all previous tasks.
- Produces verified P0.

- [ ] **Step 1: Run backend signal tests**

Run: `cd backend && pytest tests/signals -v`

Expected: PASS.

- [ ] **Step 2: Run relevant reasoning context tests**

Run: `cd backend && pytest tests/reasoning/test_agent_context_builder.py tests/reasoning/test_agent_context_schemas.py -v`

Expected: PASS.

- [ ] **Step 3: Run frontend SignalRadar test**

Run: `cd frontend && npm test -- signal_radar.test.js --runInBand`

Expected: PASS.

- [ ] **Step 4: Inspect git status**

Run: `git status --short`

Expected: only intentional committed changes remain; unrelated `backend/uv.lock` may still be untracked.

- [ ] **Step 5: Commit final fixes if any**

```bash
git add <files changed by verification fixes>
git commit -m "test: verify catalyst alert p0"
```

## Self-Review

- Spec coverage: model, fixture source, five-day window, signal generation, API filters, AgentContext, frontend display, and tests are covered.
- Placeholder scan: no task contains TBD, TODO, or unspecified implementation placeholders.
- Type consistency: `signal_kind`, `event_date`, `catalyst`, `lead_days`, `alert_level`, and `impact_scope` names match the design spec.
