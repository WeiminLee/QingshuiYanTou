"""
Retry 模块 — 指数退避重试策略

核心：
- jittered_backoff() — 指数退避 + 解相关抖动（decorrelated jitter）
- RetryStrategy — 抽象基类
- ExponentialBackoff — 可配置的重试策略
- NoRetry — 零重试（透传）

参考 hermes-agent agent/retry_utils.py：
- jittered_backoff 防止 thundering herd
- 每次调用使用 time_ns() ^ counter 种子避免同批次请求同步重试
"""

from __future__ import annotations

import asyncio
import logging
import random
import threading
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

# ── Jittered Backoff ─────────────────────────────────────────────────────────

_jitter_counter = 0
_jitter_lock = threading.Lock()


def jittered_backoff(
    attempt: int,
    *,
    base_delay: float = 5.0,
    max_delay: float = 120.0,
    jitter_ratio: float = 0.5,
) -> float:
    """
    计算带解相关抖动的指数退避延迟。

    使用全局计数器 + time_ns() 生成唯一种子，
    避免同批次并发请求在同一时刻重试（thundering herd）。

    Args:
        attempt: 重试次数（从 1 开始）
        base_delay: 首次重试的基础延迟（秒）
        max_delay: 延迟上限（秒）
        jitter_ratio: 抖动幅度比例（0.5 表示在 [0, 0.5*delay] 范围添加随机抖动）

    Returns:
        退避延迟（秒），范围 [base_delay, max_delay + max_delay*jitter_ratio]
    """
    global _jitter_counter
    with _jitter_lock:
        _jitter_counter += 1
        tick = _jitter_counter

    exponent = max(0, attempt - 1)
    if exponent >= 63 or base_delay <= 0:
        return max_delay

    delay = min(base_delay * (2**exponent), max_delay)

    # 解相关种子：time_ns() ^ (counter * golden_ratio)
    seed = (time.time_ns() ^ int(tick * 0x9E3779B9)) & 0xFFFFFFFF
    rng = random.Random(seed)
    jitter = rng.uniform(0, jitter_ratio * delay)

    return delay + jitter


# ── Retry Strategy ──────────────────────────────────────────────────────────


class RetryStrategy(ABC):
    """
    重试策略抽象基类。

    使用方式：
        strategy = ExponentialBackoff(max_attempts=3, base_delay=1.0)
        result = await strategy.execute(lambda: risky_io())
    """

    @abstractmethod
    async def execute(self, func: Callable[..., T]) -> T: ...

    def _is_async(self, func: Callable) -> bool:
        return asyncio.iscoroutinefunction(func)


class ExponentialBackoff(RetryStrategy):
    """
    指数退避重试策略。

    特性：
    - 指数退避：delay = min(base * 2^(attempt-1), max_delay)
    - 解相关抖动：避免 thundering herd
    - 可配置可重试异常类型
    - 同步函数自动在线程池执行（不阻塞事件循环）
    """

    def __init__(
        self,
        max_attempts: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        exponential_base: float = 2.0,
        jitter: bool = True,
        retryable_exceptions: tuple[type[Exception], ...] = (Exception,),
    ):
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.jitter = jitter
        self.retryable_exceptions = retryable_exceptions

    def _get_delay(self, attempt: int) -> float:
        if not self.jitter:
            exponent = max(0, attempt - 1)
            return min(self.base_delay * (self.exponential_base**exponent), self.max_delay)
        return jittered_backoff(
            attempt,
            base_delay=self.base_delay,
            max_delay=self.max_delay,
        )

    async def execute(self, func: Callable[..., T]) -> T:
        last_exc: Exception | None = None

        for attempt in range(1, self.max_attempts + 1):
            try:
                if self._is_async(func):
                    return await func()
                else:
                    return await asyncio.to_thread(func)
            except self.retryable_exceptions as e:
                last_exc = e
                if attempt >= self.max_attempts:
                    raise

                delay = self._get_delay(attempt)
                logger.warning(
                    f"[Retry] attempt {attempt}/{self.max_attempts} failed: {e}. Retrying in {delay:.2f}s..."
                )
                await asyncio.sleep(delay)

        if last_exc:
            raise last_exc
        raise RuntimeError("ExponentialBackoff exhausted all attempts")


class NoRetry(RetryStrategy):
    """
    零重试策略 — 立即透传结果或异常。

    用途：
    - 幂等性不保证的操作
    - 已在其他层级处理重试
    - 测试场景
    """

    async def execute(self, func: Callable[..., T]) -> T:
        if self._is_async(func):
            return await func()
        else:
            return await asyncio.to_thread(func)
