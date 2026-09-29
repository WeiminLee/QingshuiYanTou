"""Pure Knowledge-layer metric ops for dsh HTTP (no LangChain).

Logic previously lived under app.reasoning.tools.knowledge.metric_ops as @tool
wrappers. HTTP handlers and (temporarily) LangChain tools both call these.
"""
from __future__ import annotations

import re

from app.core.database import async_session
from app.knowledge.linklayer.models import Keyword, Link

_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")


def _to_float(value: str | None) -> float | None:
    if value is None:
        return None
    m = _NUM_RE.search(str(value))
    return float(m.group()) if m else None


async def _collect_rows(dimension: str, scope: str | None, as_of: str | None, limit: int) -> list[dict]:
    from sqlalchemy import and_, or_, select

    from app.knowledge.linklayer.queries import _parse_cutoff, _scope_evidence_subquery

    stmt = (
        select(
            Keyword.norm_text.label("metric"),
            Link.evidence_id,
            Link.metric_value,
            Link.metric_unit,
            Link.metric_period,
            Link.published_at,
        )
        .select_from(Link)
        .join(Keyword, Keyword.keyword_id == Link.keyword_id)
        .where(
            Keyword.layer == "dimension",
            or_(
                Keyword.norm_text == dimension,
                Keyword.parent_keyword_id.in_(
                    select(Keyword.keyword_id).where(
                        Keyword.layer == "dimension", Keyword.norm_text == dimension
                    )
                ),
            ),
        )
    )
    if scope:
        from sqlalchemy.orm import aliased

        scope_cte = (
            _scope_evidence_subquery(scope).distinct().cte("scope_ev").prefix_with("MATERIALIZED")
        )
        ids_scope = select(scope_cte.c.evidence_id)
        LinkA = aliased(Link)
        KeywordA = aliased(Keyword)
        subject_ids_scope = (
            select(KeywordA.keyword_id)
            .select_from(LinkA, KeywordA)
            .where(
                LinkA.keyword_id == KeywordA.keyword_id,
                KeywordA.layer == "subject",
                LinkA.evidence_id.in_(ids_scope),
            )
        ).scalar_subquery()
        stmt = stmt.add_cte(scope_cte).where(
            or_(
                Link.evidence_id.in_(ids_scope),
                Link.keyword_id.in_(subject_ids_scope),
            )
        )
    cutoff = _parse_cutoff(as_of)
    if cutoff is not None:
        stmt = stmt.where(Link.published_at <= cutoff)
    stmt = stmt.where(Link.metric_value.is_not(None))
    stmt = stmt.order_by(Link.metric_value.is_(None), Link.published_at.desc()).limit(limit * 20)

    async with async_session() as session:
        rows = (await session.execute(stmt)).all()
        evids = list({r[1] for r in rows})
        subj_map: dict[str, str] = {}
        if evids:
            subj_stmt = (
                select(Link.evidence_id, Keyword.norm_text, Link.source)
                .join(Keyword, and_(Keyword.keyword_id == Link.keyword_id, Keyword.layer == "subject"))
                .where(Link.evidence_id.in_(evids))
            )
            for evid, norm, src in (await session.execute(subj_stmt)).all():
                if src == "hint" or evid not in subj_map:
                    subj_map[evid] = norm

    out = []
    for r in rows:
        out.append({
            "metric": r[0], "evidence_id": r[1], "value": r[2],
            "unit": r[3], "period": r[4],
            "published_at": str(r[5]) if r[5] else None,
            "subject": subj_map.get(r[1]),
        })
    return out


