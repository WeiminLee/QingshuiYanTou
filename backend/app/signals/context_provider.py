from __future__ import annotations

import logging

from app.core.database import async_session
from app.signals.service import get_signal_detail

logger = logging.getLogger(__name__)


def format_signal_context(detail: dict | None) -> str:
    if not detail:
        return ""

    title = detail.get("title") or detail.get("summary") or ""
    value_score = detail.get("value_score", "")
    confidence = detail.get("confidence", "")
    source_type = detail.get("source_type", "")
    excerpt = detail.get("evidence_excerpt") or ""
    hits = detail.get("portfolio_hits") or []
    hit_text = "、".join(str(item) for item in hits if item)
    propagation_lines = []
    for item in detail.get("propagations") or []:
        path = item.get("relation_path") or ""
        reasoning = item.get("reasoning") or ""
        metadata = item.get("metadata") or {}
        secondary_type = metadata.get("secondary_type") or ""
        path_nodes = metadata.get("path_nodes") or []
        path_node_text = " -> ".join(str(node) for node in path_nodes if node)
        if path or reasoning:
            lines = [f"  传导: {path}"]
            if secondary_type:
                lines.append(f"  二阶类型: {secondary_type}")
            if path_node_text:
                lines.append(f"  KG路径: {path_node_text}")
            if reasoning:
                lines.append(f"  理由: {reasoning}")
            propagation_lines.append("\n".join(lines).strip())

    parts = [
        "<signal-context>",
        "[高价值信号]",
        f"- {title}",
        f"  signal_id: {detail.get('signal_id', '')}",
        f"  value_score: {value_score}, confidence: {confidence}, source: {source_type}",
    ]
    if excerpt:
        parts.append(f"  原文锚点: {excerpt}")
    parts.extend(propagation_lines)
    if hit_text:
        parts.append(f"  相关持仓: {hit_text}")
    parts.append("</signal-context>")
    return "\n".join(parts)


async def fetch_signal_context(
    *,
    signal_id: str | None = None,
    question: str = "",
    user_id: str | None = None,
) -> str:
    if not signal_id:
        return ""
    try:
        async with async_session() as session:
            detail = await get_signal_detail(session, signal_id)
        return format_signal_context(detail)
    except Exception as exc:
        logger.warning("[SignalContext] failed to fetch signal %s: %s", signal_id, exc)
        return ""
