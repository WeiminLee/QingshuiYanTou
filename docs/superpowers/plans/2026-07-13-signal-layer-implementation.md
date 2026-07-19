# Signal Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first end-to-end预期差信号 layer: store high-value signals, expose them to the Home sidebar, and let Agent runs receive `signal_id` context.

**Architecture:** Add an independent `backend/app/signals` package backed by PostgreSQL tables. The first slice uses rule-based extraction and lightweight propagation, exposes read/status APIs, injects signal context into `run_lead_agent`, and renders a compact `SignalRadar` in `Home.vue` without replacing the Agent chat canvas.

**Tech Stack:** FastAPI, SQLAlchemy async, Alembic, Pydantic, pytest, Vue 3, TypeScript, Vitest.

## Global Constraints

- Signal layer is independent from memory and does not write trading conclusions.
- Announcement/Evidence and external news signals must share the same `signals` model.
- First implementation may use rules and mockable services; LLM extraction remains an interface boundary.
- Frontend integration belongs in `Home.vue` left sidebar, below “新建账目” and above “最近对话”.
- Right-side Agent chat window remains the primary rendering surface.
- Clicking “问” sends an Agent question with `signal_id`, not just plain copied text.
- Keep implementation TDD: write each failing test, verify red, write minimal code, verify green.

---

## File Structure

- Create `backend/alembic/versions/025_add_signal_tables.py`: create `signals` and `signal_propagations`.
- Create `backend/app/signals/__init__.py`: package exports.
- Create `backend/app/signals/models.py`: SQLAlchemy ORM models.
- Create `backend/app/signals/schemas.py`: API response/request schemas.
- Create `backend/app/signals/extractor.py`: `SourcePayload`, `SignalCandidate`, stable ID and rule extractor.
- Create `backend/app/signals/propagation.py`: lightweight propagation candidates from signal candidates.
- Create `backend/app/signals/service.py`: list/detail/status/context formatting service functions.
- Create `backend/app/signals/context_provider.py`: `fetch_signal_context`.
- Create `backend/app/signals/api.py`: `/api/v1/signals` endpoints.
- Modify `backend/app/main.py`: include signal router as optional-auth read API.
- Modify `backend/app/reasoning/api/agent.py`: add optional `signal_id` request field and pass it through stream/report/chat paths.
- Modify `backend/app/reasoning/langchain_agent/client.py`: accept `signal_id`, fetch signal context in preflight, pass it into prompt.
- Modify `backend/app/reasoning/langchain_agent/prompts/lead_system_prompt.py`: accept and render `signal_context`.
- Create `backend/tests/signals/test_extractor.py`: stable IDs and rule extraction.
- Create `backend/tests/signals/test_context_provider.py`: context formatting for direct signal injection.
- Create `backend/tests/signals/test_api.py`: list/detail/status API against dependency overrides.
- Modify `frontend/src/api/agent.js`: pass `signal_id`.
- Create `frontend/src/api/signals.js`: signal list/detail/status API.
- Modify `frontend/src/composables/useChatSession.ts`: allow `sendMessage(..., { signalId })`.
- Create `frontend/src/components/SignalRadar.vue`: compact left-sidebar signal stream.
- Modify `frontend/src/views/Home.vue`: mount `SignalRadar` and wire `ask-signal`.
- Create `frontend/tests/signal_radar.test.js`: component behavior tests.

---

### Task 1: Backend Signal Domain Core

**Files:**
- Create: `backend/app/signals/__init__.py`
- Create: `backend/app/signals/extractor.py`
- Create: `backend/app/signals/propagation.py`
- Test: `backend/tests/signals/test_extractor.py`

**Interfaces:**
- Produces: `SourcePayload`, `SignalCandidate`, `stable_signal_id(candidate) -> str`, `RuleSignalExtractor.extract(payload) -> list[SignalCandidate]`, `build_lightweight_propagations(candidate) -> list[PropagationCandidate]`.
- Consumes: only Python stdlib.

- [ ] **Step 1: Write failing extractor tests**

