"""
测试 Phase 3: ToolResult 结构化 + 并发执行

覆盖场景：
- ToolResult dataclass 字段验证
- ToolExecutor.execute_single() 单个工具执行
- ToolExecutor.execute_batch() 并发执行（asyncio.gather）
- ToolExecutor.execute_batch() 串行执行（NEVER_PARALLEL 工具存在）
- 超时控制
- 重试机制
- 错误处理（工具不存在、执行异常）
- H4: 工具参数 schema 校验
"""
import asyncio
import pytest
import time
from unittest.mock import MagicMock


# ── Mock 工具工厂 ──────────────────────────────────────────────────


def _make_mock_tool(name: str, result: str, *, is_async: bool = False, delay: float = 0):
    """创建模拟工具"""
    tool = MagicMock()
    tool.name = name

    if is_async:

        async def invoke(args):
            if delay:
                await asyncio.sleep(delay)
            return result

        tool.invoke = invoke
    else:

        def invoke(args):
            if delay:
                time.sleep(delay)
            return result

        tool.invoke = invoke

    return tool


# ── ToolResult 数据类测试 ────────────────────────────────────────


class TestToolResultDataclass:
    """ToolResult dataclass 字段验证"""

    def test_tool_result_fields(self):
        """
        场景：构造完整的 ToolResult
        期望：所有字段正确赋值
        """
        from app.reasoning.langchain_agent.tool_executor import ToolResult

        result = ToolResult(
            tool_name="get_kline",
            success=True,
            result="KDJ 金叉信号",
            duration_ms=150.5,
            attempts=1,
        )

        assert result.tool_name == "get_kline"
        assert result.success is True
        assert result.result == "KDJ 金叉信号"
        assert result.duration_ms == 150.5
        assert result.attempts == 1
        assert result.error is None

    def test_tool_result_error(self):
        """
        场景：工具执行失败
        期望：error 字段有值，success=False
        """
        from app.reasoning.langchain_agent.tool_executor import ToolResult

        result = ToolResult(
            tool_name="get_announcement",
            success=False,
            result="",
            duration_ms=50.0,
            error="Connection timeout",
            attempts=2,
        )

        assert result.success is False
        assert result.error == "Connection timeout"
        assert result.attempts == 2

    def test_tool_result_repr(self):
        """ToolResult 有合理的 repr（方便调试）"""
        from app.reasoning.langchain_agent.tool_executor import ToolResult

        result = ToolResult(
            tool_name="tavily_search",
            success=True,
            result="result content",
            duration_ms=300.0,
            attempts=1,
        )
        r = repr(result)
        assert "tavily_search" in r
        assert "✓" in r  # repr 使用 ✓ 表示 success=True


# ── ToolExecutor 单个执行测试 ──────────────────────────────────────


class TestToolExecutorSingle:
    """ToolExecutor.execute_single() 测试"""

    def test_execute_sync_tool(self):
        """
        场景：执行同步工具
        期望：返回正确结果，无错误
        """
        from app.reasoning.langchain_agent.tool_executor import ToolExecutor

        tool = _make_mock_tool("get_concept_hot", "光模块热度排名第1")
        executor = ToolExecutor(tools=[tool])

        result = asyncio.run(executor.execute_single("get_concept_hot", {}))

        assert result.success is True
        assert result.result == "光模块热度排名第1"
        assert result.tool_name == "get_concept_hot"
        assert result.duration_ms > 0

    def test_execute_async_tool(self):
        """
        场景：执行异步工具
        期望：返回正确结果
        """
        from app.reasoning.langchain_agent.tool_executor import ToolExecutor

        tool = _make_mock_tool("neo4j_traverse", "关系图谱数据", is_async=True)
        executor = ToolExecutor(tools=[tool])

        result = asyncio.run(executor.execute_single("neo4j_traverse", {"code": "300308.SZ"}))

        assert result.success is True
        assert "关系图谱" in result.result

    def test_tool_not_found(self):
        """
        场景：工具不存在
        期望：返回错误，不抛异常
        """
        from app.reasoning.langchain_agent.tool_executor import ToolExecutor

        tool = _make_mock_tool("get_kline", "k线数据")
        executor = ToolExecutor(tools=[tool])

        result = asyncio.run(executor.execute_single("nonexistent_tool", {}))

        assert result.success is False
        assert "not found" in result.error
        assert result.tool_name == "nonexistent_tool"

    def test_tool_exception_returns_error(self):
        """
        场景：工具执行抛异常
        期望：捕获异常，返回 error，不阻断
        """
        from app.reasoning.langchain_agent.tool_executor import ToolExecutor

        tool = MagicMock()
        tool.name = "get_irm"
        tool.invoke.side_effect = RuntimeError("network error")

        executor = ToolExecutor(tools=[tool])
        result = asyncio.run(executor.execute_single("get_irm", {}))

        assert result.success is False
        assert "network error" in result.error
        assert result.tool_name == "get_irm"

    def test_execute_with_args(self):
        """
        场景：传递工具参数
        期望：参数正确传给工具
        """
        from app.reasoning.langchain_agent.tool_executor import ToolExecutor

        captured_args = {}

        tool = MagicMock()
        tool.name = "get_kline"
        tool.invoke.side_effect = lambda args: (captured_args.update(args) or "ok")

        executor = ToolExecutor(tools=[tool])
        asyncio.run(executor.execute_single("get_kline", {"ts_code": "300308.SZ", "freq": "D"}))

        assert captured_args["ts_code"] == "300308.SZ"
        assert captured_args["freq"] == "D"


