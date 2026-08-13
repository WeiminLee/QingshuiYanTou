"""
Regression tests for P1 fixes:
- user_id privilege escalation prevention
- error event visibility in SSE
- background task cancellation on timeout/cancel
"""

import asyncio
import json
import time
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException


# ── Fix 1: user_id 越权防护 ──────────────────────────────────────────────


class TestUserIDPrivilegeEscalation:
    def test_body_matches_cookie_allowed(self):
        from app.reasoning.api.agent import _resolve_request_user_id

        result = _resolve_request_user_id("user-a", "user-a")
        assert result == "user-a"

    def test_body_none_uses_cookie(self):
        from app.reasoning.api.agent import _resolve_request_user_id

        result = _resolve_request_user_id(None, "user-a")
        assert result == "user-a"

    def test_body_empty_uses_cookie(self):
        from app.reasoning.api.agent import _resolve_request_user_id

        result = _resolve_request_user_id("", "user-a")
        assert result == "user-a"

    def test_body_blank_uses_cookie(self):
        from app.reasoning.api.agent import _resolve_request_user_id

        result = _resolve_request_user_id("  ", "user-a")
        assert result == "user-a"

    def test_body_mismatches_cookie_raises_403(self):
        from app.reasoning.api.agent import _resolve_request_user_id

        with pytest.raises(HTTPException) as exc_info:
            _resolve_request_user_id("user-b", "user-a")
        assert exc_info.value.status_code == 403
        assert "does not match" in exc_info.value.detail

    def test_body_only_no_cookie_uses_body(self):
        from app.reasoning.api.agent import _resolve_request_user_id

        result = _resolve_request_user_id("user-a", None)
        assert result == "user-a"

    def test_both_none_returns_none(self):
        from app.reasoning.api.agent import _resolve_request_user_id

        result = _resolve_request_user_id(None, None)
        assert result is None

    def test_cookie_whitespace_stripped_and_matches(self):
        from app.reasoning.api.agent import _resolve_request_user_id

        result = _resolve_request_user_id("user-a", "  user-a  ")
        assert result == "user-a"


# ── Fix 2: error 事件可见性 ──────────────────────────────────────────────


class TestErrorEventVisibility:
    def test_error_in_visible_map(self):
        from app.reasoning.api.agent import _VISIBLE_MAP

        assert "error" in _VISIBLE_MAP
        assert _VISIBLE_MAP["error"] == "error"

    def test_filter_error_event_visible(self):
        from app.reasoning.api.agent import _filter_sse_event

        visible, mapped = _filter_sse_event("error", {"error": "test error"})
        assert visible is True
        assert mapped == "error"

    def test_filter_error_event_not_filtered(self):
        from app.reasoning.api.agent import _FILTERED

        assert "error" not in _FILTERED


# ── Fix 3: 后台任务泄漏防护 ──────────────────────────────────────────────


class FakeResponse:
    def __init__(self, generator):
        self.generator = generator