```python
# backend/tests/signals/test_extractor.py
from datetime import datetime, UTC

from app.signals.extractor import RuleSignalExtractor, SourcePayload, SignalCandidate, stable_signal_id
from app.signals.propagation import build_lightweight_propagations


def test_stable_signal_id_is_deterministic():
    candidate = SignalCandidate(
        source_type="news",
        source_id="EV:abc",
        source_title="十五五规划强调算力基础设施",
        source_url=None,
        published_at=datetime(2026, 7, 13, tzinfo=UTC),
        subject_name="算力基础设施",
        subject_type="policy",
        signal_type="policy",
        polarity="positive",
        strength=82,
        confidence=0.72,
        summary="十五五规划强调算力基础设施",
        evidence_excerpt="十五五规划强调算力基础设施建设",
        metadata={},
    )

    assert stable_signal_id(candidate) == stable_signal_id(candidate)
    assert stable_signal_id(candidate).startswith("SIG:")


def test_rule_extractor_finds_policy_and_capex_signal():
    payload = SourcePayload(
        source_type="news",
        source_id="EV:policy",
        title="十五五规划强调算力基础设施，大厂资本开支显著增加",
        content="十五五规划强调算力基础设施建设，多家大公司资本开支显著增加。",
        summary="",
        published_at=datetime(2026, 7, 13, tzinfo=UTC),
        url=None,
        metadata={},
    )

    signals = RuleSignalExtractor().extract(payload)

    assert {s.signal_type for s in signals} >= {"policy", "capex"}
    assert all(s.source_id == "EV:policy" for s in signals)
    assert all(s.value_score > 0 for s in signals)


def test_lightweight_propagation_explains_policy_signal():
    candidate = RuleSignalExtractor().extract(SourcePayload(
        source_type="news",
        source_id="EV:policy",
        title="十五五规划强调算力基础设施",
        content="十五五规划强调算力基础设施建设。",
        summary="",
        published_at=datetime(2026, 7, 13, tzinfo=UTC),
        url=None,
        metadata={},
    ))[0]

    propagations = build_lightweight_propagations(candidate)

    assert propagations
    assert "->" in propagations[0].relation_path
    assert propagations[0].reasoning
```

- [ ] **Step 2: Run extractor tests and verify red**

Run: `cd backend && pytest tests/signals/test_extractor.py -q`

Expected: fails with `ModuleNotFoundError: No module named 'app.signals'`.

- [ ] **Step 3: Implement minimal extractor and propagation core**

Create `backend/app/signals/__init__.py`:

```python
"""Signal layer for high-value divergence research signals."""
```

Create `backend/app/signals/extractor.py` with dataclasses and deterministic rule extraction.

Create `backend/app/signals/propagation.py` with `PropagationCandidate` and simple rules:

- `policy` -> `政策主题 -> 产业投入 -> 相关供应链`
- `capex` -> `资本开支增加 -> 订单能见度提升 -> 供应链盈利弹性`
- `mass_production` -> `量产确认 -> 订单兑现概率提升 -> 供应链需求增强`
- `risk` -> `风险事件 -> 短期兑现承压 -> 持仓波动风险`

- [ ] **Step 4: Run extractor tests and verify green**

Run: `cd backend && pytest tests/signals/test_extractor.py -q`

Expected: `3 passed`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/signals backend/tests/signals/test_extractor.py
git commit -m "feat(signals): add signal extraction core"
```

---

### Task 2: Signal Persistence, Schemas, and API

**Files:**
- Create: `backend/alembic/versions/025_add_signal_tables.py`
- Create: `backend/app/signals/models.py`
- Create: `backend/app/signals/schemas.py`
- Create: `backend/app/signals/service.py`
- Create: `backend/app/signals/api.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/signals/test_api.py`

**Interfaces:**
- Consumes: `SignalCandidate`, `PropagationCandidate`.
- Produces: `router`, `SignalListItem`, `SignalDetail`, `list_signals(session, ...)`, `get_signal_detail(session, signal_id)`, `update_signal_status(session, signal_id, status)`.

- [ ] **Step 1: Write failing API tests**

```python
# backend/tests/signals/test_api.py
from datetime import datetime, UTC

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_list_signals_returns_items(monkeypatch):
    async def fake_list_signals(*args, **kwargs):
        return [
            {
                "signal_id": "SIG:abc",
                "title": "800G 光模块规模量产",
                "summary": "量产确认 -> 订单兑现 -> 供应链需求增强",
                "source_type": "announcement",
                "published_at": datetime(2026, 7, 13, tzinfo=UTC),
                "subject_name": "光模块",
                "signal_type": "mass_production",
                "polarity": "positive",
                "value_score": 92,
                "confidence": 0.92,
                "portfolio_hits": ["中际旭创"],
            }
        ], 1

    monkeypatch.setattr("app.signals.api.list_signals", fake_list_signals)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/v1/signals")

    assert res.status_code == 200
    assert res.json()["items"][0]["signal_id"] == "SIG:abc"


@pytest.mark.asyncio
async def test_get_signal_detail_returns_propagations(monkeypatch):
    async def fake_get_signal_detail(*args, **kwargs):
        return {
            "signal_id": "SIG:abc",
            "title": "800G 光模块规模量产",
            "summary": "量产确认 -> 订单兑现 -> 供应链需求增强",
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
            "propagations": [
                {
                    "target_name": "光芯片",
                    "target_type": "concept",
                    "relation_path": "量产确认 -> 订单兑现概率提升 -> 供应链需求增强",
                    "direction": "beneficiary",
                    "impact_horizon": "short",
                    "confidence": 0.7,
                    "reasoning": "高速光模块放量可能提升上游需求",
                }
            ],
        }

    monkeypatch.setattr("app.signals.api.get_signal_detail", fake_get_signal_detail)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/v1/signals/SIG:abc")

    assert res.status_code == 200
    assert res.json()["propagations"][0]["target_name"] == "光芯片"
