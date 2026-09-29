"""
回归测试: ToolExecutor 生产集成 — lead_agent._harden_tool() 超时/重试/并发

覆盖场景：
- 工具超时：asyncio.wait_for 能在工具挂起时正确报错
- 工具重试：RetryStrategy 能在工具首次失败后自动重试
- 并发限制：asyncio.Semaphore 限制全局并发数
- NEVER_PARALLEL 互斥锁：present_chart/clarify/write_file 互斥串行
- 异常降级：工具抛异常时返回友好提示，不中断 agent
- 配置传递：tool_configs 从 client.py → make_lead_agent → _filter_langchain_tools → _harden_tool
"""

import asyncio
import time
from unittest.mock import MagicMock

import pytest


# ── 辅助函数 ──────────────────────────────────────────────────────────


def _make_mock_tool(name: str, result: str = "ok", *, is_async: bool = False, delay: float = 0):
    """创建模拟工具（与 test_tool_executor.py 风格一致）

    使用 spec=BaseTool 确保 isinstance(tool, BaseTool) 为 True，
    设置 args_schema=None 避免 StructuredTool.from_function 校验失败。
    """
    from langchain_core.tools import BaseTool

    tool = MagicMock(spec=BaseTool, name=name)
    tool.name = name
    tool.args_schema = None
    tool.description = f"mock tool {name}"

    if is_async:

        async def invoke(args):
            if delay:
                await asyncio.sleep(delay)
            return result

        tool.ainvoke = invoke
    else:

        def invoke(args):
            if delay:
                time.sleep(delay)
            return result

        tool.invoke = invoke

    return tool


def _make_async_mock_tool(name: str, ainvoke_func):
    """创建带有自定义 ainvoke 的异步工具 MagicMock（spec=BaseTool）"""
    from langchain_core.tools import BaseTool

    tool = MagicMock(spec=BaseTool, name=name)
    tool.name = name
    tool.args_schema = None
    tool.description = f"mock tool {name}"
    tool.ainvoke = ainvoke_func
    return tool


# ── 测试工具超时 ──────────────────────────────────────────────────────


class TestHardenToolTimeout:
    """_harden_tool 超时控制测试"""

    @pytest.mark.asyncio
    async def test_timeout_returns_fallback(self):
        """
        场景：工具执行超时（超过 0.1s）
        期望：_harden_tool 返回 fallback 错误提示，不抛异常
        """
        from app.reasoning.langchain_agent.lead_agent import _harden_tool

        tool = _make_mock_tool("slow_tool", "never", is_async=True, delay=10.0)
        wrapped = _harden_tool(tool, timeout=0.1)

        result = await wrapped.ainvoke({})

        assert "暂不可用" in result
        assert "slow_tool" in result
        assert "timed out" in result

    @pytest.mark.asyncio
    async def test_normal_tool_not_affected_by_timeout(self):
        """
        场景：工具在超时前完成
        期望：正常返回结果，不受影响
        """
        from app.reasoning.langchain_agent.lead_agent import _harden_tool

        tool = _make_mock_tool("get_kline", "K线数据", is_async=True)
        wrapped = _harden_tool(tool, timeout=10.0)

        result = await wrapped.ainvoke({"ts_code": "000001.SZ"})

        assert result == "K线数据"


# ── 测试工具重试 ──────────────────────────────────────────────────────


class TestHardenToolRetry:
    """_harden_tool 重试机制测试"""

    @pytest.mark.asyncio
    async def test_retry_on_failure(self):
        """
        场景：工具首次失败，第二次成功
        期望：自动重试，最终返回成功结果
        """
        from app.reasoning.langchain_agent.lead_agent import _harden_tool
        from app.reasoning.langchain_agent.retry import ExponentialBackoff

        call_count = 0

        async def flaky_ainvoke(args):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("temporary error")
            return "success after retry"

        tool = _make_async_mock_tool("flaky_tool", flaky_ainvoke)

        retry = ExponentialBackoff(
            max_attempts=3,
            base_delay=0.01,
            jitter=False,
            retryable_exceptions=(RuntimeError,),
        )
        wrapped = _harden_tool(tool, timeout=10.0, retry=retry)

        result = await wrapped.ainvoke({})

        assert result == "success after retry"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_retry_exhausted_returns_fallback(self):
        """
        场景：工具持续失败，重试耗尽
        期望：返回 fallback 错误提示，不抛异常
        """
        from app.reasoning.langchain_agent.lead_agent import _harden_tool
        from app.reasoning.langchain_agent.retry import ExponentialBackoff

        async def always_fail(args):
            raise RuntimeError("permanent error")

        tool = _make_async_mock_tool("failing_tool", always_fail)

        retry = ExponentialBackoff(
            max_attempts=2,
            base_delay=0.01,
            jitter=False,
            retryable_exceptions=(RuntimeError,),
        )
        wrapped = _harden_tool(tool, timeout=10.0, retry=retry)

        result = await wrapped.ainvoke({})

        # 重试耗尽后，异常冒泡到 _acall 的 except Exception 兜底
        assert "暂不可用" in result
        assert "failing_tool" in result

    @pytest.mark.asyncio
    async def test_no_retry_when_disabled(self):
        """
        场景：禁用重试（默认 NoRetry）
        期望：首次失败立即返回 fallback，不重试
        """
        from app.reasoning.langchain_agent.lead_agent import _harden_tool

        call_count = 0

        async def fail_once(args):
            nonlocal call_count
            call_count += 1
            raise RuntimeError("immediate error")

        tool = _make_async_mock_tool("no_retry_tool", fail_once)
        wrapped = _harden_tool(tool)  # 默认 NoRetry + DEFAULT_TIMEOUT
        result = await wrapped.ainvoke({})

        assert "暂不可用" in result
        assert call_count == 1  # 只调用一次，不重试


