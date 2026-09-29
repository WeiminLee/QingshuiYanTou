"""
测试 Phase 2: Retry 模块

参考 hermes-agent agent/retry_utils.py 的 jittered_backoff 实现：
- 指数退避 + 解相关抖动（decorrelated jitter）
- RetryStrategy 抽象基类
- ExponentialBackoff / NoRetry 实现
"""

import asyncio
import time

import pytest


class TestJitteredBackoff:
    """jittered_backoff 核心延迟计算测试"""

    def test_delay_increases_with_attempts(self):
        """
        场景：重试次数增加
        期望：延迟按指数增长（冻结 time_ns 消除随机性）
        """
        from unittest.mock import patch

        from app.reasoning.langchain_agent.retry import jittered_backoff

        # 冻结 time_ns，每次调用返回固定增量值，消除 jitter 随机性
        with patch("app.core.retry.time.time_ns") as mock_ns:
            mock_ns.return_value = 1_000_000_000

            delay1 = jittered_backoff(1, base_delay=1.0, max_delay=60.0)
            delay2 = jittered_backoff(2, base_delay=1.0, max_delay=60.0)
            delay3 = jittered_backoff(3, base_delay=1.0, max_delay=60.0)

        # 延迟应随尝试次数增加（指数退避保证，冻结时间后无 jitter 随机性）
        assert delay2 >= delay1 * 1.5, f"attempt2 延迟应明显大于 attempt1: {delay2} vs {delay1}"
        assert delay3 >= delay2 * 1.5, f"attempt3 延迟应明显大于 attempt2: {delay3} vs {delay2}"

    def test_delay_respects_max(self):
        """
        场景：重试次数超过指数增长上限
        期望：延迟被 cap 到 max_delay
        """
        from app.reasoning.langchain_agent.retry import jittered_backoff

        for attempt in [10, 20, 100]:
            delay = jittered_backoff(attempt, base_delay=1.0, max_delay=30.0)
            assert delay <= 30.0 + 30.0 * 0.5, f"attempt {attempt} delay 应 ≤ max_delay + jitter"

    def test_jitter_produces_different_delays(self):
        """
        场景：同一 attempt 多次调用
        期望：产生不同延迟（jitter 生效）
        """
        from app.reasoning.langchain_agent.retry import jittered_backoff

        delays = [jittered_backoff(3, base_delay=10.0, max_delay=60.0) for _ in range(10)]
        unique_delays = set(round(d, 4) for d in delays)
        assert len(unique_delays) >= 3, f"jitter 应产生不同的延迟值，实际 unique={len(unique_delays)}"

    def test_base_delay_zero_returns_max(self):
        """
        场景：base_delay = 0（防止除零/溢出）
        期望：返回 max_delay（不退避）
        """
        from app.reasoning.langchain_agent.retry import jittered_backoff

        delay = jittered_backoff(1, base_delay=0.0, max_delay=10.0)
        assert delay <= 10.0


class TestRetryStrategyInterface:
    """RetryStrategy 抽象接口测试"""

    def test_exponential_backoff_is_retry_strategy(self):
        """ExponentialBackoff 是 RetryStrategy 的实现"""
        from app.reasoning.langchain_agent.retry import (
            ExponentialBackoff,
            RetryStrategy,
        )

        strategy = ExponentialBackoff()
        assert isinstance(strategy, RetryStrategy)

    def test_no_retry_is_retry_strategy(self):
        """NoRetry 是 RetryStrategy 的实现"""
        from app.reasoning.langchain_agent.retry import NoRetry, RetryStrategy

        strategy = NoRetry()
        assert isinstance(strategy, RetryStrategy)


class TestRetryConfigDefaults:
    """默认配置测试"""

    def test_default_values(self):
        """合理的默认值"""
        from app.reasoning.langchain_agent.retry import ExponentialBackoff

        strategy = ExponentialBackoff()
        assert strategy.max_attempts == 3
        assert strategy.base_delay == 1.0
        assert strategy.max_delay == 60.0
        assert strategy.exponential_base == 2.0
        assert strategy.jitter is True
        assert strategy.retryable_exceptions == (Exception,)


