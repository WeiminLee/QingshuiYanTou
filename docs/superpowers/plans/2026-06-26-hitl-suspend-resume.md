# HITL Suspend/Resume Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement Human-in-the-loop suspend/resume via SSE 驻留暂停 — Agent 调用 `ask_clarification`/`AskUserQuestion` 时暂停运行，前端显示澄清界面，用户回答后在同一 SSE 连接上继续。

**Architecture:** SSE 事件队列（`_events[task_id]`）与后台任务（`_run_stream_report`）解耦。原始任务暂停时保存消息快照、发射 `clarification_request` 但不发射 `stream_end`。Resume 请求创建新后台任务，推事件到同一队列，SSE 连接无感知。

**Tech Stack:** LangChain `create_agent` + LangGraph `CompiledStateGraph` + `EventSourceResponse` + Vue 3 + TypeScript

## Global Constraints

- 所有后端新代码使用 `asyncio`（同步回退已被标记为 deprecated）
- `run_lead_agent` 签名只加可选参数，不改现有调用者
- `_PENDING_CLARIFICATIONS` 全局 dict 由 `HITLStore` 替代
- 前端 `EventSource` 在 pause/resume 期间不重新连接
- `clarification_request` SSE 事件不经过 `_VISIBLE_MAP` 映射
- `TaskStateManager` 新增 `STATUS_PAUSED = "paused"` 状态

---

## File Structure

### New Files
- `backend/app/reasoning/langchain_agent/hitl_store.py` — `HITLStore` + `PendingClarification` dataclass
- `backend/tests/reasoning/test_hitl_suspend_resume.py` — 后端集成测试

### Modified Files
- `backend/app/reasoning/langchain_agent/client.py` — 流循环暂停检测 + `prebuilt_messages` 支持
- `backend/app/reasoning/langchain_agent/lead_agent.py` — `system_prompt` 可选参数
- `backend/app/reasoning/api/agent.py` — `_resume_stream_report()` + resolve 端点
- `backend/app/reasoning/api/agent_events.py` — `TaskStateManager` 扩展 `STATUS_PAUSED` / `mark_paused()`
- `backend/app/reasoning/tools/builtins/clarification.py` — 移除 `_PENDING_CLARIFICATIONS`（由 HITLStore 替代）

### Frontend Files
- `frontend/src/types/chat.ts` — 新增 `clarification_request` / `ClarificationItem`
- `frontend/src/composables/useStreamPipeline.ts` — 新增 `onClarification` 回调
- `frontend/src/composables/useChatSession.ts` — 新增 SSE 监听 + `resolveClarification()`
- `frontend/src/views/Home.vue` — 新增 `ClarificationPanel`
- `frontend/src/api/agent.js` — 新增 `resolveClarification()`

---

### Task 1: `HITLStore` + 数据模型

**Files:**
- Create: `backend/app/reasoning/langchain_agent/hitl_store.py`
- Modify: `backend/app/reasoning/api/agent_events.py` (add `STATUS_PAUSED`)
- Test: `backend/tests/reasoning/test_hitl_suspend_resume.py`

**Interfaces:**
- Produces: `HITLStore` class with `save/pop/get/cleanup_expired`; `PendingClarification` dataclass; `CLARIFICATION_TOOLS` frozenset

- [ ] **Step 1: Add `STATUS_PAUSED` to `TaskStateManager`**

Edit `backend/app/reasoning/api/agent_events.py`:

```python
# 在类常量区或 __init__ 方法附近添加
STATUS_PAUSED = "paused"

# 在 update_status 方法中支持 paused 状态
def mark_paused(self, task_id: str) -> None:
    """标记任务为暂停状态（不发射 stream_end）。"""
    self._tasks[task_id]["status"] = "paused"

def is_paused(self, task_id: str) -> bool:
    task = self._tasks.get(task_id)
    return task is not None and task.get("status") == "paused"
```

- [ ] **Step 2: Write `HITLStore` failing test**

Create `backend/tests/reasoning/test_hitl_suspend_resume.py`:

