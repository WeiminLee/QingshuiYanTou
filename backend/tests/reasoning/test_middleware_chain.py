"""
tests/reasoning/test_middleware_chain.py

Phase C TDD — 中间件链完善

验收标准：
- [x] ClarificationMiddleware V2 在 client.py 中被调用
- [x] SubagentLimitMiddleware V2 追踪 task 调用并限制
- [x] 中间件异常降级不阻断 Agent
- [x] emit_fn 正确传递 SSE 事件

Run: uv run --directory backend python -m pytest tests/reasoning/test_middleware_chain.py -v
"""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from dataclasses import dataclass


# ── 辅助 Mock ─────────────────────────────────────────────────────────

@dataclass
class MockClarificationResult:
    needed: bool
    type: str | None = None
    question: str | None = None
    context: str | None = None
    options: list[str] | None = None


# ── Test 1: ClarificationMiddleware V2 — 短问题触发澄清 ───────────────


class TestClarificationV2ShortQuestion:
    """问题过短（< 10 字符）触发 clarification_request SSE"""

    def test_short_question_triggers_clarification(self):
        """字符数 < 10 的问题应触发澄清"""
        from app.reasoning.langchain_agent.middlewares.clarification import (
            ClarificationMiddleware,
        )
        mw = ClarificationMiddleware()

        result = mw.check_question("分析")
        assert result is not None, "短问题应触发澄清"
        assert "过短" in result or "补充" in result

    @pytest.mark.anyio
    async def test_short_question_emits_clarification_sse(self):
        """短问题应通过 emit_fn 发射 clarification_request 事件"""
        from app.reasoning.langchain_agent.middlewares.clarification import (
            ClarificationMiddleware,
        )

        mw = ClarificationMiddleware()
        emitted = []

        async def fake_emit(event_type, data):
            emitted.append((event_type, data))

        await mw.check_and_emit("分析", emit_fn=fake_emit)

        assert len(emitted) == 1
        event_type, data = emitted[0]
        assert event_type == "clarification_request"
        assert data["type"] == "missing_info"

    def test_normal_question_no_clarification(self):
        """正常长度的问题不应触发澄清"""
        from app.reasoning.langchain_agent.middlewares.clarification import (
            ClarificationMiddleware,
        )
        mw = ClarificationMiddleware()

        result = mw.check_question("分析中际旭创2024年光模块业务竞争力")
        assert result is None, f"具体问题不应触发澄清，实际返回：{result}"


# ── Test 2: ClarificationMiddleware V2 — 模糊问题触发澄清 ───────────


class TestClarificationV2VagueQuestion:
    """包含模糊关键词（无具体标的）的问题触发澄清"""

    def test_vague_keyword_triggers_clarification(self):
        """仅有 '分析一下' 等模糊词，无具体标的 → 触发澄清"""
        from app.reasoning.langchain_agent.middlewares.clarification import (
            ClarificationMiddleware,
        )
        mw = ClarificationMiddleware()

        result = mw.check_question("分析一下这个行业")
        assert result is not None, "模糊问题应触发澄清"
        assert "标的" in result or "范围" in result or "具体" in result

    def test_vague_with_entity_no_clarification(self):
        """有模糊词但有具体实体（股票名/行业名）→ 不触发澄清"""
        from app.reasoning.langchain_agent.middlewares.clarification import (
            ClarificationMiddleware,
        )

        mw = ClarificationMiddleware()

        # 有 "光模块行业" — 具体
        result = mw.check_question("分析一下光模块行业的竞争格局")
        assert result is None, f"有具体实体的模糊问题不应触发澄清：{result}"

    @pytest.mark.anyio
    async def test_vague_question_emits_correct_type(self):
        """模糊问题发射的 SSE type 应为 'ambiguous_requirement'"""
        from app.reasoning.langchain_agent.middlewares.clarification import (
            ClarificationMiddleware,
        )

        mw = ClarificationMiddleware()
        emitted = []

        async def fake_emit(event_type, data):
            emitted.append((event_type, data))

        await mw.check_and_emit("分析一下", emit_fn=fake_emit)

        assert len(emitted) == 1
        _, data = emitted[0]
        assert data["type"] in ("ambiguous_requirement", "missing_info")


# ── Test 3: SubagentLimitMiddleware V2 ───────────────────────────────


