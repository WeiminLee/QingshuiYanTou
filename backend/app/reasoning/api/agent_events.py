"""
Agent 分析事件系统（Task 27）

后端产生 SSE 事件 → 前端 EventSource 消费：

事件类型：
- reasoning_started    — 开始分析
- retrieval_started   — 开始检索
- retrieval_done      — 检索完成（含结果数量）
- graph_search_done   — 图谱检索完成
- thinking           — LLM 思考中
- tool_called        — 调用工具
- tool_result        — 工具结果
- turn_completed     — 某轮 deliberation 完成
- reflection_done    — 自评完成
- reasoning_completed — 分析完成
- error             — 错误

SSE 端点：GET /api/v1/agent/stream/{task_id}
"""

import asyncio
import json
import logging
import time
from collections import defaultdict
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import StrEnum

logger = logging.getLogger(__name__)


# ── 事件类型定义 ──────────────────────────────────────


class EventType(StrEnum):
    REASONING_START = "reasoning_start"
    REASONING_STARTED = "reasoning_started"
    RETRIEVAL_STARTED = "retrieval_started"
    RETRIEVAL_DONE = "retrieval_done"
    GRAPH_SEARCH_DONE = "graph_search_done"
    THINKING = "thinking"
    TOOL_CALLED = "tool_called"
    TOOL_RESULT = "tool_result"
    TURN_COMPLETED = "turn_completed"
    REFLECTION_DONE = "reflection_done"
    REASONING_COMPLETED = "reasoning_completed"
    ERROR = "error"
    TASK_STARTED = "task_started"
    TASK_RUNNING = "task_running"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    HEARTBEAT = "ping"
    STREAM_END = "stream_end"


@dataclass
class ReasoningEvent:
    """推理事件"""

    type: str
    task_id: str
    stage: str  # 推理阶段描述
    data: dict = field(default_factory=dict)
    timestamp: str = ""
    turn: int = 0  # 当前轮次（0=预热）
    seq: int = 0  # 事件序号（用于 SSE 去重）

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()

    def to_sse_dict(self) -> dict:
        """
        返回符合 SSE 标准的 dict，供 ensure_bytes() 处理。

        返回格式：
        {
            "event": <event_type>,  # 显式指定事件类型
            "data": json.dumps({...})  # JSON 数据
        }
        """
        return {"event": self.type, "data": json.dumps(asdict(self), ensure_ascii=False)}


# ── 任务状态管理器 ──────────────────────────────────────


