"""SubAgent task tool tests."""
from __future__ import annotations

import pytest


def test_task_tool_registered_only_when_subagent_enabled():
    from app.reasoning.tools.tools import get_available_tools

    no_subagent = [tool.name for tool in get_available_tools(subagent_enabled=False)]
    with_subagent = [tool.name for tool in get_available_tools(subagent_enabled=True)]

    assert "task" not in no_subagent
    assert "task" in with_subagent


def test_task_tool_rejects_trading_execution_intent():
    from app.reasoning.tools.builtins.task import task_tool

    with pytest.raises(ValueError):
        task_tool.invoke({"task": "帮我自动下单买入 300308.SZ", "agent_name": "researcher"})


def test_task_tool_accepts_research_task(monkeypatch):
    from app.reasoning.tools.builtins import task as task_module

    class FakeExecutor:
        def submit(self, agent_name: str, prompt: str) -> str:
            return "task-ok"

        def get_status(self, task_id: str) -> dict:
            return {
                "task_id": task_id,
                "agent_name": "researcher",
                "status": "completed",
                "result": "研究结论",
            }

    monkeypatch.setattr(task_module, "get_executor", lambda: FakeExecutor())

    result = task_module.task_tool.invoke({
        "task": "分析光模块产业链的风险因素",
        "agent_name": "researcher",
    })

    assert "研究结论" in result

