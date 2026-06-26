"""RunJournal-lite tests."""

from __future__ import annotations


def test_run_journal_lifecycle_and_serialization():
    from app.reasoning.runtime.journal import RunJournal

    journal = RunJournal(thread_id="t1", question="分析光模块")
    journal.append("tool_called", {"name": "get_kline", "args": {"x": "y"}})
    journal.add_token_usage({"prompt_tokens": 10, "completion_tokens": 5})
    journal.finish()
    data = journal.to_dict()

    assert data["run_id"]
    assert data["status"] == "completed"
    assert data["token_usage"]["prompt_tokens"] == 10
    assert data["events"][0]["type"] == "tool_called"


def test_run_journal_truncates_events():
    from app.reasoning.runtime.journal import RunJournal

    journal = RunJournal(max_events=2)
    journal.append("a")
    journal.append("b")
    journal.append("c")

    assert [event.type for event in journal.events] == ["b", "c"]


def test_current_journal_context_helpers():
    from app.reasoning.runtime.journal import (
        RunJournal,
        append_journal_event,
        get_current_journal,
        reset_current_journal,
        set_current_journal,
    )

    journal = RunJournal()
    token = set_current_journal(journal)
    try:
        append_journal_event("x", {"value": "ok"})
        assert get_current_journal() is journal
        assert journal.events[-1].type == "x"
    finally:
        reset_current_journal(token)