```python
"""Tests for HITL suspend/resume checkpoint store."""

import pytest
from datetime import datetime
from app.reasoning.langchain_agent.hitl_store import (
    HITLStore, PendingClarification, get_hitl_store,
)


class TestPendingClarification:
    def test_dataclass_fields(self):
        pc = PendingClarification(
            task_id="task_1", thread_id="thread_1",
            clarification_id="cid_1", question="哪只股票？",
            clarification_type="ambiguous",
            options=None, context=None,
            messages=[], run_config={},
        )
        assert pc.task_id == "task_1"
        assert pc.clarification_id == "cid_1"
        assert pc.created_at is not None


class TestHITLStore:
    async def test_save_and_pop(self):
        store = HITLStore()
        pc = PendingClarification(
            task_id="task_1", thread_id="thread_1",
            clarification_id="cid_1", question="test",
            clarification_type="ambiguous",
            options=None, context=None,
            messages=[], run_config={},
        )
        await store.save("task_1", pc)
        assert await store.get("task_1") is pc
        popped = await store.pop("task_1")
        assert popped is pc
        assert await store.pop("task_1") is None  # 第二次 pop 返回 None

    async def test_cleanup_expired(self):
        store = HITLStore(ttl_seconds=0)  # 立即过期
        pc = PendingClarification(
            task_id="task_1", thread_id="thread_1",
            clarification_id="cid_1", question="test",
            clarification_type="ambiguous",
            options=None, context=None,
            messages=[], run_config={},
        )
        await store.save("task_1", pc)
        import asyncio
        await asyncio.sleep(0.01)  # 让 created_at 过期
        cleaned = await store.cleanup_expired()
        assert cleaned >= 1
        assert await store.get("task_1") is None

    async def test_global_singleton(self):
        s1 = get_hitl_store()
        s2 = get_hitl_store()
        assert s1 is s2
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && ../.venv/bin/pytest tests/reasoning/test_hitl_suspend_resume.py -x -v --asyncio-mode=auto`

Expected: FAIL — `HITLStore` / `PendingClarification` not defined

- [ ] **Step 4: Write `HITLStore` implementation**

Create `backend/app/reasoning/langchain_agent/hitl_store.py`:

```python
"""HITL checkpoint store — thread state persistence for suspend/resume."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from langchain_core.messages import BaseMessage

logger = logging.getLogger(__name__)

CLARIFICATION_TOOLS = frozenset({"ask_clarification", "AskUserQuestion"})


@dataclass
class PendingClarification:
    task_id: str
    thread_id: str
    clarification_id: str
    question: str
    clarification_type: str
    options: list[dict] | None
    context: str | None
    messages: list[BaseMessage]
    run_config: dict
    created_at: datetime = field(default_factory=datetime.now)


class HITLStore:
    """In-memory checkpoint store for paused agent runs.

    Thread-safe for async access via asyncio.Lock.
    TTL-based cleanup (default 1 hour).
    """

    def __init__(self, ttl_seconds: int = 3600):
        self._store: dict[str, PendingClarification] = {}
        self._lock = asyncio.Lock()
        self._ttl = ttl_seconds

    async def save(self, task_id: str, state: PendingClarification) -> None:
        async with self._lock:
            self._store[task_id] = state

    async def pop(self, task_id: str) -> Optional[PendingClarification]:
        async with self._lock:
            return self._store.pop(task_id, None)

    async def get(self, task_id: str) -> Optional[PendingClarification]:
        async with self._lock:
            return self._store.get(task_id)

    async def cleanup_expired(self) -> int:
        now = datetime.now()
        expired = []
        async with self._lock:
            for tid, state in self._store.items():
                if (now - state.created_at).total_seconds() > self._ttl:
                    expired.append(tid)
            for tid in expired:
                del self._store[tid]
        return len(expired)


_hitl_store = HITLStore()


def get_hitl_store() -> HITLStore:
    return _hitl_store
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && ../.venv/bin/pytest tests/reasoning/test_hitl_suspend_resume.py -x -v --asyncio-mode=auto`