# ── ToolExecutor 批量执行测试 ──────────────────────────────────────


class TestToolExecutorBatch:
    """ToolExecutor.execute_batch() 测试"""

    def test_batch_parallel_when_safe(self):
        """
        场景：多个只读工具并发
        期望：并发执行，总时间约等于最慢工具
        """
        from app.reasoning.langchain_agent.tool_executor import ToolExecutor

        tool1 = _make_mock_tool("get_concept_hot", "概念热度结果", delay=0.1)
        tool2 = _make_mock_tool("get_market_breadth", "市场宽度结果", delay=0.1)
        tool3 = _make_mock_tool("get_research_report", "研报结果", delay=0.1)
        executor = ToolExecutor(tools=[tool1, tool2, tool3])

        tool_calls = [
            {"name": "get_concept_hot", "args": {}},
            {"name": "get_market_breadth", "args": {}},
            {"name": "get_research_report", "args": {}},
        ]

        start = time.monotonic()
        results = asyncio.run(executor.execute_batch(tool_calls, allow_parallel=True))
        elapsed = time.monotonic() - start

        assert len(results) == 3
        assert all(r.success for r in results)
        # 并发：总时间约等于单个工具时间（0.1s），不应是 3×0.1=0.3s
        assert elapsed < 0.25, f"并发未生效，耗时 {elapsed:.3f}s"

    def test_batch_serial_when_never_parallel(self):
        """
        场景：包含 NEVER_PARALLEL 工具（present_chart）
        期望：串行执行，总时间等于所有工具时间之和
        """
        from app.reasoning.langchain_agent.tool_executor import ToolExecutor

        tool1 = _make_mock_tool("get_kline", "K线数据", delay=0.05)
        tool2 = _make_mock_tool("present_chart", "图表HTML", delay=0.05)
        tool3 = _make_mock_tool("get_concept_hot", "热度", delay=0.05)
        executor = ToolExecutor(tools=[tool1, tool2, tool3])

        tool_calls = [
            {"name": "get_kline", "args": {}},
            {"name": "present_chart", "args": {}},
            {"name": "get_concept_hot", "args": {}},
        ]

        start = time.monotonic()
        results = asyncio.run(executor.execute_batch(tool_calls, allow_parallel=True))
        elapsed = time.monotonic() - start

        # 串行：0.05 + 0.05 + 0.05 = 0.15s
        assert elapsed >= 0.12, f"串行执行时间不足 {elapsed:.3f}s"
        assert len(results) == 3

    def test_batch_allow_parallel_false(self):
        """
        场景：allow_parallel=False
        期望：强制串行执行
        """
        from app.reasoning.langchain_agent.tool_executor import ToolExecutor

        tool1 = _make_mock_tool("get_kline", "K线数据", delay=0.05)
        tool2 = _make_mock_tool("get_concept_hot", "热度数据", delay=0.05)
        executor = ToolExecutor(tools=[tool1, tool2])

        tool_calls = [
            {"name": "get_kline", "args": {}},
            {"name": "get_concept_hot", "args": {}},
        ]

        start = time.monotonic()
        results = asyncio.run(executor.execute_batch(tool_calls, allow_parallel=False))
        elapsed = time.monotonic() - start

        assert len(results) == 2
        assert elapsed >= 0.08

    def test_batch_empty_calls(self):
        """
        场景：tool_calls 为空
        期望：返回空列表，不报错
        """
        from app.reasoning.langchain_agent.tool_executor import ToolExecutor

        tool = _make_mock_tool("get_kline", "k线")
        executor = ToolExecutor(tools=[tool])

        results = asyncio.run(executor.execute_batch([], allow_parallel=True))

        assert results == []

    def test_batch_mixed_success_and_failure(self):
        """
        场景：部分工具成功，部分失败
        期望：成功的返回结果，失败的返回错误，不相互阻塞
        """
        from app.reasoning.langchain_agent.tool_executor import ToolExecutor

        tool_success = _make_mock_tool("get_concept_hot", "热度数据")
        tool_fail = MagicMock()
        tool_fail.name = "get_announcement"
        tool_fail.invoke.side_effect = RuntimeError("API 错误")

        executor = ToolExecutor(tools=[tool_success, tool_fail])

        tool_calls = [
            {"name": "get_concept_hot", "args": {}},
            {"name": "get_announcement", "args": {}},
        ]

        results = asyncio.run(executor.execute_batch(tool_calls, allow_parallel=True))

        assert len(results) == 2
        success_results = [r for r in results if r.success]
        failure_results = [r for r in results if not r.success]

        assert len(success_results) == 1
        assert len(failure_results) == 1
        assert failure_results[0].error is not None


