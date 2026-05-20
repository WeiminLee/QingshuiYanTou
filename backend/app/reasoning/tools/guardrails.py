"""Product boundary guardrails for QingShui research tools.

QingShuiTouYan is an investment research platform. It must never expose
trading, order placement, broker execution, exchange execution, or automated
execution capabilities.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


EXECUTION_INTENT_TERMS: tuple[str, ...] = (
    "下单",
    "自动下单",
    "自动交易",
    "交易执行",
    "执行交易",
    "委托买入",
    "委托卖出",
    "一键买入",
    "一键卖出",
    "券商下单",
    "实盘交易",
    "量化执行",
    "order placement",
    "place order",
    "submit order",
    "auto order",
    "auto trading",
    "trade execution",
    "execute trade",
    "broker execution",
    "exchange execution",
    "rebalance execution",
)

RESEARCH_SAFE_TERMS: tuple[str, ...] = (
    "研究",
    "分析",
    "风险",
    "假设",
    "催化",
    "关注",
    "复盘",
    "compare",
    "analysis",
    "research",
    "risk",
    "hypothesis",
)


@dataclass(frozen=True)
class BoundaryViolation:
    """A product-boundary violation detected in a tool/prompt/request."""

    term: str
    text: str


def find_execution_intent(text: str | None) -> BoundaryViolation | None:
    """Return the first execution-intent term in text, if any."""
    if not text:
        return None
    lowered = text.lower()
    for term in EXECUTION_INTENT_TERMS:
        pattern = re.escape(term.lower())
        if re.search(pattern, lowered):
            return BoundaryViolation(term=term, text=text)
    return None


def validate_research_only(text: str | None, *, field: str = "text") -> None:
    """Raise ValueError if text crosses QingShui's research-only boundary."""
    violation = find_execution_intent(text)
    if violation is not None:
        raise ValueError(
            f"{field} contains execution intent term '{violation.term}'. "
            "清水系统仅支持投研分析，不支持交易、自动下单或任何执行链路。"
        )


def is_research_only(text: str | None) -> bool:
    """Boolean helper for filters/tests."""
    return find_execution_intent(text) is None


def validate_tool_boundary(name: str, description: str = "") -> None:
    """Validate a tool name/description before registration."""
    validate_research_only(name, field="tool name")
    validate_research_only(description, field="tool description")


def filter_research_memory_text(text: str | None) -> str:
    """Return text only if it is safe to persist as research memory."""
    if not text or not is_research_only(text):
        return ""
    return text

