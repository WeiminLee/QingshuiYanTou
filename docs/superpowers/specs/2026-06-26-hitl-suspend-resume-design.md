# HITL Suspend/Resume: Human-in-the-Loop via SSE 驻留暂停

Date: 2026-06-26

## Context

QingshuiYanTou 的 Human-in-the-loop 能力当前处于"骨架完整但功能断裂"状态：

- `ask_clarification` / `AskUserQuestion` 两个 `return_direct=True` 工具存在且可用
- `ClarificationMiddleware` 类已实现但被排除在中间件链外
- `_PENDING_CLARIFICATIONS` 只写不读（dead data store）
- 前端没有 `clarification_request` 事件监听
- 没有恢复机制——Agent 调用澄清工具后直接终止，用户响应开始全新线程

目标：对齐 DeerFlow 风格的 Graph-time HITL，实现真正的暂停/恢复。

## Architecture

### 核心理念：SSE 事件队列解耦

**关键洞见：** SSE 事件队列（`_events[task_id]`）和生产任务（`_run_stream_report`）是解耦的。

```
                    ┌─────────────────────────────────┐
                    │  EventSource (SSE)               │
                    │  GET /api/v1/agent/stream/{tid}  │
                    │  poll _events[task_id]           │←── 持续消费
                    └────────────────┬────────────────┘
                                     │
                            ┌────────▼────────┐
                            │  _events[task]  │  ← 异步队列
                            └──┬───────────┬──┘
                               │           │
                    ┌──────────▼──┐  ┌─────▼──────────┐
                    │  Run 1      │  │  Run 2 (resume)│
                    │  astream()  │  │  astream()     │
                    │  → clarify! │  │  → continue    │
                    │  → emit CR  │  │  → emit events │
                    │  → return   │  │  → stream_end  │
                    └─────────────┘  └────────────────┘
```

- Run 1 检测到澄清 → 发射 `clarification_request` → 保存 checkpoint → 返回
- Run 1 **不发射 `stream_end`**，任务状态标记为 `"paused"`
- SSE 连接保持打开，`event_generator` 持续轮询
- Resume 请求 → 新建 Run 2 → 推事件到**同一个** `_events[task_id]`
- SSE 连接无感知，继续消费 Run 2 的事件

### 与传统消息重入的对比

| 特性 | 消息重入 | SSE 驻留暂停 |
|------|---------|-------------|
| LLM 重新消费历史 | ✅ 全部重读 | ✅ 已有消息保留 |
| 预检重复（memory/pre-search/KG） | ❌ 重复执行 | ✅ 只做一次 |
| SSE 重新连接 | ❌ 需重连 | ✅ 连接保持 |
| 实现复杂度 | 低 | 中 |
| 事件断连恢复 | 自动恢复 | 需额外处理 |

## Data Model

### PendingClarification

```python
@dataclass
class PendingClarification:
    task_id: str
    thread_id: str
    clarification_id: str  # UUID
    question: str
    clarification_type: str  # missing_info / ambiguous / approach_choice / risk_confirmation
    options: list[dict] | None
    context: str | None
    messages: list[BaseMessage]  # Full message list at pause point
    run_config: dict  # Agent run configuration for resume
    created_at: datetime
```

### TaskStateManager 扩展

```python
class TaskStateManager:
    # 已有字段
    _tasks: dict[str, dict]  # {task_id: {status, thread_id, ...}}
    _events: dict[str, list[ReasoningEvent]]
    
    # 新增字段
    _pending: dict[str, PendingClarification]  # task_id → paused state
    _resume_events: dict[str, asyncio.Event]  # task_id → resume signal
    
    # 新增状态
    STATUS_PAUSED = "paused"
```

### SSE Event 类型扩展

```python
# 新增事件类型
CLARIFICATION_REQUEST = "clarification_request"
CLARIFICATION_RESOLVED = "clarification_resolved"
```

## Flow

### Normal Flow（不变）

```
POST /agent/stream/report {question, thread_id, ...}
  → create_task(task_id)
  → asyncio.create_task(_run_stream_report(task_id, thread_id, question, ...))
  → return {task_id, thread_id}

GET /api/v1/agent/stream/{task_id}
  → EventSourceResponse(event_generator(task_id))
  → 持续接收: thinking, tool_called, tool_result, ..., stream_end
```

### HITL Pause Flow

