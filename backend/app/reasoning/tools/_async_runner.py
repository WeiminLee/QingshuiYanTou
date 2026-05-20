"""
Async-to-sync helper for LangChain @tool functions.

LangChain @tool 协议要求工具函数同步返回（_run_in_executor 会包一层 thread）。
但底层 DB 服务都是 async。直接在 @tool 函数里 `asyncio.run` 在以下场景会出错：

1. 工具被 LangGraph async runtime 调用时，当前线程已有 running loop → `asyncio.run` 抛错
2. 父协程持有 DB 连接，子线程再创建新 loop 同时占用同一连接池 → 死锁

`run_async` 统一处理这两种情况：
- 无 running loop：直接 `asyncio.run`
- 有 running loop：用独立的临时线程跑一个隔离的 event loop
"""
from __future__ import annotations

import asyncio
import concurrent.futures
from typing import Awaitable, TypeVar

T = TypeVar("T")


def run_async(coro: Awaitable[T]) -> T:
    """在同步上下文里执行一个 coroutine 并返回结果。

    Args:
        coro: 已经构造好的 coroutine（每次调用应传新对象）
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    # 已经在 event loop 中，丢到独立线程跑一个临时 loop
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()