# ── ToolExecutor 超时测试 ─────────────────────────────────────────


class TestToolExecutorTimeout:
    """ToolExecutor 超时控制测试"""

    def test_timeout_kills_slow_tool(self):
        """
        场景：工具执行超时
        期望：返回超时错误，记录错误信息
        """
        from app.reasoning.langchain_agent.tool_executor import ToolExecutor

        tool = _make_mock_tool("slow_tool", "never returns", delay=10.0)
        executor = ToolExecutor(tools=[tool], default_timeout=0.2)

        result = asyncio.run(executor.execute_single("slow_tool", {}))

        assert result.success is False
        assert "timeout" in result.error.lower() or "timed out" in result.error.lower()


# ── ToolExecutor 并发数限制测试 ──────────────────────────────────


class TestToolExecutorConcurrencyLimit:
    """ToolExecutor 并发数限制测试"""

    def test_semaphore_limits_concurrency(self):
        """
        场景：大量工具并发请求
        期望：同时执行的最大并发数受 semaphore 限制
        """
        from app.reasoning.langchain_agent.tool_executor import ToolExecutor

        active_count = 0
        max_concurrent = 0
        lock = asyncio.Lock()

        async def slow_invoke(args):
            nonlocal active_count, max_concurrent
            async with lock:
                active_count += 1
                max_concurrent = max(max_concurrent, active_count)
            await asyncio.sleep(0.2)
            async with lock:
                active_count -= 1
            return "ok"

        tool = MagicMock()
        tool.name = "parallel_tool"
        tool.invoke = slow_invoke

        executor = ToolExecutor(tools=[tool], max_concurrent=3)
        tool_calls = [{"name": "parallel_tool", "args": {}} for _ in range(10)]

        asyncio.run(executor.execute_batch(tool_calls, allow_parallel=True))

        assert max_concurrent <= 3, f"并发数超限: {max_concurrent} > 3"


# ── ToolExecutor 重试测试 ────────────────────────────────────────


class TestToolExecutorRetry:
    """ToolExecutor 重试机制测试"""

    def test_retry_on_failure(self):
        """
        场景：工具首次失败，第二次成功
        期望：自动重试，最终返回成功结果
        """
        from app.reasoning.langchain_agent.retry import ExponentialBackoff
        from app.reasoning.langchain_agent.tool_executor import ToolExecutor

        call_count = 0

        def flaky_invoke(args):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("temporary error")
            return "success after retry"

        tool = MagicMock()
        tool.name = "flaky_tool"
        tool.invoke = flaky_invoke

        retry = ExponentialBackoff(
            max_attempts=3,
            base_delay=0.01,
            jitter=False,
            retryable_exceptions=(RuntimeError,),
        )
        executor = ToolExecutor(tools=[tool], default_retry=retry)

        result = asyncio.run(executor.execute_single("flaky_tool", {}))

        assert result.success is True
        assert "success after retry" in result.result
        assert result.attempts == 2

    def test_no_retry_when_disabled(self):
        """
        场景：禁用重试（NoRetry）
        期望：首次失败立即返回，不重试
        """
        from app.reasoning.langchain_agent.retry import NoRetry
        from app.reasoning.langchain_agent.tool_executor import ToolExecutor

        call_count = 0

        def fail_once(args):
            nonlocal call_count
            call_count += 1
            raise RuntimeError("permanent error")

        tool = MagicMock()
        tool.name = "failing_tool"
        tool.invoke = fail_once

        executor = ToolExecutor(tools=[tool], default_retry=NoRetry())

        result = asyncio.run(executor.execute_single("failing_tool", {}))

        assert result.success is False
        assert call_count == 1
        assert result.attempts == 1


# ── SSE 截断测试 ─────────────────────────────────────────────────


class TestSSEResultTruncation:
    """SSE 事件结果截断测试"""

    def test_result_truncation(self):
        """
        场景：工具返回超长结果
        期望：SSE 安全截断到指定长度
        """
        from app.reasoning.langchain_agent.tool_executor import ToolResult

        long_content = "x" * 10000

        result = ToolResult(
            tool_name="get_research_report",
            success=True,
            result=long_content,
            duration_ms=500.0,
        )

        sse_content = result.truncate_for_sse(max_length=2000)
        assert len(sse_content) <= 2000