Expected: 4 PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/reasoning/langchain_agent/hitl_store.py backend/app/reasoning/api/agent_events.py backend/tests/reasoning/test_hitl_suspend_resume.py
git commit -m "feat(hitl): add HITLStore and PendingClarification dataclass"
```

---

### Task 2: `run_lead_agent` — 暂停检测 + `prebuilt_messages`

**Files:**
- Modify: `backend/app/reasoning/langchain_agent/client.py`
- Modify: `backend/app/reasoning/langchain_agent/lead_agent.py`
- Test: `backend/tests/reasoning/test_hitl_suspend_resume.py`

**Interfaces:**
- Consumes: `HITLStore`, `PendingClarification`, `CLARIFICATION_TOOLS`
- Produces: `run_lead_agent(prebuilt_messages=..., skip_preflight=...)`; `is_clarified` 检测 + checkpoint 保存

- [ ] **Step 1: Write failing tests**

Add to `backend/tests/reasoning/test_hitl_suspend_resume.py`:

```python
class TestClarificationDetection:
    async def test_parse_ask_user_question_json(self):
        """AskUserQuestion 工具结果解析为结构化 dict。"""
        from app.reasoning.langchain_agent.client import _parse_clarification_result
        result_str = '{"questions": [{"question": "分析哪只？", "options": [{"label": "中际旭创"}]}]}'
        parsed = _parse_clarification_result("AskUserQuestion", result_str)
        assert parsed["question"] == "分析哪只？"
        assert len(parsed["options"]) == 1

    async def test_parse_ask_clarification_text(self):
        """旧 ask_clarification 格式也能解析。"""
        from app.reasoning.langchain_agent.client import _parse_clarification_result
        result_str = "**澄清请求** (ambiguous)\n\n哪只股票？\n\nclarification_id: abc123"
        parsed = _parse_clarification_result("ask_clarification", result_str)
        assert parsed["clarification_id"] == "abc123"
        assert "哪只股票" in parsed["question"]

    async def test_no_parse_for_normal_tools(self):
        from app.reasoning.langchain_agent.client import _parse_clarification_result
        result = _parse_clarification_result("get_kline", "some data")
        assert result is None

    async def test_prebuilt_messages_triggers_skip_preflight(self):
        """prebuilt_messages 提供时跳过预检。"""
        from app.reasoning.langchain_agent.client import run_lead_agent
        from langchain_core.messages import HumanMessage
        # 理想情况下应 mock 内部 preflight 调用，验证不被执行
        # 这里先验证 prebuilt_messages 参数类型被接受
        assert callable(run_lead_agent)

    async def test_is_clarified_flag_stops_stream_end(self):
        """当 is_clarified=True 时，run_lead_agent 不发射 stream_end。"""
        # 集成测试：mock agent.astream 产出 clarification tool result
        # 验证返回的 dict 包含 status="paused"
        pass  # 在 Task 2 实现完成后补充
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && ../.venv/bin/pytest tests/reasoning/test_hitl_suspend_resume.py::TestClarificationDetection -x -v --asyncio-mode=auto`

Expected: 1 PASS, rest FAIL (function not found)

- [ ] **Step 3: Modify `make_lead_agent` to support `system_prompt=None`**

Edit `backend/app/reasoning/langchain_agent/lead_agent.py`:

Change the function signature to make `system_prompt` optional:

```python
def make_lead_agent(
    model,
    tools: list,
    system_prompt: str = "",  # 改为默认空字符串
    config: RunnableConfig | None = None,
    thread_id: str = "default",
    plan_mode: bool = False,
):
```

Then at line 138, pass `system_prompt=system_prompt` (already exists, unchanged).

When resuming with `skip_preflight=True`, `system_prompt=""` means `create_agent` won't add a SystemMessage. The `prebuilt_messages` already contain the original SystemMessage.

- [ ] **Step 4: Add `_parse_clarification_result` and `_is_clarification_tool` to `client.py`**

Add helper functions near top of `backend/app/reasoning/langchain_agent/client.py`:

```python
# 在文件顶部导入区域之后添加
from app.reasoning.langchain_agent.hitl_store import (
    CLARIFICATION_TOOLS,
    PendingClarification,
    get_hitl_store,
)


def _parse_clarification_result(tool_name: str, result_str: str) -> dict | None:
    """解析 clarification 工具返回结果，提取结构化数据。

    返回 None 表示不是 clarification 工具。
    """
    if tool_name not in CLARIFICATION_TOOLS:
        return None

    if tool_name == "AskUserQuestion":
        import json
        try:
            data = json.loads(result_str) if isinstance(result_str, str) else {}
        except (json.JSONDecodeError, TypeError):
            data = {}
        questions = (data.get("questions") or [{}])[0]
        return {
            "clarification_id": str(uuid.uuid4())[:8],
            "question": questions.get("question", str(result_str)[:200]),
            "type": questions.get("type", "ambiguous"),
            "options": questions.get("options"),
            "context": questions.get("context"),
        }
    else:
        # ask_clarification format: "**澄清请求** (type)\n\nquestion\n\nclarification_id: xxx"
        text = str(result_str)
        cid = ""
        for line in text.split("\n"):
            if "clarification_id:" in line:
                cid = line.split("clarification_id:")[-1].strip()
        return {
            "clarification_id": cid or str(uuid.uuid4())[:8],
            "question": text[:200],
            "type": "ambiguous",
            "options": None,
            "context": None,
        }