```

- [ ] **Step 2: Run API tests and verify red**

Run: `cd backend && pytest tests/signals/test_api.py -q`

Expected: fails because `app.signals.api` does not exist or router is not mounted.

- [ ] **Step 3: Implement models, schemas, service stubs, and API router**

Implement real SQLAlchemy model fields matching the spec. API service may use SQLAlchemy when not monkeypatched.

Mount in `backend/app/main.py`:

```python
from app.signals.api import router as signals_router

app.include_router(
    signals_router,
    prefix="/api/v1/signals",
    tags=["信号"],
    dependencies=[Depends(verify_api_key_optional)],
)
```

- [ ] **Step 4: Run API tests and verify green**

Run: `cd backend && pytest tests/signals/test_api.py -q`

Expected: `2 passed`.

- [ ] **Step 5: Commit**

```bash
git add backend/alembic/versions/025_add_signal_tables.py backend/app/signals backend/app/main.py backend/tests/signals/test_api.py
git commit -m "feat(signals): add signal API"
```

---

### Task 3: Agent Signal Context Injection

**Files:**
- Create: `backend/app/signals/context_provider.py`
- Modify: `backend/app/reasoning/api/agent.py`
- Modify: `backend/app/reasoning/langchain_agent/client.py`
- Modify: `backend/app/reasoning/langchain_agent/prompts/lead_system_prompt.py`
- Test: `backend/tests/signals/test_context_provider.py`

**Interfaces:**
- Consumes: `get_signal_detail(session, signal_id)`.
- Produces: `fetch_signal_context(signal_id=None, question="", user_id=None) -> str`.
- Extends: Agent request models with `signal_id: str | None`.

- [ ] **Step 1: Write failing context tests**

```python
# backend/tests/signals/test_context_provider.py
import pytest

from app.signals.context_provider import format_signal_context


def test_format_signal_context_includes_source_anchor_and_propagation():
    context = format_signal_context({
        "signal_id": "SIG:abc",
        "title": "800G 光模块规模量产",
        "source_type": "announcement",
        "value_score": 92,
        "confidence": 0.92,
        "evidence_excerpt": "相关产品已进入规模量产阶段",
        "portfolio_hits": ["中际旭创", "新易盛"],
        "propagations": [
            {
                "relation_path": "量产确认 -> 订单兑现概率提升 -> 供应链需求增强",
                "reasoning": "高速光模块放量可能提升上游需求",
            }
        ],
    })

    assert "<signal-context>" in context
    assert "800G 光模块规模量产" in context
    assert "相关产品已进入规模量产阶段" in context
    assert "中际旭创、新易盛" in context
    assert "量产确认 -> 订单兑现概率提升" in context
```

- [ ] **Step 2: Run context test and verify red**

Run: `cd backend && pytest tests/signals/test_context_provider.py -q`

Expected: fails because `app.signals.context_provider` does not exist.

- [ ] **Step 3: Implement context provider and Agent pass-through**

Add:

```python
def format_signal_context(detail: dict | None) -> str:
    if not detail:
        return ""
    # returns <signal-context>...</signal-context>
```

Extend request models:

```python
signal_id: str | None = None
```

Pass `signal_id` through `_run_stream_report`, `stream_report`, `chat`, `report`, and `run_lead_agent`.

Add `signal_context` argument to `apply_prompt_template` and render it as a separate `<signal_context>` section.

- [ ] **Step 4: Run context test and targeted reasoning tests**

Run:

```bash
cd backend
pytest tests/signals/test_context_provider.py tests/reasoning/test_prompt_template.py -q
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/signals/context_provider.py backend/app/reasoning/api/agent.py backend/app/reasoning/langchain_agent/client.py backend/app/reasoning/langchain_agent/prompts/lead_system_prompt.py backend/tests/signals/test_context_provider.py
git commit -m "feat(signals): inject signal context into agent"
```

---

### Task 4: Frontend Signal API and Chat Pass-Through

**Files:**
- Create: `frontend/src/api/signals.js`
- Modify: `frontend/src/api/agent.js`
- Modify: `frontend/src/composables/useChatSession.ts`

**Interfaces:**
- Produces: `listSignals(params)`, `getSignalDetail(signalId)`, `updateSignalStatus(signalId, status)`.
- Extends: `sendMessage(question, scheduleAutoCollapse, options?: { signalId?: string })`.

- [ ] **Step 1: Write failing frontend API/session tests**

Create a focused Vitest test that mocks `streamReport` and verifies `sendMessage` forwards `signal_id`.

- [ ] **Step 2: Run frontend test and verify red**

Run: `cd frontend && npm test -- --run tests/use_chat_session_signal.test.js`

Expected: fails because `sendMessage` does not accept or forward `signalId`.

- [ ] **Step 3: Implement API wrappers and pass-through**

`streamReport` should include:

```js
signal_id: params.signal_id || undefined,
```

`sendMessage` should accept:

```ts
options?: { signalId?: string }
```

and call:

```ts
await streamReport({
  question: question.trim(),
  thread_id: threadId.value,
  max_turns: 4,
  signal_id: options?.signalId,
});
```

- [ ] **Step 4: Run frontend test and verify green**

Run: `cd frontend && npm test -- --run tests/use_chat_session_signal.test.js`

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/signals.js frontend/src/api/agent.js frontend/src/composables/useChatSession.ts frontend/tests/use_chat_session_signal.test.js
git commit -m "feat(frontend): pass signal context to agent"
```

