"""
Stream End 生命周期测试

当前架构由 run_lead_agent 发射唯一的 stream_end；
_run_stream_report 只负责把最终结果写入 TaskStateManager，不重复发射。
"""


def test_run_lead_agent_stream_end_has_report_and_trace_fields():
    with open("app/reasoning/langchain_agent/client.py") as f:
        source = f.read()

    assert 'emit_fn(\n                "stream_end"' in source
    assert '"report_content": report.to_markdown()' in source
    assert '"report_json": report.to_dict()' in source
    assert "trace_metadata = _build_trace_metadata(" in source
    assert "trace=trace_metadata" in source


def test_api_stream_report_does_not_emit_duplicate_stream_end():
    with open("app/reasoning/api/agent.py") as f:
        source = f.read()

    run_stream_start = source.index("async def _run_stream_report")
    resume_start = source.index("async def _resume_stream_report")
    run_stream_source = source[run_stream_start:resume_start]

    assert 'emit_fn("stream_end"' not in run_stream_source
    assert '"report_json": report.to_dict()' in run_stream_source
    assert "_apply_result_trace_to_report(report, result)" in run_stream_source


def test_resume_stream_report_includes_report_json_and_trace():
    with open("app/reasoning/api/agent.py") as f:
        source = f.read()

    resume_start = source.index("async def _resume_stream_report")
    timeout_start = source.index("async def _schedule_resume_timeout")
    resume_source = source[resume_start:timeout_start]

    assert 'emit_fn("stream_end"' in resume_source
    assert '"report_json": report.to_dict()' in resume_source
    assert "_apply_result_trace_to_report(report, result)" in resume_source
