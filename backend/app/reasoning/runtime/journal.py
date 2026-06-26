"""RunJournal-lite for QingShui agent runtime observability."""

from __future__ import annotations

import contextvars
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

MAX_SUMMARY_CHARS = 500


def _now_iso() -> str:
    return datetime.now().isoformat()


def _safe_summary(value: Any, limit: int = MAX_SUMMARY_CHARS) -> str:
    text = "" if value is None else str(value)
    text = text.replace("\x00", "")
    return text if len(text) <= limit else text[:limit] + "..."


@dataclass
class JournalEvent:
    type: str
    timestamp: str = field(default_factory=_now_iso)
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class RunJournal:
    """Compact per-run journal for LLM/tool/task debugging."""

    run_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    thread_id: str = ""
    question: str = ""
    started_at: str = field(default_factory=_now_iso)
    finished_at: str | None = None
    status: str = "running"
    events: list[JournalEvent] = field(default_factory=list)
    token_usage: dict[str, int] = field(default_factory=dict)
    max_events: int = 500
    error: str | None = None
    _start_monotonic: float = field(default_factory=time.monotonic, repr=False)

    def append(self, event_type: str, data: dict[str, Any] | None = None) -> None:
        payload = data or {}
        event = JournalEvent(
            type=event_type,
            data={k: _safe_summary(v) for k, v in payload.items()},
        )
        self.events.append(event)
        if len(self.events) > self.max_events:
            self.events = self.events[-self.max_events :]

    def add_token_usage(self, usage: dict[str, Any] | None) -> None:
        if not usage:
            return
        for key, value in usage.items():
            if isinstance(value, int):
                self.token_usage[key] = self.token_usage.get(key, 0) + value

    def finish(self) -> None:
        self.status = "completed"
        self.finished_at = _now_iso()

    def fail(self, error: str) -> None:
        self.status = "failed"
        self.error = _safe_summary(error)
        self.finished_at = _now_iso()

    @property
    def duration_ms(self) -> int:
        return int((time.monotonic() - self._start_monotonic) * 1000)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "thread_id": self.thread_id,
            "question": _safe_summary(self.question, 200),
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": self.duration_ms,
            "status": self.status,
            "token_usage": dict(self.token_usage),
            "error": self.error,
            "events": [{"type": ev.type, "timestamp": ev.timestamp, "data": ev.data} for ev in self.events],
        }


_current_journal: contextvars.ContextVar[RunJournal | None] = contextvars.ContextVar(
    "qingshui_run_journal",
    default=None,
)


def set_current_journal(journal: RunJournal | None):
    """Set active journal and return the context token."""
    return _current_journal.set(journal)


def reset_current_journal(token) -> None:
    _current_journal.reset(token)


def get_current_journal() -> RunJournal | None:
    return _current_journal.get()


def append_journal_event(event_type: str, data: dict[str, Any] | None = None) -> None:
    journal = get_current_journal()
    if journal is not None:
        journal.append(event_type, data)