# ── H4: 工具参数 schema 校验 ─────────────────────────────────────


class TestToolArgValidation:
    """H4: execute_single 参数校验测试"""

    def _make_schema_tool(self, param_schema: dict, required: list[str] | None = None, result: str = "ok"):
        """创建带 get_meta schema 的模拟工具"""
        from unittest.mock import MagicMock

        tool = MagicMock()
        tool.name = "schema_tool"

        def get_meta():
            return {
                "type": "function",
                "function": {
                    "name": "schema_tool",
                    "description": "a test tool",
                    "parameters": {
                        "type": "object",
                        "properties": param_schema,
                        **({"required": required} if required is not None else {}),
                    },
                },
            }

        tool.get_meta = get_meta
        tool.invoke = lambda args: result
        return tool

    def test_missing_required_param_returns_error(self):
        """
        场景：必填参数缺失
        期望：返回 success=False，error 包含缺失参数名
        """
        from app.reasoning.langchain_agent.tool_executor import ToolExecutor

        tool = self._make_schema_tool(
            {
                "query": {"type": "string", "description": "查询文本"},
                "ts_code": {"type": "string", "description": "股票代码"},
            },
            required=["query", "ts_code"],
            result="result",
        )
        executor = ToolExecutor(tools=[tool])

        result = asyncio.run(executor.execute_single("schema_tool", {}))

        assert result.success is False
        assert "Missing required parameter" in result.error
        assert "query" in result.error
        assert result.attempts == 1

    def test_type_mismatch_returns_error(self):
        """
        场景：参数类型不匹配（如 string 传 int）
        期望：返回 success=False，error 包含参数名和期望类型
        """
        from app.reasoning.langchain_agent.tool_executor import ToolExecutor

        tool = self._make_schema_tool(
            {
                "query": {"type": "string", "description": "查询文本"},
                "top_n": {"type": "integer", "description": "返回数量"},
            },
            required=["query", "top_n"],
            result="result",
        )
        executor = ToolExecutor(tools=[tool])

        result = asyncio.run(
            executor.execute_single("schema_tool", {"query": 123, "top_n": "not_an_int"})
        )

        assert result.success is False
        assert "Invalid type for" in result.error

    def test_valid_args_proceed_normally(self):
        """
        场景：参数符合 schema
        期望：正常执行，返回成功结果
        """
        from app.reasoning.langchain_agent.tool_executor import ToolExecutor

        captured = {}

        def capture_invoke(args):
            captured.update(args)
            return "success"

        tool = self._make_schema_tool(
            {
                "query": {"type": "string", "description": "查询文本"},
                "top_n": {"type": "integer", "description": "返回数量"},
            },
            required=["query"],
        )
        tool.invoke = capture_invoke
        executor = ToolExecutor(tools=[tool])

        result = asyncio.run(
            executor.execute_single("schema_tool", {"query": "光模块", "top_n": 5})
        )

        assert result.success is True
        assert captured["query"] == "光模块"
        assert captured["top_n"] == 5

    def test_extra_unknown_params_ignored(self):
        """
        场景：传入 schema 中未定义的额外参数
        期望：忽略额外参数，正常执行（LLM 可能传多余参数）
        """
        from app.reasoning.langchain_agent.tool_executor import ToolExecutor

        tool = self._make_schema_tool(
            {"query": {"type": "string", "description": "查询文本"}},
            required=["query"],
            result="ok",
        )
        executor = ToolExecutor(tools=[tool])

        result = asyncio.run(
            executor.execute_single(
                "schema_tool", {"query": "光模块", "unknown_param": 999, "another": True}
            )
        )

        assert result.success is True
        assert result.error is None

    def test_no_get_meta_means_no_validation(self):
        """
        场景：工具没有 get_meta 方法
        期望：跳过校验，正常执行
        """
        from app.reasoning.langchain_agent.tool_executor import ToolExecutor
        from unittest.mock import MagicMock

        tool = MagicMock()
        tool.name = "no_meta_tool"
        tool.invoke = lambda args: "ok"

        executor = ToolExecutor(tools=[tool])
        result = asyncio.run(executor.execute_single("no_meta_tool", {}))

        assert result.success is True

    def test_integer_and_number_type_validation(self):
        """
        场景：验证 number 和 integer 类型都能正确校验
        期望：float 匹配 number，int 匹配 integer，bool 不匹配两者
        """
        from app.reasoning.langchain_agent.tool_executor import _check_type

        assert _check_type(42, "integer") is True
        assert _check_type(3.14, "number") is True
        assert _check_type(True, "integer") is False
        assert _check_type(False, "number") is False
        assert _check_type("42", "integer") is False