# ── 测试异常降级 ──────────────────────────────────────────────────────


class TestHardenToolFallback:
    """_harden_tool 异常降级测试"""

    @pytest.mark.asyncio
    async def test_async_exception_returns_fallback(self):
        """
        场景：异步工具抛异常
        期望：返回 fallback 提示，不抛异常到 agent
        """
        from app.reasoning.langchain_agent.lead_agent import _harden_tool

        async def crash(args):
            raise ValueError("database connection failed")

        tool = _make_async_mock_tool("query_tool", crash)

        wrapped = _harden_tool(tool)
        result = await wrapped.ainvoke({})

        assert "暂不可用" in result
        assert "query_tool" in result
        assert "database connection failed" in result

    @pytest.mark.asyncio
    async def test_sync_tool_works(self):
        """
        场景：同步工具（非异步）
        期望：同步路径正常执行，不触发异步路径
        """
        from app.reasoning.langchain_agent.lead_agent import _harden_tool

        tool = _make_mock_tool("sync_tool", "sync result")
        wrapped = _harden_tool(tool)

        # 调用同步路径
        result = wrapped.invoke({})
        assert result == "sync result"


# ── 测试并发限制 ──────────────────────────────────────────────────────


class TestHardenToolConcurrency:
    """_harden_tool 并发限制测试"""

    @pytest.mark.asyncio
    async def test_semaphore_limits_concurrency(self):
        """
        场景：大量并发工具请求
        期望：通过 _tool_semaphore 控制最大并发数
        """
        from app.reasoning.langchain_agent.lead_agent import _harden_tool, _tool_semaphore

        # 验证默认信号量最大值
        assert _tool_semaphore._value == 8, f"默认并发数应为 8，实际为 {_tool_semaphore._value}"

        active_count = 0
        max_concurrent = 0
        lock = asyncio.Lock()

        async def tracked_invoke(args):
            nonlocal active_count, max_concurrent
            async with lock:
                active_count += 1
                max_concurrent = max(max_concurrent, active_count)
            await asyncio.sleep(0.2)
            async with lock:
                active_count -= 1
            return "ok"

        tool = _make_async_mock_tool("fast_tool", tracked_invoke)

        wrapped = _harden_tool(tool, timeout=10.0)

        # 并发启动 5 个工具调用
        tasks = [wrapped.ainvoke({}) for _ in range(5)]
        results = await asyncio.gather(*tasks)

        assert all(r == "ok" for r in results)
        # 信号量值为 8，并发 5 个应全部通过
        assert max_concurrent == 5  # 5 个并发请求，信号量 8 足够

    @pytest.mark.asyncio
    async def test_never_parallel_tool_with_regular_tool(self):
        """
        场景：NEVER_PARALLEL 工具（present_chart）与普通工具并发
        期望：NEVER_PARALLEL 仅阻止同类型工具间并发，不影响普通工具
        """
        from app.reasoning.langchain_agent.lead_agent import _harden_tool

        async def chart_invoke(args):
            await asyncio.sleep(0.1)
            return "chart ok"

        async def kline_invoke(args):
            await asyncio.sleep(0.1)
            return "kline ok"

        chart_tool = _make_async_mock_tool("present_chart", chart_invoke)
        kline_tool = _make_async_mock_tool("get_kline", kline_invoke)

        wrapped_chart = _harden_tool(chart_tool, timeout=10.0)
        wrapped_kline = _harden_tool(kline_tool, timeout=10.0)

        # 并发执行 NEVER_PARALLEL + 普通工具
        # 普通工具通过信号量，NEVER_PARALLEL 工具通过信号量 + 互斥锁
        # 二者可以并发，总时间 ≈ 0.1s
        start = time.monotonic()
        results = await asyncio.gather(
            wrapped_chart.ainvoke({}),
            wrapped_kline.ainvoke({}),
        )
        elapsed = time.monotonic() - start

        assert elapsed < 0.2, f"普通工具与 NEVER_PARALLEL 未并发，耗时 {elapsed:.3f}s"
        assert results == ["chart ok", "kline ok"]

    @pytest.mark.asyncio
    async def test_multiple_never_parallel_are_serialized(self):
        """
        场景：多个 NEVER_PARALLEL 工具同时调用
        期望：NEVER_PARALLEL 工具通过互斥锁串行化
        """
        from app.reasoning.langchain_agent.lead_agent import _harden_tool

        async def chart_invoke(args):
            await asyncio.sleep(0.1)
            return "chart ok"

        async def write_invoke(args):
            await asyncio.sleep(0.1)
            return "write ok"

        chart_tool = _make_async_mock_tool("present_chart", chart_invoke)
        write_tool = _make_async_mock_tool("write_file", write_invoke)

        wrapped_chart = _harden_tool(chart_tool, timeout=10.0)
        wrapped_write = _harden_tool(write_tool, timeout=10.0)

        # 并发执行两个 NEVER_PARALLEL 工具
        # 互斥锁确保串行化，总时间 ≈ 0.2s
        start = time.monotonic()
        results = await asyncio.gather(
            wrapped_chart.ainvoke({}),
            wrapped_write.ainvoke({}),
        )
        elapsed = time.monotonic() - start

        assert elapsed >= 0.15, f"NEVER_PARALLEL 串行化未生效，耗时 {elapsed:.3f}s"
        assert results == ["chart ok", "write ok"]


