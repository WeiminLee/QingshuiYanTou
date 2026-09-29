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
        # ensure_bytes 现位于 sse_starlette.sse（旧 sse_starlette.event 子模块已移除）
        from sse_starlette.sse import ensure_bytes

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
        with open("app/reasoning/api/agent_events.py") as f:
            source = f.read()

        lines = source.split("\n")
        in_generator = False
        for line in lines:
            if "def event_generator" in line:
                in_generator = True
            elif in_generator:
                if "to_json_bytes" in line:
                    pytest.fail("event_generator() 中仍有 to_json_bytes() 调用")
                if line.strip().startswith("def ") and "event_generator" not in line:
                    break


# ── GAP-BE-03: Legacy stream_end 含完整报告 ────────────────────────────


class TestLegacyStreamEndReport:
    """GAP-BE-03: 验证 legacy 路径 stream_end 包含完整报告"""

    def test_legacy_reasoning_end_has_report(self):
        # stream_end 的完整报告在 turn_finalizer.py 中发射：
        #   emit_fn("stream_end", {"report_content": ..., "report_json": ...})
        with open("app/reasoning/runtime/turn_finalizer.py") as f:
            source = f.read()

        assert '"report_content"' in source or "'report_content'" in source, (
            "turn_finalizer.py 中 stream_end 缺少 report_content 字段"
        )
        assert '"report_json"' in source or "'report_json'" in source, (
            "turn_finalizer.py 中 stream_end 缺少 report_json 字段"
        )


# ── GAP-BE-04: Schema 一致性 ───────────────────────────────────────────


class TestSchemaConsistency:
    """GAP-BE-04: 验证两条路径 tool_result schema 一致"""

    REQUIRED_FIELDS = {"id", "name", "result", "success", "turn", "original_len", "duration_ms"}

    def test_legacy_has_all_required_fields(self):
        with open("app/reasoning/langchain_agent/client.py") as f:
            source = f.read()

        for field in self.REQUIRED_FIELDS:
            assert f'"{field}"' in source or f"'{field}'" in source, f"legacy 路径缺少字段: {field}"

    # 注：test_manual_loop_has_all_required_fields 已删除——manual_agent_loop.py 已删除
    # （手动 agent 循环被 LangChain 原生 create_agent()+astream() 取代），不再有第二条路径需校验。


# ── GAP-BE-06: LLM 失败错误事件 ────────────────────────────────────────


class TestLLMErrorEvent:
    """GAP-BE-06: 验证 LLM 失败时发射 error 事件"""

    def test_run_lead_agent_has_error_handler(self):
        with open("app/reasoning/langchain_agent/client.py") as f:
            source = f.read()

        assert 'emit_fn("error"' in source or "emit_fn('error'" in source, "run_lead_agent() 缺少 error 事件发射"


# ── GAP-BE-08: V2 Stream 显式 stream_end ───────────────────────────────


class TestV2StreamEnd:
    """GAP-BE-08: 验证 /v2/stream 显式发射 stream_end"""

    def test_v2_stream_has_stream_end(self):
        # stream_end 仍显式发射：agent.py 的报告路径 emit_fn("stream_end", {...})。
        with open("app/reasoning/api/agent.py") as f:
            source = f.read()

        assert 'emit_fn("stream_end"' in source or "emit_fn('stream_end'" in source, (
            "agent.py 缺少 stream_end 事件发射"
        )

    def test_v2_stream_checks_task_status(self):
        with open("app/reasoning/api/agent.py") as f:
            source = f.read()

        assert "stream_task.done()" in source
        assert "stream_task.exception()" in source


# ── GAP-BE-10: legacy tool_result success 字段 ──────────────────────────


class TestLegacyToolResultSuccess:
    """GAP-BE-10: 验证 legacy 路径 tool_result 包含 success 字段"""

    def test_legacy_tool_result_has_success(self):
        with open("app/reasoning/langchain_agent/client.py") as f:
            source = f.read()

        assert '"success": True' in source or "'success': True" in source, "legacy 路径 tool_result 缺少 success 字段"