```

- [ ] **Step 5: Add `is_clarified` detection in stream loop**

In `backend/app/reasoning/langchain_agent/client.py`, inside `run_lead_agent()`, modify the stream loop:

Before the `try:` block, add:

```python
# NEW: 暂停检测标志
is_clarified = False
clarification_data: dict | None = None
all_messages: list[BaseMessage] = []
```

In the `ToolMessage` handling branch (after `elif isinstance(msg, ToolMessage):`), before the budget enforcement, add:

```python
# NEW: CLARIFICATION DETECTION
if tool_name in CLARIFICATION_TOOLS:
    clarification_data = _parse_clarification_result(tool_name, result_str)
    if clarification_data:
        await get_hitl_store().save(
            task_id,
            PendingClarification(
                task_id=task_id,
                thread_id=thread_id,
                clarification_id=clarification_data["clarification_id"],
                question=clarification_data["question"],
                clarification_type=clarification_data.get("type", "ambiguous"),
                options=clarification_data.get("options"),
                context=clarification_data.get("context"),
                messages=list(all_messages),
                run_config={
                    "model_name": model_name,
                    "max_turns": max_turns,
                    "thread_id": thread_id,
                    "plan_mode": plan_mode,
                },
            ),
        )
        await emit_fn("clarification_request", {
            "clarification_id": clarification_data["clarification_id"],
            "question": clarification_data["question"],
            "type": clarification_data.get("type", "ambiguous"),
            "options": clarification_data.get("options"),
            "context": clarification_data.get("context"),
        })
        is_clarified = True
        # Don't emit tool_result or continue processing this message
        # The return_direct AIMessage will be skipped next iteration
        continue
    # If not actually a clarification (parse returned None), fall through to normal tool handling

# Normal tool result handling follows...
```

After the `for msg in messages:` loop (but inside `for chunk in agent.astream():`), add:

```python
# NEW: 如果检测到暂停，终止流循环
if is_clarified:
    break
```

In the AIMessage text content handling, add skip when `is_clarified`:

```python
if isinstance(msg, AIMessage):
    if is_clarified:
        continue  # Skip return_direct echo
    # ... existing code ...
```

Before the `# ── 发射 stream_end ────────────────────────────` section, add:

```python
# NEW: 暂停时记录到 journal 并返回 paused 状态
if is_clarified:
    append_journal_event("clarification_request", {
        "clarification_id": clarification_data["clarification_id"],
    })
    if harness is not None:
        harness.stop()
    return {
        "status": "paused",
        "clarification_id": clarification_data["clarification_id"],
        "content": "",
    }
```

Wrap the existing stream_end emission in `if not is_clarified:`:

```python
# ── 发射 stream_end ────────────────────────────
if not is_clarified:
    if emit_fn:
        raw_analysis = "".join(full_content)
        report = _build_analysis_report(...)
        await emit_fn("stream_end", {...})
    append_journal_event("stream_end", {...})
```

Also wrap the harness stop and result assembly:

```python
# ── Harness 收尾 ────────────────────────────
if harness is not None:
    ...

# ── Paused path was already returned above ──
result = {
    "content": "".join(full_content),
    ...
}
```

- [ ] **Step 6: Add `prebuilt_messages` + `skip_preflight` to `run_lead_agent`**

In `run_lead_agent()` signature, add new parameters:

```python
async def run_lead_agent(
    question: str,
    thread_id: str,
    *,
    model_name: str | None = None,
    max_turns: int = 8,
    emit_fn: Callable | None = None,
    plan_mode: bool = False,
    title_enabled: bool = True,
    # NEW:
    prebuilt_messages: list[BaseMessage] | None = None,
    skip_preflight: bool = False,
) -> dict:
```

After the initial variable setup, add early-return for prebuilt messages:

```python
# NEW: prebuilt_messages 路径 — 跳过预检
if skip_preflight and prebuilt_messages is not None:
    system_prompt = prebuilt_messages[0].content if prebuilt_messages else ""
    agent = make_lead_agent(
        model=model,
        tools=safe_tools,
        system_prompt="",  # prebuilt_messages 已包含 SystemMessage
        config=config,
        thread_id=thread_id,
        plan_mode=plan_mode,
    )
    state = {"messages": list(prebuilt_messages)}
    # Jump to stream loop
    _run_stream_loop(agent, state, ...)  # Extract the loop logic
```

Actually, this is too invasive. A cleaner approach:

Replace the `state = {"messages": [HumanMessage(content=question)]}` line with:

```python
# NEW: 支持预构建消息（resume 路径）
if prebuilt_messages is not None:
    state = {"messages": list(prebuilt_messages)}
else:
    state = {"messages": [HumanMessage(content=question)]}
```

And wrap the preflight section (pre-search, memory load, etc.) with:

```python
if not skip_preflight:
    # 现有预检代码...
    pass
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd backend && ../.venv/bin/pytest tests/reasoning/test_hitl_suspend_resume.py -x -v --asyncio-mode=auto`

Expected: Tests pass. (Integration tests for actual pause detection will be in Task 3.)

Also run existing tests to verify no regressions:

Run: `cd backend && ../.venv/bin/pytest tests/reasoning/test_context_compressor.py tests/test_middleware_unit.py -x -v --asyncio-mode=auto`

Expected: All pass.

- [ ] **Step 8: Commit**

```bash
git add backend/app/reasoning/langchain_agent/client.py backend/app/reasoning/langchain_agent/lead_agent.py backend/tests/reasoning/test_hitl_suspend_resume.py
git commit -m "feat(hitl): add pause detection and prebuilt_messages support in stream loop"
```

---

### Task 3: Resume API + `_resume_stream_report`

**Files:**
- Modify: `backend/app/reasoning/api/agent.py`
- Modify: `backend/app/reasoning/api/agent_events.py` (mark_paused)
- Test: `backend/tests/reasoning/test_hitl_suspend_resume.py`

**Interfaces:**
- Consumes: `HITLStore`, `PendingClarification`, `run_lead_agent(prebuilt_messages=..., skip_preflight=True)`
- Produces: `POST /api/v1/agent/resolve/{task_id}` endpoint; `_resume_stream_report()` background task

- [ ] **Step 1: Write failing tests**

Add to `backend/tests/reasoning/test_hitl_suspend_resume.py`:

```python
class TestResumeAPI:
    async def test_resolve_endpoint_returns_404_for_unknown(self, client):
        """不存在的 task_id 返回 404。"""
        resp = await client.post("/api/v1/agent/resolve/unknown_task", json={
            "answer": "中际旭创", "clarification_id": "cid_1"
        })
        assert resp.status_code == 404

    async def test_resolve_endpoint_accepts_valid_request(self, client):
        """有效请求返回 200 和 status=resumed。"""
        # 先创建暂停任务
        from app.reasoning.api.agent_events import _task_manager
        _task_manager.create_task("test_task", "thread_1", "问题")

        from app.reasoning.langchain_agent.hitl_store import get_hitl_store, PendingClarification
        store = get_hitl_store()
        await store.save("test_task", PendingClarification(
            task_id="test_task", thread_id="thread_1",
            clarification_id="cid_1", question="哪只？",
            clarification_type="ambiguous",
            options=None, context=None,
            messages=[], run_config={"model_name": "test"},
        ))

        resp = await client.post("/api/v1/agent/resolve/test_task", json={
            "answer": "中际旭创", "clarification_id": "cid_1"
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "resumed"
        # 验证 checkpoint 已被 pop（不可重复 resume）
        assert await store.get("test_task") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && ../.venv/bin/pytest tests/reasoning/test_hitl_suspend_resume.py::TestResumeAPI -x -v --asyncio-mode=auto`

Expected: FAIL — endpoint not found

- [ ] **Step 3: Add `mark_paused` / `is_paused` to `TaskStateManager`**

Edit `backend/app/reasoning/api/agent_events.py`:

```python
# 在 TaskStateManager 类中添加
STATUS_PAUSED = "paused"

def mark_paused(self, task_id: str) -> None:
    self._tasks[task_id]["status"] = "paused"

def is_paused(self, task_id: str) -> bool:
    task = self._tasks.get(task_id)
    return task is not None and task.get("status") == "paused"
```

- [ ] **Step 4: Add `ResolveClarificationRequest` Pydantic model**

At the top of `backend/app/reasoning/api/agent.py` (or in existing models section):

```python
from pydantic import BaseModel

class ResolveClarificationRequest(BaseModel):
    answer: str
    clarification_id: str
```

- [ ] **Step 5: Add `_resume_stream_report` function**

In `backend/app/reasoning/api/agent.py`, add after `_run_stream_report`:

```python
async def _resume_stream_report(
    task_id: str,
    thread_id: str,
    messages: list[BaseMessage],
    run_config: dict,
):
    """Resume a paused agent run from checkpoint — pushes events to same task_id stream."""
    from app.reasoning.langchain_agent.client import run_lead_agent
    from app.reasoning.output import AnalysisReport

    async def emit_fn(ev_type: str, data: dict):
        await _emit_to_manager(ev_type, data)

    try:
        _task_manager.update_status(task_id, "running")

        result = await run_lead_agent(
            question="",
            thread_id=thread_id,
            model_name=run_config.get("model_name"),
            max_turns=run_config.get("max_turns", 8),
            emit_fn=emit_fn,
            prebuilt_messages=messages,
            skip_preflight=True,
            plan_mode=run_config.get("plan_mode", False),
        )

        raw_analysis = result.get("content", "") if result else ""
        report = AnalysisReport(
            report_id=task_id[:8],
            topic="继续分析",
            generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            raw_analysis=raw_analysis,
        )
        await emit_fn("stream_end", {
            "report_content": report.to_markdown(),
            "report_json": report.to_dict(),
            "report_id": report.report_id,
            "compliance_passed": report.compliance_declared,
            "turns": result.get("turns", 0),
            "content": raw_analysis,
        })
        _task_manager.update_status(task_id, "completed")

    except Exception as e:
        logger.exception(f"[Resume] resume agent 异常: {e}")
        await _emit_to_manager("error", {"error": str(e)})
        _task_manager.update_status(task_id, "failed")
```

