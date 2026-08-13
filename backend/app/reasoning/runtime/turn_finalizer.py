"""Post-loop finalization for QingShui agent turns."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from app.reasoning.runtime.journal import append_journal_event
from app.reasoning.runtime.run_ledger import RunLedgerRecord
from app.reasoning.runtime.turn_context import AgentTurnContext


@dataclass
class AgentTurnFinalization:
    trace: dict[str, Any]
    report: Any | None
    result: dict[str, Any]


async def finalize_agent_turn(
    context: AgentTurnContext,
    *,
    raw_analysis: str,
    build_trace_metadata: Callable[..., dict[str, Any]],
    build_analysis_report: Callable[..., Any],
    emit_fn: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None,
    stop_reason: str | None = None,
    ledger_store: Any | None = None,
) -> AgentTurnFinalization:
    """Build trace/report/result for one completed agent turn."""
    trace = build_trace_metadata(**context.to_trace_inputs())
    report = build_analysis_report(
        topic=context.question,
        raw_analysis=raw_analysis,
        turns=context.turns,
        trace=trace,
    )

    if emit_fn is not None:
        await emit_fn(
            "stream_end",
            {
                "report_content": report.to_markdown(),
                "report_json": report.to_dict(),
                "report_id": report.report_id,
                "compliance_passed": report.compliance_declared,
                "turns": context.turns,
                "content": raw_analysis,
                "stop_reason": stop_reason,
                "run_id": context.run_id,
            },
        )

    append_journal_event("stream_end", {"turns": context.turns, "truncated": context.truncated})
    append_journal_event("readiness_binding", trace.get("readiness_binding", {}))
    if ledger_store is not None:
        try:
            ledger_store.append(
                RunLedgerRecord(
                    run_id=context.run_id,
                    thread_id=context.thread_id,
                    question=context.question,
                    report_id=report.report_id,
                    readiness_binding=trace.get("readiness_binding", {}),
                    trace_summary=trace.get("trace_summary", {}),
                    evidence_refs=trace.get("evidence_refs", []),
                    tool_audit=trace.get("tool_audit", []),
                    graph_refs=trace.get("graph_refs", []),
                )
            )
        except Exception as exc:
            append_journal_event("run_ledger_persist_failed", {"error": str(exc)})

    result = context.to_result_base(raw_analysis)
    result["trace"] = trace
    return AgentTurnFinalization(trace=trace, report=report, result=result)