```
_run_stream_report(task_id, thread_id, question, ...)
  ├── 1. Preflight: clarification pre-check, pre-search, memory load, KG anchors, build prompt
  ├── 2. make_lead_agent() → create_agent
  ├── 3. agent.astream(state, config, stream_mode="values")
  │     ├── ... 正常事件 ...
  │     ├── AIMessage with tool_calls → tool_called SSE
  │     ├── ToolMessage for ask_clarification / AskUserQuestion
  │     │     │
  │     │     ├── Detect: tool_name in CLARIFICATION_TOOLS
  │     │     ├── Save messages + run_config to TaskStateManager._pending[task_id]
  │     │     ├── emit_fn("clarification_request", {
  │     │     │     "clarification_id": id,
  │     │     │     "question": question,
  │     │     │     "type": clarification_type,
  │     │     │     "options": options,
  │     │     │     "context": context,
  │     │     │     "stage": "clarification_request",
  │     │     │ })
  │     │     ├── update_status(task_id, "paused")
  │     │     └── **返回**（不发射 stream_end）
  │     │
  │     └── ... 其他工具正常处理 ...
  │
  └── 4. 返回（stream_end 未发射 → SSE 连接保持 polling）
```

### HITL Resume Flow

```
POST /agent/resolve/{task_id} {answer, clarification_id}
  │
  ├── 1. Validate: task status == "paused"
  ├── 2. Pop PendingClarification from _pending[task_id]
  ├── 3. Restore saved messages
  ├── 4. Append answer as HumanMessage
  ├── 5. emit_fn("clarification_resolved", {clarification_id, answer})
  ├── 6. update_status(task_id, "running")
  └── 7. asyncio.create_task(_resume_stream_report(task_id, messages, run_config))
        │
        ├── resume_fn() → emit_to_manager (same task_id)
        ├── make_lead_agent() with same config
        ├── agent.astream({"messages": messages}, config, stream_mode="values")
        │     ├── 正常事件（thinking, tool_called, tool_result...）
        │     └── agent 看到完整历史 + 用户回答，继续分析
        ├── 最终 emit stream_end
        └── update_status(task_id, "completed")
```

### SSE 连接生命周期

```
Frontend                        Backend
   │                              │
   ├── POST /agent/stream/report──┤
   │         {task_id, thread_id} │
   ├── GET /api/v1/agent/stream───┤
   │    EventSource connects      │
   │                              ├── _run_stream_report (Run 1)
   │        thinking_delta        │
   │        tool_called           │
   │        tool_result           │
   │        clarification_request │←── Agent 需要澄清
   │                              │  → Run 1 结束
   │                              │  → 状态: paused
   │   显示澄清 UI ───────────────┤
   │   ┌──────────────────┐      │
   │   │ 分析哪只股票？    │      │
   │   │ [中际旭创] [宁德] │      │
   │   └──────────────────┘      │
   │      用户点击"中际旭创"     │
   ├── POST /agent/resolve───────┤
   │    {task_id, answer}         │
   │                              ├── _resume_stream_report (Run 2)
   │        clarification_resolved│
   │        thinking_delta        │
   │        tool_called           │
   │        tool_result           │
   │        stream_end            │←── 最终完成
   │                              │  → 状态: completed
   │   显示完整分析报告           │
   │   关闭 EventSource           │
```

## Component Changes

### New Files

`backend/app/reasoning/langchain_agent/hitl_store.py`

```python
"""HITL checkpoint store — thread state persistence for suspend/resume."""

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from langchain_core.messages import BaseMessage


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
        """Remove expired entries. Returns count of removed items."""
        now = datetime.now()
        expired = []
        async with self._lock:
            for tid, state in self._store.items():
                if (now - state.created_at).total_seconds() > self._ttl:
                    expired.append(tid)
            for tid in expired:
                del self._store[tid]
        return len(expired)


# Global singleton
_hitl_store = HITLStore()


def get_hitl_store() -> HITLStore:
    return _hitl_store
```

### Changed Files

#### `client.py`

**`run_lead_agent()`** — 新增参数：

```python
async def run_lead_agent(
    question: str,
    thread_id: str | None = None,
    task_id: str | None = None,  # SSE task_id for HITLStore key (was thread_id before bugfix)
    *,
    model_name: str | None = None,
    max_turns: int = 8,
    emit_fn: Callable | None = None,
    plan_mode: bool = False,
    prebuilt_messages: list[BaseMessage] | None = None,  # NEW: resume from checkpoint
    skip_preflight: bool = False,  # NEW: skip preflight on resume
) -> dict:
```