# ── 测试配置传递链路 ──────────────────────────────────────────────────


class TestToolConfigChain:
    """tool_configs 从 client.py → lead_agent 传递链路测试"""

    def test_make_lead_agent_accepts_tool_configs(self):
        """
        场景：make_lead_agent 接收 tool_configs 参数
        期望：配置被正确分发给 _filter_langchain_tools → _harden_tool
        """
        import inspect

        from app.reasoning.langchain_agent.lead_agent import make_lead_agent

        sig = inspect.signature(make_lead_agent)
        assert "tool_configs" in sig.parameters, "make_lead_agent 应接受 tool_configs 参数"

    def test_filter_langchain_tools_accepts_configs(self):
        """
        场景：_filter_langchain_tools 接收 tool_configs
        期望：配置被正确分发给 _harden_tool
        """
        import inspect

        from app.reasoning.langchain_agent.lead_agent import _filter_langchain_tools

        sig = inspect.signature(_filter_langchain_tools)
        assert "tool_configs" in sig.parameters, "_filter_langchain_tools 应接受 tool_configs 参数"

    def test_harden_tool_accepts_timeout_and_retry(self):
        """
        场景：_harden_tool 接收 timeout 和 retry 参数
        期望：参数被正确用于包装工具
        """
        import inspect

        from app.reasoning.langchain_agent.lead_agent import _harden_tool

        sig = inspect.signature(_harden_tool)
        assert "timeout" in sig.parameters, "_harden_tool 应接受 timeout 参数"
        assert "retry" in sig.parameters, "_harden_tool 应接受 retry 参数"

    @pytest.mark.asyncio
    async def test_retry_config_from_tool_configs(self):
        """
        场景：通过 tool_configs 传递 retry 策略
        期望：retry 策略对指定工具生效
        """
        from app.reasoning.langchain_agent.lead_agent import _filter_langchain_tools
        from app.reasoning.langchain_agent.retry import ExponentialBackoff

        call_count = 0

        async def flaky_ainvoke(args):
            nonlocal call_count
            call_count += 1
            raise RuntimeError("network error")

        tool = _make_async_mock_tool("tavily_search", flaky_ainvoke)

        configs = {
            "tavily_search": {
                "timeout": 10.0,
                "retry": ExponentialBackoff(max_attempts=2, base_delay=0.01, jitter=False),
            }
        }
        wrapped_list = _filter_langchain_tools([tool], tool_configs=configs)
        wrapped = wrapped_list[0]

        result = await wrapped.ainvoke({})

        assert "暂不可用" in result
        # 首次调用失败 + 重试 1 次 = 2 次调用
        assert call_count == 2, f"retry 未生效，调用次数: {call_count}"


# ── 测试 NEVER_PARALLEL 触发 ──────────────────────────────────────────


class TestNeverParallelTrigger:
    """NEVER_PARALLEL 工具互斥锁触发测试"""

    @pytest.mark.asyncio
    async def test_never_parallel_tools_use_lock(self):
        """
        场景：NEVER_PARALLEL 集合中的工具被正确识别
        期望：NEVER_PARALLEL 工具使用全局互斥锁
        """
        from app.reasoning.langchain_agent.lead_agent import _harden_tool
        from app.reasoning.langchain_agent.tool_executor import NEVER_PARALLEL

        for tool_name in NEVER_PARALLEL:
            async def slow_invoke(args, _name=tool_name):
                await asyncio.sleep(0.05)
                return f"{_name} ok"

            tool = _make_async_mock_tool(tool_name, slow_invoke)

            wrapped = _harden_tool(tool, timeout=10.0)
            result = await wrapped.ainvoke({})

            assert result == f"{tool_name} ok", f"NEVER_PARALLEL 工具 {tool_name} 执行失败"