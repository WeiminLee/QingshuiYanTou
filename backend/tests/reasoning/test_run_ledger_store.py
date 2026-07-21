import json

from app.reasoning.runtime.run_ledger import JsonlRunLedgerStore, RunLedgerRecord


def test_jsonl_run_ledger_store_appends_record(tmp_path):
    path = tmp_path / "runs.jsonl"
    store = JsonlRunLedgerStore(path)
    record = RunLedgerRecord(
        run_id="run-1",
        thread_id="thread-1",
        question="分析光模块",
        report_id="report-1",
        readiness_binding={"overall_status": "fresh"},
        trace_summary={"tool_call_count": 1},
        evidence_refs=[{"id": "DATA_READINESS"}],
        tool_audit=[{"tool": "get_kline"}],
        graph_refs=[],
    )

    store.append(record)

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["run_id"] == "run-1"
    assert payload["readiness_binding"]["overall_status"] == "fresh"
    assert payload["tool_audit"][0]["tool"] == "get_kline"
