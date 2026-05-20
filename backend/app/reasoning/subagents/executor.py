"""
SubagentExecutor — 后台线程池 + 状态机执行器

参考 DeerFlow subagents/executor.py 设计：
- ThreadPoolExecutor 后台执行，不阻塞主 agent
- Task 状态机：PENDING → RUNNING → COMPLETED / FAILED / TIMED_OUT
- 纯内存存储（TaskStore）
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import time
from typing import Any

from app.reasoning.subagents.config import SubAgentConfig
from app.reasoning.subagents.task_store import (
    TaskStore,
    TaskStatus,
    get_task_store,
)

logger = logging.getLogger(__name__)

# 全局线程池（进程级别复用）
_executor: concurrent.futures.ThreadPoolExecutor | None = None


def _get_executor(config: SubAgentConfig) -> concurrent.futures.ThreadPoolExecutor:
    global _executor
    if _executor is None:
        _executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=config.max_workers,
            thread_name_prefix="subagent-",
        )
        logger.info(f"[SubagentExecutor] ThreadPool started, max_workers={config.max_workers}")
    return _executor


def _execute_llm_sync(agent_name: str, prompt: str) -> str:
    """
    同步执行 LLM 调用（在线程池中运行，不阻塞事件循环）。
    """
    from app.core.llm_client import chat
    response = chat(
        prompt=f"你是一个投资研究助手。请简洁地回答：\n\n{prompt}",
        model="minimax2.5",
        temperature=0.1,
        timeout=120,
    )
    return response


def _run_task_sync(
    task_id: str,
    agent_name: str,
    prompt: str,
    config: SubAgentConfig,
    store: TaskStore,
) -> None:
    """
    同步包装：创建新事件循环，在线程池中运行异步任务。
    """
    store.update(task_id, TaskStatus.RUNNING)
    start_time = time.time()

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(
                _run_async(task_id, agent_name, prompt, config, store, start_time)
            )
        finally:
            loop.close()
    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        store.update(task_id, TaskStatus.FAILED, error=error_msg)
        logger.exception(f"[SubagentExecutor] task_id={task_id} executor error")


async def _run_async(
    task_id: str,
    agent_name: str,
    prompt: str,
    config: SubAgentConfig,
    store: TaskStore,
    start_time: float,
) -> None:
    """异步执行 LLM 调用 + 状态更新"""
    try:
        loop = asyncio.get_event_loop()
        result = await asyncio.wait_for(
            loop.run_in_executor(None, lambda: _execute_llm_sync(agent_name, prompt)),
            timeout=config.timeout_seconds,
        )
        elapsed = time.time() - start_time
        store.update(task_id, TaskStatus.COMPLETED, result=result)
        logger.info(f"[SubagentExecutor] task_id={task_id} completed in {elapsed:.1f}s")
    except asyncio.TimeoutError:
        elapsed = time.time() - start_time
        store.update(task_id, TaskStatus.TIMED_OUT, error=f"执行超时（{elapsed:.0f}s）")
        logger.warning(f"[SubagentExecutor] task_id={task_id} timed out after {elapsed:.1f}s")
    except Exception as e:
        elapsed = time.time() - start_time
        error_msg = f"{type(e).__name__}: {e}"
        store.update(task_id, TaskStatus.FAILED, error=error_msg)
        logger.error(f"[SubagentExecutor] task_id={task_id} failed after {elapsed:.1f}s: {error_msg}")


class SubagentExecutor:
    """
    SubAgent 后台执行器。

    特性：
    - ThreadPoolExecutor 并发执行，不阻塞主 agent
    - 状态机追踪：PENDING → RUNNING → COMPLETED / FAILED / TIMED_OUT / CANCELLED
    - 纯内存存储，无外部依赖
    """

    def __init__(self, config: SubAgentConfig | None = None):
        self.config = config or SubAgentConfig()
        self._store = get_task_store()
        self._executor = _get_executor(self.config)

    def submit(self, agent_name: str, prompt: str) -> str:
        """
        提交后台任务，立即返回 task_id。

        任务在 ThreadPoolExecutor 中执行，调用者通过 get_status(task_id) 轮询。
        """
        task_id = self._store.create(agent_name, prompt)
        self._executor.submit(
            _run_task_sync,
            task_id,
            agent_name,
            prompt,
            self.config,
            self._store,
        )
        logger.info(f"[SubagentExecutor] Submitted task_id={task_id}, agent={agent_name}")
        return task_id

    def get_status(self, task_id: str) -> dict | None:
        """获取任务状态（None = 任务不存在）"""
        record = self._store.get(task_id)
        return record.to_dict() if record else None

    def list_running(self) -> list[dict]:
        """列出所有 RUNNING 状态的任务"""
        return [r.to_dict() for r in self._store.list_by_status(TaskStatus.RUNNING)]

    def cancel(self, task_id: str) -> bool:
        """取消任务（如果尚未完成）"""
        record = self._store.get(task_id)
        if record is None:
            return False
        if record.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.TIMED_OUT, TaskStatus.CANCELLED):
            return False
        self._store.update(task_id, TaskStatus.CANCELLED)
        return True


# ── 全局实例 ─────────────────────────────────────────────────────────────

_default_executor: SubagentExecutor | None = None


def get_executor(config: SubAgentConfig | None = None) -> SubagentExecutor:
    global _default_executor
    if _default_executor is None:
        _default_executor = SubagentExecutor(config or SubAgentConfig())
    return _default_executor