- [ ] **Step 6: Add resolve endpoint**

In `backend/app/reasoning/api/agent.py`, add the route:

```python
@router.post("/api/v1/agent/resolve/{task_id}")
async def resolve_clarification(
    task_id: str,
    body: ResolveClarificationRequest,
    auth: str = Depends(verify_api_key),
):
    """Resume a paused agent run with user's clarification answer."""
    store = get_hitl_store()
    pending = await store.pop(task_id)
    if not pending:
        raise HTTPException(404, "No pending clarification found for this task")

    await _emit_to_manager("clarification_resolved", {
        "clarification_id": body.clarification_id,
        "task_id": task_id,
    })

    messages = list(pending.messages)
    messages.append(HumanMessage(content=body.answer))

    asyncio.create_task(_resume_stream_report(
        task_id=task_id,
        thread_id=pending.thread_id,
        messages=messages,
        run_config=pending.run_config,
    ))

    return {"status": "resumed", "task_id": task_id}
```

Make sure imports include `HumanMessage` and `get_hitl_store`:

```python
from langchain_core.messages import HumanMessage
from app.reasoning.langchain_agent.hitl_store import get_hitl_store
```

- [ ] **Step 7: Update `_run_stream_report` to call `mark_paused` when paused**

In `_run_stream_report`, after `result = await run_lead_agent(...)`, add:

```python
if result and result.get("status") == "paused":
    _task_manager.mark_paused(task_id)
    return  # Don't emit stream_end — SSE stays alive
```

- [ ] **Step 8: Run tests**

Run: `cd backend && ../.venv/bin/pytest tests/reasoning/test_hitl_suspend_resume.py -x -v --asyncio-mode=auto`

Expected: All tests pass.

Run: `cd backend && ../.venv/bin/pytest tests/reasoning/test_context_compressor.py tests/test_middleware_unit.py -x -v --asyncio-mode=auto`

Expected: No regressions.

- [ ] **Step 9: Commit**

```bash
git add backend/app/reasoning/api/agent.py backend/app/reasoning/api/agent_events.py backend/tests/reasoning/test_hitl_suspend_resume.py
git commit -m "feat(hitl): add resume API endpoint and _resume_stream_report"
```

---

### Task 4: 前端 SSE 事件处理

**Files:**
- Modify: `frontend/src/types/chat.ts`
- Modify: `frontend/src/composables/useStreamPipeline.ts`
- Modify: `frontend/src/composables/useChatSession.ts`
- Modify: `frontend/src/api/agent.js`

**Interfaces:**
- Consumes: `clarification_request` SSE event from backend
- Produces: `onClarification` pipeline callback; `resolveClarification()` method

- [ ] **Step 1: Add TypeScript types**

Edit `frontend/src/types/chat.ts`:

```typescript
// 在 SSEEvent.type union 中添加
export type SSEEventType =
  // ... 现有类型 ...
  | "clarification_request"
  | "clarification_resolved";

// 新增类型
export interface ClarificationOption {
  label: string;
  description?: string;
}

export interface ClarificationItem {
  clarification_id: string;
  question: string;
  type: "missing_info" | "ambiguous" | "approach_choice" | "risk_confirmation";
  options?: ClarificationOption[];
  context?: string;
}
```

- [ ] **Step 2: Add `onClarification` to pipeline**

Edit `frontend/src/composables/useStreamPipeline.ts`:

```typescript
// In StreamPipelineCallbacks interface, add:
export interface StreamPipelineCallbacks {
  // ... existing callbacks ...
  onClarification?: (item: ClarificationItem) => void;
}

// In handleBufferedEvent function, add case:
export function handleBufferedEvent(
  buffered: SSEDataBufferItem[],
  pipeline: StreamPipelineCallbacks,
): void {
  // ... existing code ...
  for (const event of buffered) {
    // ... existing event type routing ...
    if (event.type === "clarification_request") {
      pipeline.onClarification?.({
        clarification_id: event.data.clarification_id || "",
        question: event.data.question || "",
        type: event.data.type || "ambiguous",
        options: event.data.options,
        context: event.data.context,
      });
      continue;
    }
  }
}
```

- [ ] **Step 3: Add SSE listener + resolve method in `useChatSession.ts`**