class TaskStateManager:
    """
    任务状态 + 事件历史管理器（全局单例）。

    每个 task_id 维护一个事件历史列表，每个 SSE 连接独立读取。
    带 TTL 清理，防止内存无限增长。
    """

    STATUS_PAUSED = "paused"

    def __init__(self):
        self._tasks: dict[str, dict] = {}
        self._events: dict[str, list[ReasoningEvent]] = defaultdict(list)
        self._seqs: dict[str, int] = {}  # task_id → 下一个事件序号
        self._timestamps: dict[str, float] = {}  # task_id → 创建时间戳
        self._last_content: dict[str, str] = {}  # task_id → 上一次发送的完整文本（用于计算 delta）
        self._lock = asyncio.Lock()
        self._cleanup_counter = 0
        self._CLEANUP_INTERVAL = 10  # 每 N 个任务触发一次清理
        self._TTL_SECONDS = 3600  # 1 小时超时
        self._MAX_EVENTS = 500  # Bug #9: 单任务最大事件数，防止 OOM

    def create_task(self, task_id: str, thread_id: str, question: str) -> None:
        """创建任务记录"""
        import time

        self._tasks[task_id] = {
            "task_id": task_id,
            "thread_id": thread_id,
            "question": question,
            "status": "pending",
            "created_at": datetime.now().isoformat(),
            "completed_at": "",
        }
        self._events[task_id] = []
        self._seqs[task_id] = 0
        self._timestamps[task_id] = time.time()

        # 定期触发清理
        self._cleanup_counter += 1
        if self._cleanup_counter >= self._CLEANUP_INTERVAL:
            self._cleanup_counter = 0
            self._cleanup()

    def _cleanup(self) -> int:
        """清理超时任务"""
        import time

        now = time.time()
        to_remove = [tid for tid, ts in list(self._timestamps.items()) if now - ts > self._TTL_SECONDS]
        for tid in to_remove:
            self._tasks.pop(tid, None)
            self._events.pop(tid, None)
            self._seqs.pop(tid, None)
            self._timestamps.pop(tid, None)
        if to_remove:
            logger.info(f"[TaskManager] 清理 {len(to_remove)} 个超时任务（TTL={self._TTL_SECONDS}s）")
        return len(to_remove)

    def mark_paused(self, task_id: str) -> None:
        """标记任务为暂停状态（不发射 stream_end）。"""
        self._tasks[task_id]["status"] = "paused"

    def is_paused(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        return task is not None and task.get("status") == "paused"

    def get_task(self, task_id: str) -> dict | None:
        return self._tasks.get(task_id)

    def update_status(self, task_id: str, status: str) -> None:
        if task_id in self._tasks:
            self._tasks[task_id]["status"] = status
            if status == "done":
                self._tasks[task_id]["completed_at"] = datetime.now().isoformat()

    def set_result(self, task_id: str, result: dict) -> None:
        """设置任务结果（供 /invoke/{task_id}/result 使用，消除独立 _task_store）"""
        if task_id in self._tasks:
            self._tasks[task_id]["result"] = result

    def list_recent_tasks(self, limit: int = 20) -> list[dict]:
        """Return recent tasks sorted by creation time (newest first)."""
        sorted_tasks = sorted(
            self._tasks.values(),
            key=lambda t: t.get("created_at", ""),
            reverse=True,
        )
        return sorted_tasks[:limit]

    def update_last_content(self, task_id: str, content: str) -> None:
        """Update the last content delta for a task."""
        self._last_content[task_id] = content

    async def emit(self, task_id: str, event: ReasoningEvent) -> None:
        """发送事件（写入历史列表，自动分配序号，容量超限先进先出截断）"""
        if task_id not in self._seqs:
            self._seqs[task_id] = 0
        event.seq = self._seqs.get(task_id, 0)
        self._seqs[task_id] = event.seq + 1

        # Bug #9: 容量上限，超限先进先出截断
        events = self._events[task_id]
        if len(events) >= self._MAX_EVENTS:
            events.pop(0)  # 移除最旧事件（FIFO）
        events.append(event)

        # DEBUG: 打印事件发送（不含敏感 data 字段，仅在 debug 级别记录）
        logger.debug(f"[TaskStateManager] Emit event: type={event.type}, task_id={task_id}, seq={event.seq}")

    def get_events(self, task_id: str) -> list[ReasoningEvent]:
        """获取任务的所有事件"""
        return self._events.get(task_id, [])

    def clear_task(self, task_id: str) -> None:
        """清理任务数据（防止内存泄漏）"""
        self._tasks.pop(task_id, None)
        self._events.pop(task_id, None)
        self._seqs.pop(task_id, None)
        self._timestamps.pop(task_id, None)
        self._last_content.pop(task_id, None)

    async def emit_timeout_end(self, task_id: str) -> None:
        """Emit a timeout stream_end for a paused task that expired."""
        self._tasks[task_id]["status"] = "timed_out"
        await self.emit(
            task_id,
            ReasoningEvent(
                type="stream_end",
                task_id=task_id,
                stage="stream_end",
                data={
                    "content": "",
                    "stop_reason": "timeout",
                    "report_content": "",
                    "turns": self._tasks[task_id].get("turns", 0),
                },
            ),
        )


# 全局单例
_task_manager = TaskStateManager()


# ── 便捷事件发送函数 ──────────────────────────────────────


async def emit_reasoning_started(task_id: str, question: str, max_turns: int) -> None:
    await _task_manager.emit(
        task_id,
        ReasoningEvent(
            type=EventType.REASONING_START,
            task_id=task_id,
            stage="开始分析",
            data={"question": question, "max_turns": max_turns},
        ),
    )


async def emit_retrieval_started(task_id: str, turn: int, query: str) -> None:
    await _task_manager.emit(
        task_id,
        ReasoningEvent(
            type=EventType.RETRIEVAL_STARTED,
            task_id=task_id,
            stage=f"第 {turn + 1} 轮：知识库检索中",
            data={"turn": turn, "query": query[:100]},
            turn=turn,
        ),
    )


async def emit_retrieval_done(task_id: str, turn: int, chunks_count: int, graph_entities: int) -> None:
    await _task_manager.emit(
        task_id,
        ReasoningEvent(
            type=EventType.RETRIEVAL_DONE,
            task_id=task_id,
            stage=f"第 {turn + 1} 轮：检索完成",
            data={
                "turn": turn,
                "chunks_count": chunks_count,
                "graph_entities": graph_entities,
            },
            turn=turn,
        ),
    )


async def emit_thinking(task_id: str, turn: int, delta: str, content: str = "") -> None:
    await _task_manager.emit(
        task_id,
        ReasoningEvent(
            type=EventType.THINKING,
            task_id=task_id,
            stage=delta,
            data={
                "turn": turn,
                "delta": delta,
                "content": content,
            },
            turn=turn,
        ),
    )


async def emit_tool_called(task_id: str, turn: int, tool_name: str, args: dict) -> None:
    await _task_manager.emit(
        task_id,
        ReasoningEvent(
            type=EventType.TOOL_CALLED,
            task_id=task_id,
            stage=f"调用工具：{tool_name}",
            data={"tool": tool_name, "args": {k: str(v)[:50] for k, v in args.items()}},
            turn=turn,
        ),
    )


async def emit_tool_result(task_id: str, turn: int, tool_name: str, chars: int) -> None:
    await _task_manager.emit(
        task_id,
        ReasoningEvent(
            type=EventType.TOOL_RESULT,
            task_id=task_id,
            stage=f"工具 {tool_name} 执行完成",
            data={"tool": tool_name, "chars": chars},
            turn=turn,
        ),
    )


async def emit_turn_completed(task_id: str, turn: int, turn_summary: str) -> None:
    await _task_manager.emit(
        task_id,
        ReasoningEvent(
            type=EventType.TURN_COMPLETED,
            task_id=task_id,
            stage=f"第 {turn + 1} 轮完成",
            data={"turn": turn, "summary": turn_summary[:200]},
            turn=turn,
        ),
    )


async def emit_reflection_done(task_id: str, turn: int, pending: list, should_continue: bool) -> None:
    await _task_manager.emit(
        task_id,
        ReasoningEvent(
            type=EventType.REFLECTION_DONE,
            task_id=task_id,
            stage="自评中",
            data={"turn": turn, "pending": pending[:3], "should_continue": should_continue},
            turn=turn,
        ),
    )


async def emit_reasoning_completed(task_id: str, total_turns: int, report_id: str) -> None:
    await _task_manager.emit(
        task_id,
        ReasoningEvent(
            type=EventType.REASONING_COMPLETED,
            task_id=task_id,
            stage="分析完成",
            data={"total_turns": total_turns, "report_id": report_id},
        ),
    )


async def emit_graph_search_done(task_id: str, turn: int, entity_count: int, relation_count: int) -> None:
    """图谱检索完成事件 — 供前端 ReportView 渲染图谱节点计数"""
    await _task_manager.emit(
        task_id,
        ReasoningEvent(
            type=EventType.GRAPH_SEARCH_DONE,
            task_id=task_id,
            stage=f"第 {turn + 1} 轮：图谱检索完成",
            data={
                "turn": turn,
                "entity_count": entity_count,
                "relation_count": relation_count,
            },
            turn=turn,
        ),
    )


async def emit_error(task_id: str, error: str) -> None:
    await _task_manager.emit(
        task_id,
        ReasoningEvent(
            type=EventType.ERROR,
            task_id=task_id,
            stage="发生错误",
            data={"error": error},
        ),
    )


# ── SSE 连接并发限制 ──────────────────────────────────────

_sse_semaphore: asyncio.Semaphore | None = None
_MAX_CONCURRENT_SSE = 20  # 最多同时 20 个 SSE 连接
PING_INTERVAL = 60  # Phase E: ping 保活间隔（秒）


def _get_semaphore() -> asyncio.Semaphore:
    global _sse_semaphore
    if _sse_semaphore is None:
        _sse_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_SSE)
    return _sse_semaphore