---

### Task 5: Home Sidebar SignalRadar

**Files:**
- Create: `frontend/src/components/SignalRadar.vue`
- Modify: `frontend/src/views/Home.vue`
- Test: `frontend/tests/signal_radar.test.js`

**Interfaces:**
- Consumes: `listSignals`, `getSignalDetail`, `updateSignalStatus`.
- Emits: `ask-signal` with `{ signalId, question }`.

- [ ] **Step 1: Write failing SignalRadar component tests**

Test requirements:

- Renders list item title and score.
- Emits `ask-signal` when “问” is clicked.
- Shows detail after card click.
- Pauses auto scroll on mouseenter and resumes on mouseleave through a visible state class.

- [ ] **Step 2: Run component test and verify red**

Run: `cd frontend && npm test -- --run tests/signal_radar.test.js`

Expected: fails because `SignalRadar.vue` does not exist.

- [ ] **Step 3: Implement SignalRadar and mount it in Home**

In `Home.vue`, insert:

```vue
<SignalRadar @ask-signal="handleAskSignal" />
```

below the new chat button.

Add:

```ts
function handleAskSignal(payload: { signalId: string; question: string }) {
  handleSend(payload.question, { signalId: payload.signalId });
}
```

If the existing `handleSend` signature only accepts text, update it to:

```ts
async function handleSend(text: string, options?: { signalId?: string }) {
  lastQuestion.value = text;
  reportContent.value = "";
  reportJson.value = null;
  lastTaskId.value = "";
  inputText.value = "";
  await sendMessage(text, scheduleAutoCollapse, options);
}
```

- [ ] **Step 4: Run component and smoke tests**

Run:

```bash
cd frontend
npm test -- --run tests/signal_radar.test.js
npm run build
```

Expected: tests pass and build exits 0.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/SignalRadar.vue frontend/src/views/Home.vue frontend/tests/signal_radar.test.js
git commit -m "feat(frontend): add signal radar to home sidebar"
```

---

### Task 6: End-to-End Verification

**Files:**
- Modify only if verification reveals integration defects.

**Interfaces:**
- Consumes all prior tasks.
- Produces verified first slice.

- [ ] **Step 1: Run backend signal and reasoning tests**

Run:

```bash
cd backend
pytest tests/signals tests/reasoning/test_prompt_template.py tests/reasoning/test_sse_event_filter.py -q
```

Expected: all selected tests pass.

- [ ] **Step 2: Run frontend tests and build**

Run:

```bash
cd frontend
npm test -- --run tests/signal_radar.test.js tests/use_chat_session_signal.test.js
npm run build
```

Expected: tests pass and build exits 0.

- [ ] **Step 3: Inspect git diff for scope**

Run: `git diff --stat HEAD`

Expected: only signal-layer backend/frontend files and planned Agent pass-through files changed.

- [ ] **Step 4: Commit final integration fixes if any**

If Step 1 or Step 2 required fixes:

```bash
git add <changed-files>
git commit -m "fix(signals): complete signal layer integration"
```

If no fixes were required, do not create an empty commit.

---

## Self-Review

Spec coverage:

- Independent signal module: Tasks 1-2.
- Unified news and announcement/Evidence model: Tasks 1-2 model `source_type` and `source_id`; first implementation wires events first and leaves Evidence-ready inputs.
- Lightweight propagation: Task 1.
- Agent context injection: Task 3.
- Frontend Home left-sidebar SignalRadar: Task 5.
- “Ask Agent” with `signal_id`: Tasks 3-5.
- Not a trading conclusion layer: enforced in prompt/context text and data model naming.

Placeholder scan:

- No placeholder markers or unnamed files are used in executable tasks.

Type consistency:

- Frontend uses `signalId` in component/composable and sends `signal_id` to API.
- Backend request model uses `signal_id`, matching API payload.
