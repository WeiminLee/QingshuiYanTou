from __future__ import annotations

from typing import Any

from app.reasoning.context.router import MemoryRouter
from app.reasoning.context.schemas import (
    AgentContextDTO,
    ReadinessContextDTO,
    SignalContextDTO,
    SignalMemoryDTO,
    UserHitDTO,
    UserSnapshotDTO,
)
from app.reasoning.context.user_snapshot import build_user_snapshot


async def _load_signal_detail(signal_id: str) -> dict | None:
    from app.core.database import async_session
    from app.signals.service import get_signal_detail

    async with async_session() as session:
        return await get_signal_detail(session, signal_id)


async def _load_readiness_context() -> dict[str, str]:
    try:
        from app.reasoning.langchain_agent.freshness import load_freshness_context

        text = await load_freshness_context()
        return {
            "overall_status": _extract_line(text, "overall_status") or "unknown",
            "answer_boundary": _extract_line(text, "answer_boundary"),
        }
    except Exception:
        return {"overall_status": "unavailable", "answer_boundary": ""}


def _extract_line(text: str, key: str) -> str:
    prefix = f"{key}="
    for line in (text or "").splitlines():
        if line.startswith(prefix):
            return line[len(prefix) :].strip()
    return ""


def match_user_hits(signal_detail: dict, user_snapshot: UserSnapshotDTO) -> UserHitDTO:
    candidates = _candidate_names(signal_detail)
    return UserHitDTO(
        portfolio=_match_items(candidates, user_snapshot.portfolio, ["name", "ts_code"]),
        watchlist=_match_items(candidates, user_snapshot.watchlist, ["name", "ts_code"]),
        preferences=_match_items(candidates, user_snapshot.preferences, ["subject"]),
    )


def _candidate_names(signal_detail: dict) -> list[str]:
    values: list[str] = []
    for key in ["subject_name"]:
        if signal_detail.get(key):
            values.append(str(signal_detail[key]))
    for prop in signal_detail.get("propagations") or []:
        if prop.get("target_name"):
            values.append(str(prop["target_name"]))
        path = prop.get("signal_path") or {}
        values.extend(str(node) for node in path.get("nodes") or [] if node)
    seen: set[str] = set()
    return [item for item in values if item and not (item in seen or seen.add(item))]


def _match_items(candidates: list[str], rows: list[dict[str, Any]], keys: list[str]) -> list[str]:
    hits: list[str] = []
    for row in rows:
        label = str(row.get(keys[0]) or "")
        for key in keys:
            value = str(row.get(key) or "")
            if value and _matches_any(value, candidates):
                hits.append(label or value)
                break
    return list(dict.fromkeys(hits))


def _matches_any(value: str, candidates: list[str]) -> bool:
    if value in candidates:
        return True
    if len(value) >= 2:
        return any(value in candidate or candidate in value for candidate in candidates if len(candidate) >= 2)
    return False


