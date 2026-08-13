"""HITL checkpoint store — thread state persistence for suspend/resume."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from langchain_core.messages import BaseMessage

logger = logging.getLogger(__name__)

CLARIFICATION_TOOLS = frozenset({"ask_clarification", "AskUserQuestion"})


def parse_clarification_result(tool_name: str, result_str: str) -> dict | None:
    """Parse a tool result from a clarification tool into a structured dict."""
    if tool_name not in CLARIFICATION_TOOLS:
        return None
    if tool_name == "AskUserQuestion":
        try:
            data = json.loads(result_str) if isinstance(result_str, str) else {}
        except (json.JSONDecodeError, TypeError):
            data = {}
        questions = (data.get("questions") or [{}])[0]
        return {
            "clarification_id": str(uuid.uuid4())[:8],
            "question": questions.get("question", str(result_str)[:200]),
            "type": questions.get("type", "ambiguous"),
            "options": questions.get("options"),
            "context": questions.get("context"),
        }
    else:
        # 工具结果里的换行可能是字面量 "\n"（反斜杠+n），先规范成真换行再解析。
        text = str(result_str).replace("\\n", "\n")
        cid = ""
        context = None
        question_lines: list[str] = []
        for raw_line in text.split("\n"):
            line = raw_line.strip()
            if not line:
                continue
            if "clarification_id:" in line:
                cid = line.split("clarification_id:")[-1].strip()
                continue
            # 去掉 "**澄清请求** (missing_info)" 这类标题样板
            if line.startswith("**澄清请求**") or line.startswith("澄清请求"):
                continue
            # "**背景：** ..." 归入 context，不塞进 question
            if line.startswith("**背景") or line.startswith("背景："):
                context = line.replace("**背景：**", "").replace("**背景:**", "").replace("背景：", "").strip()
                continue
            question_lines.append(line)
        question = " ".join(question_lines).strip() or text[:200]
        return {
            "clarification_id": cid or str(uuid.uuid4())[:8],
            "question": question[:200],
            "type": "ambiguous",
            "options": None,
            "context": context,
        }


@dataclass
class PendingClarification:
    task_id: str
    thread_id: str
    clarification_id: str
    question: str
    clarification_type: str
    options: list[dict] | None
    context: str | None
    messages: list[BaseMessage]
    run_config: dict
    created_at: datetime = field(default_factory=datetime.now)


class HITLStore:
    """In-memory checkpoint store for paused agent runs.

    Thread-safe for async access via asyncio.Lock.
    TTL-based cleanup (default 1 hour).
    """

    def __init__(self, ttl_seconds: int = 3600):
        self._store: dict[str, PendingClarification] = {}
        self._lock = asyncio.Lock()
        self._ttl = ttl_seconds

    async def save(self, task_id: str, state: PendingClarification) -> None:
        async with self._lock:
            self._store[task_id] = state

    async def pop(self, task_id: str) -> PendingClarification | None:
        async with self._lock:
            return self._store.pop(task_id, None)

    async def get(self, task_id: str) -> PendingClarification | None:
        async with self._lock:
            return self._store.get(task_id)

    async def cleanup_expired(self) -> int:
        now = datetime.now()
        expired = []
        async with self._lock:
            for tid, state in self._store.items():
                if (now - state.created_at).total_seconds() > self._ttl:
                    expired.append(tid)
            for tid in expired:
                del self._store[tid]
        if expired:
            logger.info(f"[HITLStore] cleanup_expired: removed {len(expired)} stale tasks")
        return len(expired)


_hitl_store = HITLStore()


def get_hitl_store() -> HITLStore:
    return _hitl_store
