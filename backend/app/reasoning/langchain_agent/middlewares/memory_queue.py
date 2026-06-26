"""MemoryQueue-lite for post-run investment research memory updates."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class MemoryJob:
    thread_id: str
    messages: list[dict]
    agent_name: str | None = None
    enqueued_at: float = field(default_factory=time.time)


class MemoryUpdaterProtocol(Protocol):
    def update(self, thread_id: str, agent_name: str | None, messages: list[dict]) -> None: ...


class MemoryQueueLite:
    """Small debounced queue that coalesces jobs by thread id."""

    def __init__(
        self,
        updater: MemoryUpdaterProtocol,
        debounce_seconds: float = 2.0,
        max_size: int = 100,
    ) -> None:
        self._updater = updater
        self._debounce_seconds = debounce_seconds
        self._max_size = max_size
        self._jobs: dict[str, MemoryJob] = {}
        self._timer: threading.Timer | None = None
        self._lock = threading.RLock()

    def enqueue(self, thread_id: str, messages: list[dict], agent_name: str | None = None) -> None:
        if not thread_id or not messages:
            return
        with self._lock:
            if len(self._jobs) >= self._max_size and thread_id not in self._jobs:
                oldest = min(self._jobs.items(), key=lambda item: item[1].enqueued_at)[0]
                self._jobs.pop(oldest, None)
            self._jobs[thread_id] = MemoryJob(
                thread_id=thread_id,
                agent_name=agent_name,
                messages=messages,
            )
            self._schedule_locked()

    def _schedule_locked(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
        self._timer = threading.Timer(self._debounce_seconds, self.flush)
        self._timer.daemon = True
        self._timer.start()

    def flush(self) -> None:
        with self._lock:
            jobs = list(self._jobs.values())
            self._jobs.clear()
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None

        for job in jobs:
            self._updater.update(job.thread_id, job.agent_name, job.messages)

    def pending_count(self) -> int:
        with self._lock:
            return len(self._jobs)