- `prebuilt_messages` 提供时：跳过预检（pre-search, memory, KG anchors, system prompt），
  用 `prebuilt_messages` 作为初始状态。此时 `prebuilt_messages[0]` 已是原始 `SystemMessage`，
  不需要再构建新的 system prompt，`make_lead_agent(system_prompt=None)` 避免 `create_agent` 重复添加。
- `prebuilt_messages` 为 `None` 时：当前逻辑不变

**暂停检测机制** — Stream loop 内 `is_clarified` 标志：

```python
CLARIFICATION_TOOLS = frozenset({"ask_clarification", "AskUserQuestion"})

is_clarified = False
clarification_data: dict | None = None
# messages 全局列表：记录所有已处理消息，用于 checkpoint 保存
all_messages: list[BaseMessage] = []

try:
    async for chunk in agent.astream(state, config=config, stream_mode="values"):
        messages = chunk.get("messages", [])
        turn_count += 1

        for msg in messages:
            msg_id = getattr(msg, "id", None) or str(uuid.uuid4())[:8]
            if msg_id in seen_msg_ids:
                continue
            seen_msg_ids.add(msg_id)

            if isinstance(msg, AIMessage):
                # Normal thinking — but skip if this is return_direct echo
                if is_clarified:
                    continue  # 跳过 return_direct 的响应回显

                # Tool calls — emit normally
                if msg.tool_calls:
                    for tc in msg.tool_calls:
                        ...

                # Text content
                text = _extract_text(msg.content)
                if text and not is_clarified:
                    ...

            elif isinstance(msg, ToolMessage):
                result_str = _extract_text(msg.content) or str(msg.content)
                tool_name = getattr(msg, "name", "unknown")
                tool_call_id = getattr(msg, "tool_call_id", None) or msg_id

                # 🌟 CLARIFICATION DETECTION
                if tool_name in CLARIFICATION_TOOLS:
                    clarification_data = _parse_clarification_result(
                        tool_name, result_str
                    )
                    # Save checkpoint: full messages snapshot
                    from app.reasoning.langchain_agent.hitl_store import (
                        PendingClarification, get_hitl_store,
                    )
                    store_key = task_id or thread_id  # task_id is the correct HITLStore key
                    save_messages = list(all_messages)
                    # Filter out the clarification ToolMessage itself from checkpoint
                    if isinstance(msg, ToolMessage) and save_messages and save_messages[-1] is msg:
                        save_messages.pop()
                    await get_hitl_store().save(
                        store_key,
                        PendingClarification(
                            task_id=store_key,
                            thread_id=thread_id,
                            clarification_id=clarification_data["clarification_id"],
                            question=clarification_data["question"],
                            clarification_type=clarification_data.get("type", "ambiguous"),
                            options=clarification_data.get("options"),
                            context=clarification_data.get("context"),
                            messages=save_messages,  # 消息快照（不含 clarification ToolMessage 自身）
                            run_config={
                                "model_name": model_name,
                                "max_turns": max_turns,
                                "thread_id": thread_id,
                                "plan_mode": plan_mode,
                                "question": question,  # store original question for resume report topic
                            },
                            created_at=datetime.now(),
                        ),
                    )
                    # Emit clarification_request SSE
                    await emit_fn("clarification_request", {
                        "clarification_id": clarification_data["clarification_id"],
                        "question": clarification_data["question"],
                        "type": clarification_data.get("type", "ambiguous"),
                        "options": clarification_data.get("options"),
                        "context": clarification_data.get("context"),
                    })
                    is_clarified = True
                    # DON'T push this tool result as normal tool_result SSE
                    # DON'T emit stream_end — loop will break but no end event
                    continue

                # Normal tool result — emit normally
                ...

        # 在 chunk 处理后检测暂停
        if is_clarified:
            break

except GraphRecursionError as e:
    ...

# ── 发射 stream_end ────────────────────────────
# 仅当不是暂停时才发射 stream_end
if not is_clarified:
    if emit_fn:
        ...
```

**辅助函数 `_parse_clarification_result()`**：