class AgentContextBuilder:
    def __init__(self, router: MemoryRouter | None = None):
        self.router = router or MemoryRouter()

    async def build(
        self,
        *,
        user_id: str,
        thread_id: str,
        question: str,
        signal_id: str | None = None,
        page_context: dict | None = None,
    ) -> AgentContextDTO:
        route = self.router.classify(
            question,
            user_id=user_id,
            thread_id=thread_id,
            signal_id=signal_id,
            page_context=page_context,
        )
        user_snapshot, warnings = await build_user_snapshot(user_id)
        readiness = ReadinessContextDTO(**await _load_readiness_context())
        signal_context = None
        if signal_id:
            try:
                detail = await _load_signal_detail(signal_id)
            except Exception:
                detail = None
                warnings.append("signal_context_read_failed")
            if detail:
                hits = match_user_hits(detail, user_snapshot)
                detail["user_hits"] = hits.model_dump()
                detail["portfolio_hits"] = hits.portfolio or detail.get("portfolio_hits", [])
                memory = detail.get("memory") or {"schema_version": "signal.memory.v1", "signal_id": signal_id}
                signal_context = SignalContextDTO(
                    signal=_signal_summary(detail),
                    source=detail.get("source") or {},
                    primary_signal=detail.get("primary_signal") or {},
                    memory=SignalMemoryDTO(**memory),
                    user_hits=hits,
                    portfolio_hits=detail.get("portfolio_hits") or [],
                    propagations=detail.get("propagations") or [],
                )
            else:
                warnings.append("signal_context_missing")
        elif route.route == "relation_reasoning":
            warnings.append("signal_context_missing")
        if route.route == "broad_synthesis":
            warnings.append("long_history_synthesis_not_enabled")
        ctx = AgentContextDTO(
            context_type="signal_research" if signal_context else "general_research",
            route=route.route,
            user_id=user_id,
            thread_id=thread_id,
            question=question,
            user_snapshot=user_snapshot,
            signal_context=signal_context,
            readiness_context=readiness,
            warnings=warnings,
        )
        ctx.prompt_context = render_prompt_context(ctx)
        return ctx


def _signal_summary(detail: dict) -> dict[str, Any]:
    keys = [
        "signal_id",
        "title",
        "summary",
        "source_type",
        "published_at",
        "subject_name",
        "subject_type",
        "signal_type",
        "polarity",
        "value_score",
        "confidence",
    ]
    return {key: detail.get(key) for key in keys if key in detail}


def render_prompt_context(ctx: AgentContextDTO) -> str:
    lines = ["<signal-context>", f"route: {ctx.route}"]
    if ctx.user_snapshot:
        portfolio = "、".join(item.get("name") or item.get("ts_code", "") for item in ctx.user_snapshot.portfolio)
        prefs = "、".join(item.get("subject", "") for item in ctx.user_snapshot.preferences)
        lines.extend(
            [
                "",
                "<user-snapshot>",
                f"- 持仓: {portfolio}" if portfolio else "- 持仓: ",
                f"- 偏好: {prefs}" if prefs else "- 偏好: ",
                "</user-snapshot>",
            ]
        )
    if ctx.signal_context:
        sig = ctx.signal_context.signal
        lines.extend(
            [
                "",
                "<signal-detail>",
                f"- 信号: {sig.get('title', '')}",
                f"  signal_id: {sig.get('signal_id', '')}",
                f"  value_score: {sig.get('value_score', '')}, confidence: {sig.get('confidence', '')}",
            ]
        )
        if ctx.signal_context.primary_signal.get("evidence_excerpt"):
            lines.append(f"  原文锚点: {ctx.signal_context.primary_signal['evidence_excerpt']}")
        if ctx.signal_context.memory:
            lines.append(
                f"  生命周期: {ctx.signal_context.memory.lifecycle_status}, 用户状态: {ctx.signal_context.memory.user_status}"
            )
        hits = ctx.signal_context.user_hits
        if hits.portfolio or hits.watchlist or hits.preferences:
            lines.append(
                f"  用户命中: portfolio={','.join(hits.portfolio)}; watchlist={','.join(hits.watchlist)}; preferences={','.join(hits.preferences)}"
            )
        for prop in ctx.signal_context.propagations[:5]:
            path = prop.get("signal_path") or {}
            nodes = " -> ".join(str(node) for node in path.get("nodes") or [] if node)
            if nodes:
                lines.append(f"  传导: {nodes}")
            if prop.get("reasoning"):
                lines.append(f"  理由: {prop['reasoning']}")
        lines.append("</signal-detail>")
    lines.extend(
        [
            "",
            "<data-readiness-summary>",
            f"overall_status: {ctx.readiness_context.overall_status}",
            f"answer_boundary: {ctx.readiness_context.answer_boundary}",
            "</data-readiness-summary>",
        ]
    )
    if ctx.warnings:
        lines.append(f"warnings: {', '.join(ctx.warnings)}")
    lines.append("</signal-context>")
    return "\n".join(lines)