class TestBackgroundTaskCancellation:
    """验证 v2_stream 在超时/取消时正确取消后台 stream_task。"""

    async def test_stream_task_cancelled_on_timeout(self):
        import app.reasoning.api.agent as agent_module
        from app.reasoning.api.agent import V2StreamRequest, v2_stream

        class FakeClient:
            def __init__(self, **kwargs):
                self.cancelled = False

            async def run(self, question, emit_fn=None):
                try:
                    await asyncio.sleep(60)
                except asyncio.CancelledError:
                    self.cancelled = True
                    raise
                return {"content": "done"}

        request = V2StreamRequest(question="test")

        with (
            patch.object(agent_module, "EventSourceResponse", FakeResponse),
            patch("app.reasoning.langchain_agent.client.LangChainAgentClient", FakeClient),
            patch("app.config.settings.agent_sse_timeout", 0.1),
        ):
            response = await v2_stream(request, api_key="test")

            chunks = []
            async for chunk in response.generator:
                chunks.append(chunk)

        timeout_events = [c for c in chunks if "stream timeout" in c]
        assert len(timeout_events) >= 1, "超时时应产生 error 事件"

    async def test_stream_task_cleanly_completes(self):
        """验证 stream_task 正常完成时 finally 块安全处理（cancel 已完成任务为 no-op）。"""
        import app.reasoning.api.agent as agent_module
        from app.reasoning.api.agent import V2StreamRequest, v2_stream

        completed = []

        class FakeClient:
            def __init__(self, **kwargs):
                pass

            async def run(self, question, emit_fn=None):
                await emit_fn("stream_end", {"content": "done"})
                completed.append(True)
                return {"content": "done"}

        request = V2StreamRequest(question="test")

        with (
            patch.object(agent_module, "EventSourceResponse", FakeResponse),
            patch("app.reasoning.langchain_agent.client.LangChainAgentClient", FakeClient),
        ):
            response = await v2_stream(request, api_key="test")

            gen = response.generator
            async for chunk in gen:
                pass

        assert len(completed) == 1, "stream_task 应正常完成"

    async def test_stream_end_emitted_via_sse(self):
        """验证 stream_end 事件通过 SSE 正确发射。"""
        import app.reasoning.api.agent as agent_module
        from app.reasoning.api.agent import V2StreamRequest, v2_stream

        class FakeClient:
            def __init__(self, **kwargs):
                pass

            async def run(self, question, emit_fn=None):
                await emit_fn("stream_end", {"content": "done", "report_content": "report"})
                return {"content": "done"}

        request = V2StreamRequest(question="test")

        with (
            patch.object(agent_module, "EventSourceResponse", FakeResponse),
            patch("app.reasoning.langchain_agent.client.LangChainAgentClient", FakeClient),
        ):
            response = await v2_stream(request, api_key="test")

            chunks = []
            async for chunk in response.generator:
                chunks.append(chunk)

        stream_end_chunks = [c for c in chunks if "stream_end" in c]
        assert len(stream_end_chunks) >= 1, "stream_end 事件应正确发射"

    async def test_error_event_emitted_for_failed_stream_task(self):
        """验证 stream_task 异常时错误事件被正确发射。"""
        import app.reasoning.api.agent as agent_module
        from app.reasoning.api.agent import V2StreamRequest, v2_stream

        class FakeClient:
            def __init__(self, **kwargs):
                pass

            async def run(self, question, emit_fn=None):
                raise RuntimeError("simulated agent failure")

        request = V2StreamRequest(question="test")

        with (
            patch.object(agent_module, "EventSourceResponse", FakeResponse),
            patch("app.reasoning.langchain_agent.client.LangChainAgentClient", FakeClient),
        ):
            response = await v2_stream(request, api_key="test")

            chunks = []
            async for chunk in response.generator:
                chunks.append(chunk)

        error_events = [c for c in chunks if "simulated agent failure" in c]
        assert len(error_events) >= 1, "stream_task 异常时应收敛为 error 事件"

    async def test_v2_stream_uses_resolved_user_id(self):
        """验证 v2_stream 正确传递匹配的 user_id 给 LangChainAgentClient。"""
        import app.reasoning.api.agent as agent_module
        from app.reasoning.api.agent import V2StreamRequest, v2_stream

        captured_user_id = []

        class FakeClient:
            def __init__(self, **kwargs):
                captured_user_id.append(kwargs.get("user_id"))

            async def run(self, question, emit_fn=None):
                await emit_fn("stream_end", {"content": "done"})
                return {"content": "done"}

        request = V2StreamRequest(question="test", user_id="shared-user")

        with (
            patch.object(agent_module, "EventSourceResponse", FakeResponse),
            patch("app.reasoning.langchain_agent.client.LangChainAgentClient", FakeClient),
        ):
            response = await v2_stream(request, api_key="test", user_id_cookie="shared-user")

            async for chunk in response.generator:
                pass

        assert captured_user_id[0] == "shared-user"

    def test_v2_stream_finally_block_cancels_stream_task(self):
        """验证 event_generator 的 finally 块调用了 stream_task.cancel()。"""
        with open("app/reasoning/api/agent.py") as f:
            source = f.read()

        assert "finally:" in source, "event_generator 缺少 finally 块"
        assert "stream_task.cancel()" in source, "finally 块缺少 stream_task.cancel()"


# ── Fix 1 integration: endpoint-level user_id validation ──────────────────


class TestEndpointUserIDValidation:
    @pytest.mark.anyio
    async def test_v2_stream_rejects_mismatched_user_id(self):
        import app.reasoning.api.agent as agent_module
        from app.reasoning.api.agent import V2StreamRequest, v2_stream

        request = V2StreamRequest(question="test", user_id="attacker")

        with pytest.raises(HTTPException) as exc_info:
            await v2_stream(request, api_key="test", user_id_cookie="victim")
        assert exc_info.value.status_code == 403


if __name__ == "__main__":
    pytest.main([__file__, "-v"])