```python
def _parse_clarification_result(tool_name: str, result_str: str) -> dict:
    """解析 clarification 工具返回结果，提取结构化数据。

    两种工具格式：
    - AskUserQuestion: JSON {"questions": [...]}
    - ask_clarification（旧）: Markdown 文本含 clarification_id / question
    """
    if tool_name == "AskUserQuestion":
        import json
        try:
            data = json.loads(result_str)
        except json.JSONDecodeError:
            data = {}
        questions = (data.get("questions") or [{}])[0]
        return {
            "clarification_id": data.get("clarification_id", task_id),
            "question": questions.get("question", result_str[:200]),
            "type": "ambiguous",
            "options": questions.get("options"),
            "context": questions.get("context"),
        }
    else:
        # ask_clarification (old format)
        return {
            "clarification_id": _extract_clarification_id(result_str),
            "question": _extract_question(result_str),
            "type": _extract_type(result_str),
            "options": _extract_options(result_str),
            "context": _extract_context(result_str),
        }
```

#### `agent.py` / `agent_events.py`

**新增 Resume Endpoint** in `agent.py`:

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
        raise HTTPException(404, "No pending clarification found")
    
    # Emit resolved event
    await _task_manager.emit(
        task_id,
        ReasoningEvent(
            type="clarification_resolved",
            task_id=task_id,
            stage="clarification_resolved",
            data={"clarification_id": body.clarification_id},
        ),
    )
    
    # Start resume run
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

**`_resume_stream_report()`** — 类似 `_run_stream_report()` 但跳过预检：

```python
async def _resume_stream_report(
    task_id: str,
    thread_id: str,
    messages: list[BaseMessage],
    run_config: dict,
):
    """Resume a paused agent run from checkpoint."""
    async def emit_fn(ev_type: str, data: dict):
        """async 回调，复用 _run_stream_report 的 _emit_to_manager。"""
        from app.reasoning.api.agent import _emit_to_manager
        await _emit_to_manager(ev_type, data)

    try:
        _task_manager.update_status(task_id, "running")

        # 不跑预检，直接用 saved messages
        result = await run_lead_agent(
            question="",  # 当 prebuilt_messages 提供时忽略
            thread_id=thread_id,
            task_id=task_id,  # Use SSE task_id as HITLStore key
            model_name=run_config.get("model_name"),
            max_turns=run_config.get("max_turns", 8),
            emit_fn=emit_fn,
            prebuilt_messages=messages,
            skip_preflight=True,
            plan_mode=run_config.get("plan_mode", False),
        )

        # 发射 stream_end
        raw_analysis = result.get("content", "") if result else ""
        report = _build_analysis_report(
            topic=run_config.get("question", "继续分析"),  # Use stored original question
            raw_analysis=raw_analysis,
            turns=result.get("turns", 0),
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

#### `lead_agent.py`

`_build_middlewares()` 保持当前链不变（ClarificationMiddleware 不在链中，澄清工具拦截在 stream loop 级别处理）。

#### `types/chat.ts` (Frontend)

```typescript
// 新增事件类型
export type SSEEventType =
  // ... 现有类型 ...
  | "clarification_request"
  | "clarification_resolved";

// 新增数据类型
export interface ClarificationItem {
  clarification_id: string;
  question: string;
  type: "missing_info" | "ambiguous" | "approach_choice" | "risk_confirmation";
  options?: Array<{
    label: string;
    description?: string;
  }>;
  context?: string;
}

// 新增回调
export interface SSECallbacks {
  // ... 现有回调 ...
  onClarification?: (item: ClarificationItem) => void;
  onClarificationResolved?: (data: { clarification_id: string }) => void;
}
```

#### `useStreamPipeline.ts` (Frontend)

```typescript
export interface StreamPipelineCallbacks {
  // ... 现有回调 ...
  onClarification?: (item: ClarificationItem) => void;
}

// handleBufferedEvent 新增分支：
if (eventType === "clarification_request") {
  pipeline.onClarification?.({
    clarification_id: data.clarification_id,
    question: data.question,
    type: data.type,
    options: data.options,
    context: data.context,
  });
}
```

#### `useChatSession.ts` (Frontend)

```typescript
// connectSSE 新增事件监听：
es.addEventListener("clarification_request", (e) => {
  const data = JSON.parse(e.data).data;
  pipeline.onClarification?.({
    clarification_id: data.clarification_id,
    question: data.question,
    type: data.type,
    options: data.options,
    context: data.context,
  });
});

es.addEventListener("clarification_resolved", (e) => {
  // Optionally show a "resolved" indicator
});

