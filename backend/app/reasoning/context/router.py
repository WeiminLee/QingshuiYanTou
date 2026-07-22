from __future__ import annotations

from pydantic import BaseModel, Field


class MemoryRoute(BaseModel):
    route: str
    reason: str
    required_context: list[str] = Field(default_factory=list)


class MemoryRouter:
    def classify(
        self,
        question: str,
        *,
        user_id: str = "",
        thread_id: str = "",
        signal_id: str | None = None,
        page_context: dict | None = None,
    ) -> MemoryRoute:
        text = question or ""
        if signal_id:
            return MemoryRoute(
                route="relation_reasoning",
                reason="signal_id provided",
                required_context=["user_snapshot", "signal_context", "readiness_context"],
            )
        if any(key in text for key in ["过去", "最近一个月", "总结", "复盘", "长期", "变化趋势"]):
            return MemoryRoute(
                route="broad_synthesis",
                reason="long history keyword",
                required_context=["user_snapshot"],
            )
        if any(key in text for key in ["我是否", "我有没有", "我的持仓", "我的关注"]):
            return MemoryRoute(
                route="factual_lookup",
                reason="user fact keyword",
                required_context=["user_snapshot"],
            )
        if any(key in text for key in ["这个信号", "传导", "影响我的持仓", "产业链", "二阶"]):
            return MemoryRoute(
                route="relation_reasoning",
                reason="relation keyword",
                required_context=["user_snapshot", "signal_context", "readiness_context"],
            )
        return MemoryRoute(
            route="relation_reasoning",
            reason="default",
            required_context=["user_snapshot", "readiness_context"],
        )
