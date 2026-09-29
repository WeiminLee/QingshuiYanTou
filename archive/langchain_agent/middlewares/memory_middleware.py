"""Research memory filtering and post-run enqueue helpers."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.reasoning.tools.guardrails import filter_research_memory_text

logger = logging.getLogger(__name__)

RESEARCH_MEMORY_CATEGORIES: tuple[str, ...] = (
    "关注标的",
    "投资假设",
    "已确认事实",
    "用户偏好",
    "待跟踪催化",
    "风险因素",
    "研究排除项",
)


@dataclass
class ResearchMemoryCandidate:
    category: str
    content: str
    confidence: float = 0.5


def classify_research_memory(text: str) -> list[ResearchMemoryCandidate]:
    """Conservative keyword classifier used before LLM memory update."""
    safe = filter_research_memory_text(text)
    if not safe:
        return []

    candidates: list[ResearchMemoryCandidate] = []
    checks = (
        ("关注标的", ("关注", "跟踪", "观察", ".sz", ".sh", ".bj")),
        ("投资假设", ("假设", "如果", "逻辑", "预期")),
        ("已确认事实", ("公告", "披露", "确认", "数据", "财报")),
        ("用户偏好", ("偏好", "希望", "关注风格", "看重")),
        ("待跟踪催化", ("催化", "发布", "落地", "招标", "订单")),
        ("风险因素", ("风险", "不确定", "下滑", "低于预期")),
        ("研究排除项", ("排除", "暂不关注", "不纳入")),
    )
    lowered = safe.lower()
    for category, keywords in checks:
        if any(keyword.lower() in lowered for keyword in keywords):
            candidates.append(ResearchMemoryCandidate(category=category, content=safe[:500]))

    if not candidates and len(safe) >= 20:
        candidates.append(ResearchMemoryCandidate(category="已确认事实", content=safe[:500], confidence=0.4))
    return candidates[:5]


def build_post_run_memory_messages(question: str, answer: str) -> list[dict]:
    """Build safe post-run messages for memory persistence."""
    messages: list[dict] = []
    safe_question = filter_research_memory_text(question)
    safe_answer = filter_research_memory_text(answer)
    if safe_question:
        messages.append({"role": "user", "content": safe_question[:1000]})
    if safe_answer:
        candidates = classify_research_memory(safe_answer)
        if candidates:
            tagged = "\n".join(f"[{c.category}] {c.content}" for c in candidates)
            messages.append({"role": "assistant", "content": tagged[:1500]})
    return messages

