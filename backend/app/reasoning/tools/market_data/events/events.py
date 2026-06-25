from __future__ import annotations

import logging
from typing import Annotated

from langchain_core.tools import tool
from sqlalchemy import text

from app.core.database import engine
from app.reasoning.tools._async_runner import run_async

logger = logging.getLogger(__name__)


@tool("find_events")
def find_events(
    query: Annotated[str | None, "搜索关键词，越精确越好（如 'AI芯片 制裁 中际旭创'）。query 和 tags 可选至少传一个"] = None,
    tags: Annotated[list[str] | None, "板块/概念标签过滤（如 ['芯片概念', '华为概念']）。事件入库时会自动打标签，可用来精确筛选"] = None,
    date_from: Annotated[str | None, "开始日期 YYYYMMDD，不传则不限制"] = None,
    date_to: Annotated[str | None, "结束日期 YYYYMMDD，不传则到今天"] = None,
    top_n: Annotated[int, "返回条数，默认 10，最多 30"] = 10,
) -> str:
    """搜索财联社事件库。按关键词或板块标签查找相关事件，支持按时间范围过滤。
    适合用来查询最近影响某个行业、板块或个股的新闻事件。"""
    top_n = min(max(top_n, 1), 30)
    return run_async(_find_events(query, tags, date_from, date_to, top_n))


async def _find_events(
    query: str | None,
    tags: list[str] | None,
    date_from: str | None,
    date_to: str | None,
    top_n: int,
) -> str:
    if not query and not tags:
        return "请至少提供搜索关键词(query)或板块标签(tags)。"

    conditions: list[str] = []
    params: dict = {}

    if tags:
        tag_conditions = []
        for i, tag in enumerate(tags):
            key = f"tag_{i}"
            tag_conditions.append(f"metadata @> :{key}")
            params[key] = f'{{"tags": ["{tag}"]}}'
        conditions.append(f"({' OR '.join(tag_conditions)})")

    if query:
        keywords = [kw.strip() for kw in query.split() if kw.strip()]
        kw_conditions = []
        for i, kw in enumerate(keywords):
            key = f"kw_{i}"
            kw_conditions.append(f"title ILIKE :{key}")
            params[key] = f"%{kw}%"
        conditions.append(f"({' AND '.join(kw_conditions)})")

    if date_from:
        conditions.append("publish_at >= :date_from")
        params["date_from"] = date_from
    if date_to:
        conditions.append("publish_at <= :date_to")
        params["date_to"] = date_to

    where_clause = " AND ".join(conditions)
    sql = f"""
        SELECT event_id, title, summary, source, publish_at
        FROM events
        WHERE {where_clause}
        ORDER BY publish_at DESC
        LIMIT :top_n
    """
    params["top_n"] = top_n

    async with engine.connect() as conn:
        result = await conn.execute(text(sql), params)
        rows = result.fetchall()

    if not rows:
        return "未找到匹配的事件。"

    events = [
        {
            "event_id": r[0],
            "title": r[1],
            "summary": (r[2] or "")[:200],
            "source": r[3],
            "publish_at": str(r[4]) if r[4] else "",
        }
        for r in rows
    ]
    return _format_event_list(events, query or "")


def _format_event_list(events: list[dict], query: str) -> str:
    lines = [f"## 事件搜索结果（关键词：{query or '全部'}）\n"]
    for i, ev in enumerate(events, 1):
        lines.append(f"**{i}.** {ev['title']}")
        lines.append(f"   📅 {ev['publish_at']}  |  来源：{ev['source']}")
        if ev['summary']:
            lines.append(f"   摘要：{ev['summary'][:150]}")
        lines.append(f"   ID: `{ev['event_id']}`")
        lines.append("")
    return "\n".join(lines)


@tool("get_event_detail")
def get_event_detail(
    event_id: Annotated[str, "事件 ID（EV: 开头）"],
) -> str:
    """获取事件的原始全文内容。在 find_events 找到感兴趣的事件后调用。"""
    return run_async(_get_event_detail(event_id))


async def _get_event_detail(event_id: str) -> str:
    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT event_id, title, content, source, publish_at FROM events WHERE event_id = :eid"),
            {"eid": event_id},
        )
        row = result.fetchone()

    if not row:
        return f"未找到事件: {event_id}"

    return _format_event_detail({
        "event_id": row[0],
        "title": row[1],
        "content": row[2] or "（无全文内容）",
        "source": row[3],
        "publish_at": str(row[4]) if row[4] else "",
    })


def _format_event_detail(event: dict) -> str:
    return (
        f"## 事件详情\n"
        f"ID: {event['event_id']}\n"
        f"标题: {event['title']}\n"
        f"时间: {event['publish_at']}\n"
        f"来源: {event['source']}\n\n"
        f"【全文内容】\n{event['content']}"
    )