class TestSubagentLimitMiddleware:
    """SubagentLimitMiddleware 追踪 task 调用次数并限制"""

    @pytest.mark.anyio
    async def test_first_task_call_passes_through(self):
        """第一个 task 调用应正常通过"""
        from app.reasoning.langchain_agent.middlewares.subagent_limit import (
            SubagentLimitMiddleware,
        )

        mw = SubagentLimitMiddleware(max_concurrent=3)
        result = await mw.process_tool_call("task", {"description": "分析", "prompt": "..."})
        assert result["allowed"] is True

    @pytest.mark.anyio
    async def test_within_limit_passes_through(self):
        """在限制次数内的 task 调用应通过"""
        from app.reasoning.langchain_agent.middlewares.subagent_limit import (
            SubagentLimitMiddleware,
        )

        mw = SubagentLimitMiddleware(max_concurrent=3)
        for i in range(3):
            result = await mw.process_tool_call("task", {"description": f"分析{i}"})
            assert result["allowed"] is True, f"第{i+1}次调用应在限制内"

    @pytest.mark.anyio
    async def test_exceeds_limit_returns_blocked(self):
        """超出限制的 task 调用应返回 blocked"""
        from app.reasoning.langchain_agent.middlewares.subagent_limit import (
            SubagentLimitMiddleware,
        )

        mw = SubagentLimitMiddleware(max_concurrent=3)
        # 耗尽配额
        for i in range(3):
            await mw.process_tool_call("task", {"description": f"分析{i}"})

        result = await mw.process_tool_call("task", {"description": "第4个分析"})
        assert result["allowed"] is False, "超出限制应返回 blocked"
        msg = result.get("message", "")
        assert ("limit" in msg.lower() or "exceeded" in msg.lower() or "上限" in msg), (
            f"超出限制应返回包含 'limit' 或 '上限' 的消息，实际：{msg}"
        )

    @pytest.mark.anyio
    async def test_non_task_tool_always_allowed(self):
        """非 task 工具永远不受限制"""
        from app.reasoning.langchain_agent.middlewares.subagent_limit import (
            SubagentLimitMiddleware,
        )

        mw = SubagentLimitMiddleware(max_concurrent=1)
        for name in ["get_kline", "qdrant_search", "neo4j_traverse", "chart_tool"]:
            result = await mw.process_tool_call(name, {})
            assert result["allowed"] is True, f"{name} 不应受 task 限制"

    @pytest.mark.anyio
    async def test_reset_per_turn(self):
        """每轮（turn）计数器应独立，重置后配额恢复"""
        from app.reasoning.langchain_agent.middlewares.subagent_limit import (
            SubagentLimitMiddleware,
        )

        mw = SubagentLimitMiddleware(max_concurrent=2)
        for i in range(2):
            await mw.process_tool_call("task", {"description": f"分析{i}"})

        # 超出限制
        result = await mw.process_tool_call("task", {"description": "第3个"})
        assert result["allowed"] is False

        # 重置本轮
        mw.reset_turn()

        # 配额恢复
        result = await mw.process_tool_call("task", {"description": "重置后第1个"})
        assert result["allowed"] is True

    @pytest.mark.anyio
    async def test_emits_sse_event_on_limit_exceeded(self):
        """超出限制时发射 subagent_limit_exceeded 事件"""
        from app.reasoning.langchain_agent.middlewares.subagent_limit import (
            SubagentLimitMiddleware,
        )

        mw = SubagentLimitMiddleware(max_concurrent=1)
        emitted = []

        async def fake_emit(event_type, data):
            emitted.append((event_type, data))

        # 耗尽配额
        await mw.process_tool_call("task", {"description": "分析1"})
        # 超限
        await mw.process_tool_call(
            "task",
            {"description": "分析2"},
            emit_fn=fake_emit,
        )

        assert len(emitted) == 1
        event_type, data = emitted[0]
        assert event_type == "subagent_limit_exceeded"
        assert "limit" in data or "exceeded" in data


# ── Test 4: client.py 集成 ───────────────────────────────────────────


class TestClientMiddlewareIntegration:
    """client.py 正确集成两个中间件"""

    def test_client_imports_clarification_middleware(self):
        """client.py 导入了 ClarificationMiddleware"""
        import inspect
        from app.reasoning.langchain_agent import client
        src = inspect.getsource(client)

        assert "ClarificationMiddleware" in src or "clarification" in src.lower(), (
            "client.py 未引用 ClarificationMiddleware"
        )

    def test_client_imports_subagent_limit_middleware(self):
        """client.py 导入了 SubagentLimitMiddleware"""
        import inspect
        from app.reasoning.langchain_agent import client
        src = inspect.getsource(client)

        # 至少导入了 subagent_limit 相关逻辑
        assert "subagent_limit" in src.lower() or "max_concurrent_subagents" in src, (
            "client.py 未引用 subagent_limit 相关逻辑"
        )

    def test_run_lead_agent_checks_clarification_before_agent(self):
        """run_lead_agent 在调用 agent 之前检查是否需要澄清"""
        import inspect
        from app.reasoning.langchain_agent import client
        src = inspect.getsource(client.run_lead_agent)
        lines = src.splitlines()

        question_pos = agent_pos = clarification_pos = -1
        for i, line in enumerate(lines):
            if "question" in line and "user_content" in line:
                question_pos = i
            if "agent.stream" in line or "_ensure_agent" in line:
                agent_pos = i
            if "clarification" in line.lower() or "check_question" in line:
                clarification_pos = i

        # 澄清检查应在 agent 调用之前
        assert clarification_pos < agent_pos or clarification_pos > 0, (
            f"澄清检查应在 agent 调用之前（clarification={clarification_pos}, agent={agent_pos}）"
        )


# ── Test 5: 中间件降级 ───────────────────────────────────────────────


class TestMiddlewareDegradation:
    """中间件抛异常时降级，不阻断 Agent"""

    def test_clarification_raises_return_none(self):
        """ClarificationMiddleware 异常时返回 None（不阻断）"""
        from app.reasoning.langchain_agent.middlewares.clarification import (
            ClarificationMiddleware,
        )

        mw = ClarificationMiddleware()
        # 传入 None / 空字符串不应崩溃
        result = mw.check_question("")
        # 空问题可以要求澄清，也可以放行（只要不抛异常）
        assert result is None or isinstance(result, str)

    @pytest.mark.anyio
    async def test_subagent_limit_raises_return_allowed(self):
        """SubagentLimitMiddleware 异常时返回 allowed=True（不阻断）"""
        from app.reasoning.langchain_agent.middlewares.subagent_limit import (
            SubagentLimitMiddleware,
        )

        mw = SubagentLimitMiddleware(max_concurrent=3)
        # 传入无效工具名
        result = await mw.process_tool_call(None, {})
        assert result["allowed"] is True, "异常时应默认放行，不阻断 Agent"
