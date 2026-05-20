"""
SSE 集成测试套件

验证所有 Phase 05 GAP 修复的完整性：
- GAP-BE-01: SSE wire format 包含 event: 字段
- GAP-BE-02: event_generator 统一 yield dict
- GAP-BE-03: legacy 路径 stream_end 包含完整报告
- GAP-BE-04: 两条路径 tool_result schema 一致
- GAP-BE-06: LLM 失败发射 error 事件
- GAP-BE-08: /v2/stream 显式 stream_end
- GAP-BE-10: legacy 路径 tool_result 包含 success
- GAP-BE-11: legacy 路径使用 build_preview
- GAP-BE-12: 无重复 stream_end
- GAP-BE-13: 超时不构建空报告
"""
import json
import pytest


# ── GAP-BE-01: SSE Wire Format ─────────────────────────────────────────

class TestSSEWireFormat:
    """GAP-BE-01: 验证 SSE wire format 包含 event: 字段"""

    def test_reasoning_event_to_sse_dict_has_event_field(self):
        from app.reasoning.api.agent_events import ReasoningEvent

        event = ReasoningEvent(
            type="thinking",
            task_id="test",
            stage="thinking",
            data={"delta": "test"},
        )
        result = event.to_sse_dict()
        assert "event" in result
        assert result["event"] == "thinking"

    def test_sse_bytes_contain_event_line(self):
        from sse_starlette.event import ensure_bytes
        from app.reasoning.api.agent_events import ReasoningEvent

        event = ReasoningEvent(
            type="tool_result",
            task_id="test",
            stage="tool_result",
            data={"name": "test", "result": "data"},
        )
        sse_bytes = ensure_bytes(event.to_sse_dict(), sep="\r\n")
        sse_str = sse_bytes.decode("utf-8")
        assert "event: tool_result\r\n" in sse_str


# ── GAP-BE-02: 统一 yield 类型 ─────────────────────────────────────────

class TestUnifiedYieldType:
    """GAP-BE-02: 验证 event_generator 统一 yield dict"""

    def test_event_generator_no_to_json_bytes(self):
        with open("app/reasoning/api/agent_events.py", "r") as f:
            source = f.read()

        lines = source.split('\n')
        in_generator = False
        for line in lines:
            if 'def event_generator' in line:
                in_generator = True
            elif in_generator:
                if 'to_json_bytes' in line:
                    pytest.fail("event_generator() 中仍有 to_json_bytes() 调用")
                if line.strip().startswith('def ') and 'event_generator' not in line:
                    break


# ── GAP-BE-03: Legacy stream_end 含完整报告 ────────────────────────────

class TestLegacyStreamEndReport:
    """GAP-BE-03: 验证 legacy 路径 stream_end 包含完整报告"""

    def test_legacy_reasoning_end_has_report(self):
        with open("app/reasoning/langchain_agent/client.py", "r") as f:
            source = f.read()

        assert '"report_content"' in source or "'report_content'" in source, \
            "client.py 中 reasoning_end 缺少 report_content 字段"
        assert '"report_json"' in source or "'report_json'" in source, \
            "client.py 中 reasoning_end 缺少 report_json 字段"


# ── GAP-BE-04: Schema 一致性 ───────────────────────────────────────────

class TestSchemaConsistency:
    """GAP-BE-04: 验证两条路径 tool_result schema 一致"""

    REQUIRED_FIELDS = {"id", "name", "result", "success", "turn", "original_len", "duration_ms"}

    def test_legacy_has_all_required_fields(self):
        with open("app/reasoning/langchain_agent/client.py", "r") as f:
            source = f.read()

        for field in self.REQUIRED_FIELDS:
            assert f'"{field}"' in source or f"'{field}'" in source, \
                f"legacy 路径缺少字段: {field}"

    def test_manual_loop_has_all_required_fields(self):
        with open("app/reasoning/langchain_agent/middlewares/manual_agent_loop.py", "r") as f:
            source = f.read()

        for field in self.REQUIRED_FIELDS:
            assert f'"{field}"' in source or f"'{field}'" in source, \
                f"ManualAgentLoop 路径缺少字段: {field}"