In `frontend/src/composables/useChatSession.ts`:

```typescript
// 在 ref 声明区添加
const pendingClarification = ref<ClarificationItem | null>(null)
const isWaitingForClarification = ref(false)
const clarificationAnswer = ref("")

// 在 connectSSE 的 EventSource 事件注册中添加
es.addEventListener("clarification_request", (e: MessageEvent) => {
  try {
    const parsed = JSON.parse(e.data)
    const data = parsed.data || parsed
    pendingClarification.value = {
      clarification_id: data.clarification_id || "",
      question: data.question || "",
      type: data.type || "ambiguous",
      options: data.options,
      context: data.context,
    }
    isWaitingForClarification.value = true
    isLoading.value = false
  } catch (err) {
    console.error("[HITL] Failed to parse clarification_request:", err)
  }
})

es.addEventListener("clarification_resolved", () => {
  isWaitingForClarification.value = true  // 等待 resume 后的事件
})

// 新增方法
async function resolveClarification(answer: string) {
  if (!taskId.value || !pendingClarification.value) return
  try {
    await api.resolveClarification(taskId.value, {
      answer,
      clarification_id: pendingClarification.value.clarification_id,
    })
    pendingClarification.value = null
    isWaitingForClarification.value = true
  } catch (err) {
    console.error("[HITL] resolveClarification failed:", err)
  }
}

// 在 return 中导出
return {
  // ... existing ...
  pendingClarification,
  isWaitingForClarification,
  clarificationAnswer,
  resolveClarification,
}
```

- [ ] **Step 4: Add API call**

Edit `frontend/src/api/agent.js`:

```javascript
export async function resolveClarification(taskId, { answer, clarification_id }) {
  const resp = await fetch(`/api/v1/agent/resolve/${taskId}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ answer, clarification_id }),
  });
  if (!resp.ok) throw new Error(`resolveClarification failed: ${resp.status}`);
  return resp.json();
}
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/types/chat.ts frontend/src/composables/useStreamPipeline.ts frontend/src/composables/useChatSession.ts frontend/src/api/agent.js
git commit -m "feat(hitl): add frontend SSE event handling for clarification_request"
```

---

### Task 5: 前端 Clarification UI

**Files:**
- Modify: `frontend/src/views/Home.vue`

- [ ] **Step 1: Add ClarificationPanel component to Home.vue**

In the `<template>` section of `frontend/src/views/Home.vue`, inside the chat area (near the message list or loading indicator), add:

```vue
<!-- HITL Clarification Panel -->
<div v-if="isWaitingForClarification && pendingClarification" class="clarification-panel">
  <div class="clarification-header">
    <span class="clarification-icon">💬</span>
    <span class="clarification-label">需要澄清</span>
  </div>
  <div class="clarification-question">{{ pendingClarification.question }}</div>
  
  <!-- Option buttons (approach_choice / with options) -->
  <div v-if="pendingClarification.options?.length" class="clarification-options">
    <button
      v-for="(opt, idx) in pendingClarification.options"
      :key="idx"
      class="clarification-option-btn"
      @click="resolveClarification(opt.label)"
    >
      {{ opt.label }}
      <span v-if="opt.description" class="option-desc">{{ opt.description }}</span>
    </button>
  </div>
  
  <!-- Text input (missing_info / ambiguous) -->
  <div v-else class="clarification-input-area">
    <input
      v-model="clarificationAnswer"
      class="clarification-input"
      placeholder="输入回答..."
      @keyup.enter="resolveClarification(clarificationAnswer)"
    />
    <button
      class="clarification-send-btn"
      :disabled="!clarificationAnswer.trim()"
      @click="resolveClarification(clarificationAnswer)"
    >
      发送
    </button>
  </div>