class TestRetryExecute:
    """RetryStrategy.execute() 异步执行测试"""

    async def _run(self, strategy, func):
        """使用 asyncio.run 执行异步测试（兼容 pytest-anyio）"""
        return await strategy.execute(func)

    def test_succeeds_on_first_attempt(self):
        """函数首次调用即成功：直接返回结果"""
        from app.reasoning.langchain_agent.retry import ExponentialBackoff

        strategy = ExponentialBackoff(max_attempts=3, base_delay=10.0, jitter=False)

        async def succeed():
            return "ok"

        result = asyncio.run(self._run(strategy, succeed))
        assert result == "ok"

    def test_retries_on_failure_then_succeeds(self):
        """前两次失败，第三次成功：等待后退后重试"""
        from app.reasoning.langchain_agent.retry import ExponentialBackoff

        strategy = ExponentialBackoff(
            max_attempts=3,
            base_delay=0.05,
            jitter=False,
            retryable_exceptions=(ValueError,),
        )

        call_count = 0

        async def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("temporary error")
            return "success"

        start = time.monotonic()
        result = asyncio.run(self._run(strategy, flaky))
        elapsed = time.monotonic() - start

        assert result == "success"
        assert call_count == 3
        assert elapsed >= 0.08

    def test_stops_after_max_attempts(self):
        """所有调用均失败：达到 max_attempts 后抛出异常"""
        from app.reasoning.langchain_agent.retry import ExponentialBackoff

        strategy = ExponentialBackoff(
            max_attempts=2,
            base_delay=0.01,
            jitter=False,
            retryable_exceptions=(ValueError,),
        )

        async def always_fail():
            raise ValueError("always fails")

        with pytest.raises(ValueError, match="always fails"):
            asyncio.run(self._run(strategy, always_fail))

    def test_non_retryable_exception_does_not_retry(self):
        """不可重试的异常：立即失败，不重试"""
        from app.reasoning.langchain_agent.retry import ExponentialBackoff

        strategy = ExponentialBackoff(
            max_attempts=3,
            base_delay=10.0,
            jitter=False,
            retryable_exceptions=(ValueError,),
        )

        async def bad_error():
            raise TypeError("not retryable")

        start = time.monotonic()
        with pytest.raises(TypeError):
            asyncio.run(self._run(strategy, bad_error))
        elapsed = time.monotonic() - start

        assert elapsed < 0.5

    def test_sync_function_runs_in_thread(self):
        """同步函数：自动在线程池执行，不阻塞事件循环"""
        from app.reasoning.langchain_agent.retry import ExponentialBackoff

        strategy = ExponentialBackoff(max_attempts=1, jitter=False)

        def sync_func():
            return "sync result"

        result = asyncio.run(self._run(strategy, sync_func))
        assert result == "sync result"


class TestDecorrelatedJitter:
    """解相关抖动（decorrelated jitter）特性测试"""

    def test_concurrent_calls_produce_different_delays(self):
        """
        场景：并发调用 jittered_backoff
        期望：不同并发请求产生分散的延迟（避免 thundering herd）
        """
        import concurrent.futures

        from app.reasoning.langchain_agent.retry import jittered_backoff

        def call_backoff():
            return jittered_backoff(5, base_delay=10.0, max_delay=120.0, jitter_ratio=0.5)

        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
            futures = [executor.submit(call_backoff) for _ in range(50)]
            delays = [f.result() for f in concurrent.futures.as_completed(futures)]

        min_d, max_d = min(delays), max(delays)
        spread = max_d - min_d
        assert spread > 0, "并发调用应产生不同的延迟值"
        assert spread / max_d > 0.05, f"延迟分散度过小: {spread:.2f}s / {max_d:.2f}s"


class TestNoRetry:
    """NoRetry 零重试策略测试"""

    def test_no_retry_always_passes_through(self):
        """NoRetry 不重试，立即透传结果"""
        from app.reasoning.langchain_agent.retry import NoRetry

        strategy = NoRetry()

        async def direct():
            return "direct"

        result = asyncio.run(strategy.execute(direct))
        assert result == "direct"

    def test_no_retry_raises_immediately(self):
        """NoRetry 遇到错误立即抛出"""
        from app.reasoning.langchain_agent.retry import NoRetry

        strategy = NoRetry()

        async def fail():
            raise RuntimeError("fail")

        with pytest.raises(RuntimeError, match="fail"):
            asyncio.run(strategy.execute(fail))