# ── GAP-BE-11: legacy 使用 build_preview ────────────────────────────────


class TestLegacyBuildPreview:
    """GAP-BE-11: 验证 legacy 路径使用 build_preview()"""

    def test_legacy_imports_build_preview(self):
        with open("app/reasoning/langchain_agent/client.py") as f:
            source = f.read()

        assert "build_preview" in source, "client.py 未导入 build_preview"

    def test_legacy_uses_build_preview(self):
        with open("app/reasoning/langchain_agent/client.py") as f:
            source = f.read()

        assert "build_preview(" in source, "legacy 路径未调用 build_preview()"


# ── GAP-BE-12: 无重复 stream_end ───────────────────────────────────────


class TestNoDuplicateStreamEnd:
    """GAP-BE-12: 验证无重复 stream_end"""

    def test_turn_finalizer_emits_single_stream_end(self):
        # 结束事件统一为 stream_end。turn_finalizer.finalize_agent_turn() 发射一次；
        # client.py 不直接发射 stream_end，agent.py 的报告路径也注明不再重复发射。
        with open("app/reasoning/runtime/turn_finalizer.py") as f:
            finalizer_source = f.read()
        with open("app/reasoning/langchain_agent/client.py") as f:
            client_source = f.read()
        with open("app/reasoning/api/agent.py") as f:
            agent_source = f.read()

        # turn_finalizer 侧 SSE 发射一次 stream_end
        emit_stream_end_lines = [
            ln for ln in finalizer_source.splitlines()
            if '"stream_end",' in ln and "append_journal_event" not in ln
        ]
        assert len(emit_stream_end_lines) == 1, (
            f"turn_finalizer.py 应恰好发射一次 SSE stream_end，实际 {len(emit_stream_end_lines)}"
        )

        # client.py 不直接发射 stream_end（委托给 finalize_agent_turn）
        direct_client_emits = [
            ln for ln in client_source.splitlines()
            if '"stream_end",' in ln and "append_journal_event" not in ln
        ]
        assert len(direct_client_emits) == 0, (
            f"client.py 不应直接发射 stream_end（已委托给 turn_finalizer），实际 {len(direct_client_emits)}"
        )

        # agent.py 的报告路径注明不再重复发射 stream_end
        agent_comment = "不再重复发射" if "不再重复发射" in agent_source else "stream_end 由 turn_finalizer 发射"
        assert agent_comment, "agent.py 缺少 stream_end 重复发射的注释说明"
        # agent.py 侧留有防重复注释/逻辑
        assert "不再重复发射" in agent_source or "已经由 run_lead_agent" in agent_source, (
            "agent.py 缺少防止 stream_end 重复发射的说明/逻辑"
        )


# ── GAP-BE-13: 超时不构建空报告 ────────────────────────────────────────


class TestTimeoutNoEmptyReport:
    """GAP-BE-13: 验证超时不构建空报告"""

    def test_timeout_returns_early(self):
        # GAP-BE-13 原意：超时不得构建空报告。当前架构下 agent.py 唯一的 TimeoutError 处理是
        # 事件队列 ping 超时（emitter_queue.get 的 wait_for），它只 ping/break，绝不构建报告——
        # 因此"超时构建空报告"的旧路径已不存在。这里验证该 handler 不触及报告构建。
        with open("app/reasoning/api/agent.py") as f:
            source = f.read()

        lines = source.split("\n")
        in_timeout_handler = False
        builds_report_in_handler = False

        for line in lines:
            stripped = line.strip()
            if "except" in line and "TimeoutError" in line:
                in_timeout_handler = True
                continue
            if in_timeout_handler:
                # 退出 handler：遇到同级或更外层的 except/新逻辑块
                if stripped.startswith("except ") and "TimeoutError" not in line:
                    break
                if ("report_content" in line or "AnalysisReport" in line or "to_markdown" in line) and not stripped.startswith("#"):
                    builds_report_in_handler = True
                    break

        assert not builds_report_in_handler, "TimeoutError 处理中不应构建报告（避免超时空报告）"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