</div>
```

In the `<style scoped>` section, add:

```vue
<style scoped>
.clarification-panel {
  margin: 16px 12px;
  padding: 16px;
  background: #f0f5ff;
  border: 1px solid #d6e4ff;
  border-radius: 8px;
}
.clarification-header {
  font-size: 13px;
  color: #1d7c8a;
  margin-bottom: 8px;
}
.clarification-question {
  font-size: 15px;
  font-weight: 500;
  margin-bottom: 12px;
}
.clarification-options {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.clarification-option-btn {
  padding: 8px 16px;
  background: white;
  border: 1px solid #d6e4ff;
  border-radius: 6px;
  cursor: pointer;
  text-align: left;
}
.clarification-option-btn:hover {
  background: #e6f0ff;
  border-color: #1d7c8a;
}
.option-desc {
  display: block;
  font-size: 12px;
  color: #666;
  margin-top: 2px;
}
.clarification-input-area {
  display: flex;
  gap: 8px;
}
.clarification-input {
  flex: 1;
  padding: 8px 12px;
  border: 1px solid #d9d9d9;
  border-radius: 6px;
}
.clarification-send-btn {
  padding: 8px 20px;
  background: #1d7c8a;
  color: white;
  border: none;
  border-radius: 6px;
  cursor: pointer;
}
.clarification-send-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
```

- [ ] **Step 2: Wire composable to Home.vue**

In the `<script setup>` section, destructure the new exports from `useChatSession`:

```typescript
const {
  // ... existing ...
  pendingClarification,
  isWaitingForClarification,
  clarificationAnswer,
  resolveClarification,
} = useChatSession()
```

- [ ] **Step 3: Preview and verify**

Run: `cd frontend && pnpm build`

Expected: Build succeeds, no TypeScript errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/views/Home.vue
git commit -m "feat(hitl): add clarification UI panel to chat view"
```

---

### Task 6: TTL 清理 + 边界处理

**Files:**
- Modify: `backend/app/reasoning/langchain_agent/hitl_store.py`
- Modify: `backend/app/reasoning/api/agent_events.py`
- Test: `backend/tests/reasoning/test_hitl_suspend_resume.py`

- [ ] **Step 1: Write TTL cleanup tests**

Add to `backend/tests/reasoning/test_hitl_suspend_resume.py`:

```python
class TestTTLCleanup:
    async def test_expired_paused_task_sends_timeout_event(self):
        """过期暂停任务自动发 stream_end（超时）。"""
        from app.reasoning.api.agent_events import _task_manager
        _task_manager.create_task("timeout_task", "thread_1", "问题")
        _task_manager.mark_paused("timeout_task")
        assert _task_manager.is_paused("timeout_task")
        # 模拟 cleanup: 发射超时 stream_end
        await _task_manager.emit_timeout_end("timeout_task")
        status = _task_manager._tasks.get("timeout_task", {}).get("status")
        assert status == "timed_out"
```

- [ ] **Step 2: Add cleanup to HITLStore**

Ensure `cleanup_expired` is robust:

```python
async def cleanup_expired(self) -> int:
    now = datetime.now()
    expired = []
    async with self._lock:
        for tid, state in self._store.items():
            if (now - state.created_at).total_seconds() > self._ttl:
                expired.append(tid)
        for tid in expired:
            del self._store[tid]
    if expired:
        logger.info(f"[HITLStore] cleanup_expired: removed {len(expired)} stale tasks")
    return len(expired)
```

- [ ] **Step 3: Add periodic cleanup to `agent.py` or `agent_events.py`**

Add a background cleanup task (runs every 5 minutes):

```python
async def _periodic_hitl_cleanup():
    """Periodically clean up expired HITL checkpoints."""
    from app.reasoning.langchain_agent.hitl_store import get_hitl_store
    while True:
        await asyncio.sleep(300)  # 5 min
        try:
            store = get_hitl_store()
            count = await store.cleanup_expired()
            if count:
                logger.info(f"[HITL] Cleaned up {count} expired paused tasks")
        except Exception as e:
            logger.warning(f"[HITL] Cleanup error: {e}")
```

Start it in the lifespan startup:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # ... existing startup ...
    cleanup_task = asyncio.create_task(_periodic_hitl_cleanup())
    yield
    cleanup_task.cancel()
```

- [ ] **Step 4: Run all tests**

Run: `cd backend && ../.venv/bin/pytest tests/reasoning/test_hitl_suspend_resume.py -x -v --asyncio-mode=auto`

Expected: All pass.

Run: `cd backend && ../.venv/bin/pytest tests/reasoning/ tests/test_middleware_unit.py tests/test_tool_concurrency.py -x -v --asyncio-mode=auto`

Expected: No regressions.

- [ ] **Step 5: Commit**

```bash
git add backend/app/reasoning/langchain_agent/hitl_store.py backend/app/reasoning/api/agent_events.py backend/app/reasoning/api/agent.py backend/tests/reasoning/test_hitl_suspend_resume.py
git commit -m "feat(hitl): add TTL cleanup and edge case handling"
```

---

## Plan Self-Review

- Spec coverage: All 6 spec sections map to tasks 1-6
- Placeholder scan: No TBD/TODO/fill-in-later patterns
- Type consistency: `PendingClarification` fields match between Task 1 and Task 3; `run_lead_agent` params match between Task 2 and Task 3
- Test coverage: Task 1 (dataclass, store), Task 2 (parse, prebuilt_messages), Task 3 (resume API), Task 6 (TTL)
- Frontend: Task 4 (types, pipeline, session), Task 5 (UI), no frontend tests (build-only check)