// 新增方法：
async function resolveClarification(answer: string): Promise<void> {
  const taskId = taskId.value;
  if (!taskId) return;
  
  await api.resolveClarification(taskId, {
    answer,
    clarification_id: pendingClarification.value?.clarification_id,
  });
  pendingClarification.value = null;
  isWaitingForClarification.value = false;
}
```

#### `Home.vue` (Frontend)

新增 `ClarificationPanel` 或内联 UI：

```vue
<template>
  <!-- 在消息列表底部，正在加载时显示 -->
  <div v-if="isWaitingForClarification" class="clarification-panel">
    <div class="clarification-question">{{ clarification.question }}</div>
    
    <!-- 选项按钮（approach_choice 类型） -->
    <div v-if="clarification.options?.length" class="clarification-options">
      <button
        v-for="opt in clarification.options"
        :key="opt.label"
        @click="resolveClarification(opt.label)"
      >
        {{ opt.label }}
      </button>
    </div>
    
    <!-- 文本输入（missing_info / ambiguous 类型） -->
    <div v-else class="clarification-input">
      <input v-model="clarificationAnswer" placeholder="输入回答..." />
      <button @click="resolveClarification(clarificationAnswer)">发送</button>
    </div>
  </div>
</template>
```

#### `api/agent.js` (Frontend)

```javascript
export async function resolveClarification(taskId, { answer, clarification_id }) {
  const resp = await fetch(`/api/v1/agent/resolve/${taskId}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ answer, clarification_id }),
  });
  return resp.json();
}
```

## TaskStateManager 扩展

```python
class TaskStateManager:
    # 新增状态常量
    STATUS_PAUSED = "paused"
    
    # 恢复事件：task_id → asyncio.Event
    _resume_events: dict[str, asyncio.Event] = {}
    
    # 暂停计数：用于 TTL 清理
    _paused_at: dict[str, float] = {}
    
    def mark_paused(self, task_id: str) -> None:
        """标记任务为暂停状态。"""
        self._tasks[task_id]["status"] = "paused"
        self._paused_at[task_id] = time.time()
    
    def is_paused(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        return task is not None and task.get("status") == "paused"
```

## Edge Cases

### 重复 Resume
- `HITLStore.pop()` 是原子操作，第二次调用返回 `None` → 404
- 前端在收到 `clarification_resolved` 后禁用再次发送按钮

### Resume 超时
- pause 后启动 `_schedule_resume_timeout`（默认 600s）
- 超时时 `store.pop()` + `emit_timeout_end()` → SSE `stream_end`（`stop_reason="timeout"`）
- 超时后用户尝试 resume → 404（store 已清理）
- `event_generator` 将 `"timed_out"` 视为终止态，SSE 连接正确关闭

### TTL 过期
- 后台定期 `cleanup_expired()` 清理超过 1h 的暂停
- 清理时发射 `stream_end`（内容为"对话已超时"）

### 用户断开连接
- `EventSourceResponse` close → 后台 `asyncio.CancelledError`
- `_task_manager` 的 TTL 清理处理残留暂停

### 多次暂停
- 当前设计只支持单次暂停（resume 后完成任务）
- 多次暂停需要额外状态管理（暂不支持）

## 附录：ClarificationMiddleware 状态

当前 `backend/app/reasoning/langchain_agent/middlewares/clarification.py` 中的 `ClarificationMiddleware`：

- **不再使用** — 不会被注册到 `lead_agent._build_middlewares()` 中
- 其预检功能（`_needs_clarification` / `_build_suggestions`）已被 `client.py` 中的同步 pre-check 替代
- 保留文件（不删除）以避免引入 import 断裂，但功能已由 HITL 流循环拦截完全替代

## 附录：deer-flow / hermes-agent 对比审查缺陷

### 🔴 CRITICAL: HITLStore 键值错位（已修复）

`client.py` 以 `thread_id` 为 key 保存 checkpoint，但 resolve endpoint 以 URL 的 `task_id` 查找。两者是不同的 UUID（`stream/report` 端点分别生成），导致 resume 永远返回 404。

**修复（已实施）**：给 `run_lead_agent` 加可选 `task_id` 参数，HITLStore save 时使用 `task_id or thread_id` 为 key。

### 🟡 MEDIUM: checkpoint 包含 clarification ToolMessage（已修复）

保存的 `all_messages` 包含了触发暂停的 clarification ToolMessage 自身，resume 时 LLM 会看到自己的澄清请求，可能导致混淆。

**修复（已实施）**：保存前过滤掉最后一条 clarification ToolMessage。

### 🟡 MEDIUM: 无 agent 端超时（已修复）

`HITLStore` 有 TTL 清理但 `_run_stream_report` 没有 agent 侧超时。对比 hermes-agent 的 600s 超时。

**修复（已实施）**：`_run_stream_report` 中 pause 后启动 `_schedule_resume_timeout`（默认 600s），超时后 `store.pop()` + `emit_timeout_end()`。`event_generator` 新增 `"timed_out"` 作为终止态。

### 🟢 LOW: Resume 报告硬编码 topic（已修复）

`_resume_stream_report` 生成 `AnalysisReport(topic="继续分析")`，丢失原始问题。

**修复（已实施）**：将 `question` 存入 `run_config`，resume 时读取。

### 🟢 LOW: 仅内存存储（未修复）

`HITLStore` 是纯内存实现，服务重启后丢失。与 deer-flow 的 `_pending_clarifications` (30min TTL) 相当，但对比 hermes 的 SQLite `SessionDB` 有差距。

### ✅ 已验证无问题

| 项目 | 结论 |
|------|------|
| `return_direct=True` | `ask_clarification` 和 `AskUserQuestion` 均已设置 ✅ |
| SSE 事件透传 | `clarification_request` 不在 `_VISIBLE_MAP`，前端透传正确 ✅ |
| 测试覆盖 | 13 HITL 专测 + 63 回归测试通过 ✅ |

## 未纳入范围

- **ClarificationMiddleware 改造**：保留当前预检逻辑，不在中间件链中注册。拦截在 stream loop 级别处理更直接。
- **前端建议卡片 UI 重构**：当前建议卡片（suggestion chips）保留，HITL 用单独面板展示。两者不冲突。
- **暂停持久化**：当前使用内存存储，暂不持久化到 MongoDB。
- **多次暂停**：如果 resume 后的 Agent 又调用 `ask_clarification`，第二次暂停会覆盖第一次。
- **自进化**：非本模块范围。

## 测试计划

### 后端测试

`tests/reasoning/test_hitl_suspend_resume.py`:

1. **clarification detection**: stream loop 正确识别 `ask_clarification`/`AskUserQuestion` tool results
2. **checkpoint save**: `HITLStore.save()`/`pop()` 正确保存/恢复
3. **SSE events**: clarification_request 事件格式正确，没有 stream_end
4. **resume with answer**: resume 后 agent 正确收到用户回答
5. **TTL cleanup**: 过期暂停被清理
6. **duplicate resume**: 第二次 resume 返回 404
7. **prebuilt_messages**: `run_lead_agent(prebuilt_messages=...)` 跳过预检

### 前端测试

`sse_streaming.test.js`:

1. `clarification_request` 事件被正确处理
2. 暂停 UI 出现，选项按钮可点击
3. 回答后 `resolveClarification` API 被调用
4. 后续 SSE 事件正常接收

## 实施顺序

### Step 1: `HITLStore` + 数据模型
- 新建 `hitl_store.py`：`PendingClarification` dataclass + `HITLStore` 类
- 扩展 `TaskStateManager`：`mark_paused()` / `is_paused()`
- 测试：3-5 个单元测试

### Step 2: `run_lead_agent` 暂停检测
- `client.py`：流循环中检测 clarification 工具结果
- 保存 checkpoint、发射 `clarification_request`、不发射 `stream_end`
- 新增 `prebuilt_messages` / `skip_preflight` 参数
- 测试：5-7 个暂停流集成测试

### Step 3: Resume API + 恢复运行
- `agent.py`：新增 `POST /api/v1/agent/resolve/{task_id}`
- `agent_events.py` 或 `agent.py`：新增 `_resume_stream_report()`
- 测试：5-7 个 resume 集成测试

### Step 4: 前端 SSE 事件处理
- `types/chat.ts`：新增 event/data 类型
- `useStreamPipeline.ts`：新增 `onClarification` 回调
- `useChatSession.ts`：新增 `clarification_request` 监听 + `resolveClarification()`
- `api/agent.js`：新增 `resolveClarification()` API 调用
- 测试：3-5 个前端测试

### Step 5: 前端 Clarification UI
- `Home.vue`：新增澄清面板（问题文本 + 选项按钮 / 输入框）
- 样式隔离、防抖处理
- 测试：3-5 个前端测试

### Step 6: TTL 清理 + 边界处理
- `TaskStateManager`：定期 cleanup expired
- 断网恢复：前端重连后检查任务状态，如为 paused 保持 UI
- 测试：2-3 个清理测试