async def compare_metric(
    *,
    dimension: str,
    scope: str | None = None,
    as_of: str | None = None,
    top_k: int = 30,
) -> dict:
    rows = await _collect_rows(dimension, scope, as_of, top_k)

    latest: dict[str, dict] = {}
    for r in rows:
        subj = r["subject"]
        if not subj:
            continue
        cur = latest.get(subj)
        has_val = _to_float(r["value"]) is not None
        if cur is None:
            latest[subj] = r
            continue
        cur_has = _to_float(cur["value"]) is not None
        if has_val and not cur_has:
            latest[subj] = r
        elif has_val == cur_has and (r["published_at"] or "") > (cur["published_at"] or ""):
            latest[subj] = r

    ranked = [r for r in latest.values() if _to_float(r["value"]) is not None]
    missing = [r for r in latest.values() if _to_float(r["value"]) is None]
    ranked.sort(key=lambda r: _to_float(r["value"]), reverse=True)

    return {
        "dimension": dimension,
        "scope": scope,
        "as_of": as_of,
        "count": len(ranked),
        "items": [
            {
                "subject": r["subject"], "value": r["value"], "unit": r["unit"],
                "period": r["period"], "published_at": r["published_at"],
                "evidence_id": r["evidence_id"],
            }
            for r in ranked[:top_k]
        ],
        "missing_value": len(missing),
        "note": "按数值降序；period 不同则不可直接比较（注意单位与期间口径）",
    }


async def rollup_metric(
    *,
    parent: str,
    scope: str | None = None,
    top_k: int = 30,
) -> dict:
    from sqlalchemy import func, select

    async with async_session() as session:
        parent_kw = (
            await session.execute(
                select(Keyword.keyword_id).where(
                    Keyword.layer == "dimension", Keyword.norm_text == parent
                )
            )
        ).first()
        if not parent_kw:
            children: list[dict] = []
        else:
            child_stmt = (
                select(Keyword.norm_text, func.count(Link.evidence_id).label("n"))
                .select_from(Keyword)
                .outerjoin(Link, Link.keyword_id == Keyword.keyword_id)
                .where(Keyword.layer == "dimension", Keyword.parent_keyword_id == parent_kw[0])
                .group_by(Keyword.norm_text)
                .order_by(func.count(Link.evidence_id).desc())
                .limit(top_k)
            )
            children = [
                {"child_metric": r[0], "evidence_count": r[1]}
                for r in (await session.execute(child_stmt)).all()
            ]

    return {
        "parent": parent,
        "scope": scope,
        "children": children,
        "count": len(children),
        "note": "child_metric 是细粒度标尺；可用 compare_metric 逐个深入",
    }


async def metric_trend(
    *,
    subject: str,
    dimension: str | None = None,
    limit: int = 50,
) -> dict:
    from sqlalchemy import select

    async with async_session() as session:
        subj_kw = (
            await session.execute(
                select(Keyword.keyword_id).where(
                    Keyword.layer == "subject", Keyword.norm_text == subject
                )
            )
        ).first()
        if not subj_kw:
            rows: list[dict] = []
        else:
            evid_sub = select(Link.evidence_id).where(Link.keyword_id == subj_kw[0])
            stmt = (
                select(Keyword.norm_text, Link.metric_value, Link.metric_unit,
                       Link.metric_period, Link.published_at, Link.evidence_id)
                .select_from(Link)
                .join(Keyword, Keyword.keyword_id == Link.keyword_id)
                .where(Keyword.layer == "dimension", Link.evidence_id.in_(evid_sub))
            )
            if dimension:
                stmt = stmt.where(Keyword.norm_text == dimension)
            stmt = stmt.order_by(Link.published_at.asc()).limit(limit)
            rows = [
                {
                    "metric": r[0], "value": r[1], "unit": r[2], "period": r[3],
                    "published_at": str(r[4]) if r[4] else None, "evidence_id": r[5],
                }
                for r in (await session.execute(stmt)).all()
            ]

    return {
        "subject": subject,
        "dimension": dimension,
        "count": len(rows),
        "timeline": rows,
        "note": "按时间正序；数值变化可直接看趋势，表述变化需 fetch_evidence 读原文",
    }
