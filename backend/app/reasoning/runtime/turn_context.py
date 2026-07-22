"""Per-turn context container for QingShui agent runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.reasoning.runtime.run_ledger import build_readiness_binding


@dataclass
class AgentTurnContext:
    """Mutable state shared by the agent loop and turn finalizer."""

    run_id: str
    thread_id: str
    question: str
    freshness_context: str = ""
    memory_context: str = ""
    background_context: str = ""
    graph_context: str = ""
    signal_context: str = ""
    agent_context: dict[str, Any] = field(default_factory=dict)
    kg_anchors: str = ""
    turns: int = 0
    truncated: bool = False
    full_content: list[str] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tool_results: list[dict[str, Any]] = field(default_factory=list)
    readiness_binding: dict[str, Any] = field(init=False)

    def __post_init__(self) -> None:
        self.readiness_binding = build_readiness_binding(self.freshness_context)

    @property
    def raw_analysis(self) -> str:
        return "".join(self.full_content)

    def to_trace_inputs(self) -> dict[str, Any]:
        return {
            "tool_calls": self.tool_calls,
            "tool_results": self.tool_results,
            "background": self.background_context,
            "graph_context": self.graph_context,
            "agent_context": self.agent_context,
            "freshness_context": self.freshness_context,
            "turns": self.turns,
            "run_id": self.run_id,
        }

    def to_result_base(self, raw_analysis: str | None = None) -> dict[str, Any]:
        content = self.raw_analysis if raw_analysis is None else raw_analysis
        return {
            "content": content,
            "reasoning": content,
            "turns": self.turns,
            "tool_calls": self.tool_calls,
            "tool_results": self.tool_results,
            "thread_id": self.thread_id,
            "truncated": self.truncated,
        }