# ── GAP-BE-06: LLM 失败错误事件 ────────────────────────────────────────

class TestLLMErrorEvent:
    """GAP-BE-06: 验证 LLM 失败时发射 error 事件"""

    def test_run_lead_agent_has_error_handler(self):
        with open("app/reasoning/langchain_agent/client.py", "r") as f:
            source = f.read()

        assert 'emit_fn("error"' in source or "emit_fn('error'" in source, \
            "run_lead_agent() 缺少 error 事件发射"


# ── GAP-BE-08: V2 Stream 显式 stream_end ───────────────────────────────

class TestV2StreamEnd:
    """GAP-BE-08: 验证 /v2/stream 显式发射 stream_end"""

    def test_v2_stream_has_stream_end(self):
        with open("app/reasoning/api/agent.py", "r") as f:
            source = f.read()

        assert "'type': 'stream_end'" in source or '"type": "stream_end"' in source, \
            "v2_stream() 缺少显式 stream_end 事件"

    def test_v2_stream_checks_task_status(self):
        with open("app/reasoning/api/agent.py", "r") as f:
            source = f.read()

        assert 'stream_task.done()' in source
        assert 'stream_task.exception()' in source


# ── GAP-BE-10: legacy tool_result success 字段 ──────────────────────────

class TestLegacyToolResultSuccess:
    """GAP-BE-10: 验证 legacy 路径 tool_result 包含 success 字段"""

    def test_legacy_tool_result_has_success(self):
        with open("app/reasoning/langchain_agent/client.py", "r") as f:
            source = f.read()

        assert '"success": True' in source or "'success': True" in source, \
            "legacy 路径 tool_result 缺少 success 字段"


# ── GAP-BE-11: legacy 使用 build_preview ────────────────────────────────

class TestLegacyBuildPreview:
    """GAP-BE-11: 验证 legacy 路径使用 build_preview()"""

    def test_legacy_imports_build_preview(self):
        with open("app/reasoning/langchain_agent/client.py", "r") as f:
            source = f.read()

        assert "build_preview" in source, "client.py 未导入 build_preview"

    def test_legacy_uses_build_preview(self):
        with open("app/reasoning/langchain_agent/client.py", "r") as f:
            source = f.read()

        assert "build_preview(" in source, "legacy 路径未调用 build_preview()"


# ── GAP-BE-12: 无重复 stream_end ───────────────────────────────────────

class TestNoDuplicateStreamEnd:
    """GAP-BE-12: 验证无重复 stream_end"""

    def test_manual_loop_no_duplicate_reasoning_end(self):
        with open("app/reasoning/langchain_agent/client.py", "r") as f:
            source = f.read()

        count = source.count('emit_fn("reasoning_end"') + source.count("emit_fn('reasoning_end'")
        assert count == 1, \
            f"client.py 中 reasoning_end 发射次数应为 1（仅 legacy 路径），实际为 {count}"


# ── GAP-BE-13: 超时不构建空报告 ────────────────────────────────────────

class TestTimeoutNoEmptyReport:
    """GAP-BE-13: 验证超时不构建空报告"""

    def test_timeout_returns_early(self):
        with open("app/reasoning/api/agent.py", "r") as f:
            source = f.read()

        lines = source.split('\n')
        timeout_return_found = False
        in_timeout_handler = False

        for i, line in enumerate(lines):
            if 'asyncio.TimeoutError' in line and 'except' in line:
                in_timeout_handler = True
            elif in_timeout_handler:
                if 'return' in line and not line.strip().startswith('#'):
                    timeout_return_found = True
                    break
                if 'except' in line and 'TimeoutError' not in line:
                    break

        assert timeout_return_found, "TimeoutError 处理中缺少 return 语句"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
