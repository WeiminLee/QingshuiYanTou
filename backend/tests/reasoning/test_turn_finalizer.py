from app.reasoning.runtime.turn_context import AgentTurnContext
from app.reasoning.runtime.turn_finalizer import finalize_agent_turn


class FakeReport:
    report_id = "report-1"
    compliance_declared = True

    def to_dict(self):
        return {"report_id": self.report_id, "trace": "ok"}

    def to_markdown(self):
        return "# report"


async def test_finalize_agent_turn_builds_trace_report_result_and_emits_stream_end():
    emitted = []
    ctx = AgentTurnContext(
        run_id="run-1",
        thread_id="thread-1",
        question="分析光模块",
        background_context="背景",
        graph_context="图谱",
        freshness_context="<data_readiness>\noverall_status=fresh\n</data_readiness>",
    )
    ctx.tool_calls.append({"id": "call-1", "name": "get_kline"})
    ctx.tool_results.append({"id": "call-1", "name": "get_kline", "success": True})
    ctx.turns = 2

    def build_trace_metadata(**kwargs):
        assert kwargs == ctx.to_trace_inputs()
        return {"trace_summary": {"run_id": "run-1"}, "readiness_binding": {"overall_status": "fresh"}}

    def build_analysis_report(**kwargs):
        assert kwargs["topic"] == "分析光模块"
        assert kwargs["raw_analysis"] == "分析内容"
        assert kwargs["turns"] == 2
        assert kwargs["trace"]["trace_summary"]["run_id"] == "run-1"
        return FakeReport()

    async def emit_fn(event_type, payload):
        emitted.append((event_type, payload))

    finalized = await finalize_agent_turn(
        ctx,
        raw_analysis="分析内容",
        build_trace_metadata=build_trace_metadata,
        build_analysis_report=build_analysis_report,
        emit_fn=emit_fn,
        stop_reason=None,
    )

    assert finalized.trace == {"trace_summary": {"run_id": "run-1"}, "readiness_binding": {"overall_status": "fresh"}}
    assert finalized.report is not None
    assert finalized.result["content"] == "分析内容"
    assert finalized.result["trace"] == finalized.trace
    assert finalized.result["thread_id"] == "thread-1"
    assert emitted == [
        (
            "stream_end",
            {
                "report_content": "# report",
                "report_json": {"report_id": "report-1", "trace": "ok"},
                "report_id": "report-1",
                "compliance_passed": True,
                "turns": 2,
                "content": "分析内容",
                "stop_reason": None,
                "run_id": "run-1",
            },
        )
    ]


class CapturingLedgerStore:
    def __init__(self):
        self.records = []

    def append(self, record):
        self.records.append(record)


async def test_finalize_agent_turn_persists_run_ledger_record():
    store = CapturingLedgerStore()
    ctx = AgentTurnContext(run_id="run-ledger", thread_id="thread-ledger", question="复盘")

    await finalize_agent_turn(
        ctx,
        raw_analysis="分析内容",
        build_trace_metadata=lambda **_: {
            "trace_summary": {"run_id": "run-ledger"},
            "readiness_binding": {"overall_status": "fresh"},
            "evidence_refs": [{"id": "DATA_READINESS"}],
            "tool_audit": [{"tool": "get_kline"}],
            "graph_refs": [],
        },
        build_analysis_report=lambda **_: FakeReport(),
        ledger_store=store,
    )

    assert len(store.records) == 1
    record = store.records[0]
    assert record.run_id == "run-ledger"
    assert record.thread_id == "thread-ledger"
    assert record.report_id == "report-1"
    assert record.readiness_binding == {"overall_status": "fresh"}
