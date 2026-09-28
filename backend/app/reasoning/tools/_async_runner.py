"""
Async-to-sync helper for LangChain @tool functions.

LangChain @tool 协议要求工具函数同步返回（_run_in_executor 会包一层 thread）。
但底层 DB 服务都是 async。直接在 @tool 函数里 `asyncio.run` 在以下场景会出错：

1. 工具被 LangGraph async runtime 调用时，当前线程已有 running loop → `asyncio.run` 抛错
2. 父协程持有 DB 连接，子线程再创建新 loop 同时占用同一连接池 → 死锁
3. 全局 engine 连接池绑定主 loop，工具临时 loop 复用时 asyncpg 报
   'got Future attached to a different loop'（实测 agent 路径频繁踩坑）

`run_async` 统一处理：
- 执行时在本 loop 内创建 NullPool 临时 engine 并注入 contextvar，
  使 isolated_session() 走该 engine（与主 loop 池零共享）；
- 无 running loop：直接 `asyncio.run`
- 有 running loop：用独立临时线程跑隔离 event loop
"""

from __future__ import annotations

import asyncio
import concurrent.futures
from collections.abc import Awaitable
from typing import TypeVar

T = TypeVar("T")


async def _run_with_isolated_engine[T](coro: Awaitable[T]) -> T:
    """在隔离的 NullPool engine + 一次性 Mongo client 下执行 coro。"""
    from app.core.database import (
        make_nullpool_engine,
        reset_isolated_engine,
        use_isolated_engine,
    )
    from app.core.mongodb import (
        make_isolated_mongo_db,
        reset_isolated_mongo,
        use_isolated_mongo,
    )

    engine = make_nullpool_engine()
    mongo_client, mongo_db = make_isolated_mongo_db()
    tok_sql = use_isolated_engine(engine)
    tok_mongo = use_isolated_mongo(mongo_db)
    try:
        return await coro
    finally:
        reset_isolated_engine(tok_sql)
        reset_isolated_mongo(tok_mongo)
        await engine.dispose()
        mongo_client.close()


def run_async[T](coro: Awaitable[T]) -> T:
    """在同步上下文里执行一个 coroutine 并返回结果。

    Args:
        coro: 已经构造好的 coroutine（每次调用应传新对象）
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_run_with_isolated_engine(coro))

    # 已经在 event loop 中，丢到独立线程跑一个临时 loop
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(
            asyncio.run, _run_with_isolated_engine(coro)
        ).result()
