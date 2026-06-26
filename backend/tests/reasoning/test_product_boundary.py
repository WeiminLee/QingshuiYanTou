"""Product boundary tests: QingShui is research-only, never execution."""

from __future__ import annotations

import pytest


@pytest.mark.parametrize(
    "text",
    [
        "自动下单买入中际旭创",
        "place order for 300308.SZ",
        "broker execution",
        "交易执行",
        "rebalance execution",
    ],
)
def test_execution_intent_is_rejected(text):
    from app.reasoning.tools.guardrails import validate_research_only

    with pytest.raises(ValueError):
        validate_research_only(text)


def test_research_language_is_allowed():
    from app.reasoning.tools.guardrails import validate_research_only

    validate_research_only("分析中际旭创的投资假设、风险因素和待跟踪催化")


def test_tool_boundary_rejects_execution_tool():
    from app.reasoning.tools.guardrails import validate_tool_boundary

    with pytest.raises(ValueError):
        validate_tool_boundary("auto_order", "自动下单工具")