# ── SSE 端点 ──────────────────────────────────────


async def event_generator(task_id: str) -> AsyncIterator[ReasoningEvent]:
    """
    SSE 事件流生成器。

    每个 SSE 连接独立读取事件历史列表，通过轮询检测新事件。
    支持断线重连：首次连接推送所有历史事件，之后只推送新事件。
    受 Semaphore 并发限制，超时自动断开。
    """
    # 获取或创建信号量（单例）
    semaphore = _get_semaphore()
    try:
        # 尝试获取信号量（最多等 5 秒）
        await asyncio.wait_for(semaphore.acquire(), timeout=5.0)
    except TimeoutError:
        # 并发上限已满，拒绝连接
        logger.warning(f"[SSE] 并发连接数已达上限（{_MAX_CONCURRENT_SSE}），拒绝 task_id={task_id}")
        yield ReasoningEvent(
            type="rejected",
            task_id=task_id,
            stage="连接被拒绝",
            data={"reason": "too_many_connections"},
        ).to_sse_dict()
        return

    last_count = 0
    # 放宽到 30 分钟：主 loop 不设外层超时，超时只发生在工具层。
    # 用户 memory 明确：超时只在工具层，pre_search/图谱查询等异步任务有独立超时。
    # task_state.status 为终止信号，max_wait 仅作为保底断线保护。
    max_wait = 1800
    start_time = time.time()
    last_ping_time = start_time  # Phase E: 追踪上次 ping 时间

    try:
        logger.info(f"[SSE] 连接已建立: task_id={task_id}")
        while True:
            now = time.time()
            elapsed = now - start_time
            remaining = max_wait - elapsed

            if remaining <= 0:
                yield ReasoningEvent(
                    type="timeout",
                    task_id=task_id,
                    stage="任务超时",
                    data={"reason": "max_wait_exceeded"},
                ).to_sse_dict()
                break

            task_state = _task_manager.get_task(task_id)
            events = _task_manager.get_events(task_id)
            event_count = len(events)

            if task_state and task_state["status"] in ("done", "failed"):
                # 推送剩余事件（含 stream_end + 完整 report_content，由 agent 端发射）
                for i in range(last_count, event_count):
                    yield events[i].to_sse_dict()
                break

            if event_count > last_count:
                # 有新事件，推送增量
                for i in range(last_count, event_count):
                    yield events[i].to_sse_dict()
                last_count = event_count

            # Phase E: ping 保活（每 PING_INTERVAL 秒发送一次）
            if now - last_ping_time >= PING_INTERVAL:
                yield ReasoningEvent(
                    type="ping",
                    task_id=task_id,
                    stage="ping",
                    data={},
                ).to_sse_dict()
                last_ping_time = now

            # 低延迟轮询，降低事件批量堆积导致的"分块输出"感
            await asyncio.sleep(0.03)
    except asyncio.CancelledError:
        logger.info(f"[SSE] 连接被客户端断开: task_id={task_id}")
        raise
    except Exception as e:
        logger.warning(f"[SSE] 异常: task_id={task_id}, error={e}")
    finally:
        try:
            semaphore.release()
        except Exception:
            pass
        logger.info(f"[SSE] 连接已释放: task_id={task_id}")


# ── 任务管理器依赖注入（供其他模块用） ─────────────────────────────


def get_task_manager() -> TaskStateManager:
    return _task_manager
