"""Context compression snapshot helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

_MARKERS = {
    "data_readiness": ("<data_readiness>", "</data_readiness>"),
    "memory_context": ("<memory-context>", "<memory>"),
    "background_context": ("<background_context>",),
    "graph_context": ("<graph_context>",),
    "kg_anchors": ("<kg_anchors>",),
    "kline_data": ("[K线数据]",),
}


@dataclass(frozen=True)
class ContextSnapshot:
    before_message_count: int
    after_message_count: int
    before_tokens: int
    after_tokens: int
    reason: str
    strategy: str
    structural_markers: list[str]
    preserved_markers: list[str]
    lost_markers: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "compressed": self.after_tokens < self.before_tokens or self.after_message_count < self.before_message_count,
            "before_message_count": self.before_message_count,
            "after_message_count": self.after_message_count,
            "before_tokens": self.before_tokens,
            "after_tokens": self.after_tokens,
            "tokens_saved": max(0, self.before_tokens - self.after_tokens),
            "reason": self.reason,
            "strategy": self.strategy,
            "structural_markers": self.structural_markers,
            "preserved_markers": self.preserved_markers,
            "lost_markers": self.lost_markers,
        }


def build_context_snapshot(
    *,
    before_messages: list[Any],
    after_messages: list[Any],
    before_tokens: int,
    after_tokens: int,
    reason: str,
    strategy: str,
) -> ContextSnapshot:
    before_markers = _collect_markers(before_messages)
    after_markers = _collect_markers(after_messages)
    return ContextSnapshot(
        before_message_count=len(before_messages),
        after_message_count=len(after_messages),
        before_tokens=before_tokens,
        after_tokens=after_tokens,
        reason=reason,
        strategy=strategy,
        structural_markers=before_markers,
        preserved_markers=[marker for marker in before_markers if marker in after_markers],
        lost_markers=[marker for marker in before_markers if marker not in after_markers],
    )


def _collect_markers(messages: list[Any]) -> list[str]:
    found: list[str] = []
    for msg in messages:
        content = _message_content(msg)
        if not content:
            continue
        for key, needles in _MARKERS.items():
            if key in found:
                continue
            if any(needle in content for needle in needles):
                found.append(key)
    return found


def _message_content(msg: Any) -> str:
    if isinstance(msg, dict):
        content = msg.get("content", "")
    else:
        content = getattr(msg, "content", "")
    return content if isinstance(content, str) else str(content or "")
