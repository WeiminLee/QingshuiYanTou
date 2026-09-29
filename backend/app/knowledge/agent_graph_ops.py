"""Pure Knowledge-layer graph-walk ops for dsh HTTP (no LangChain)."""
from __future__ import annotations

_LAYER_ZH = {
    "subject": "公司",
    "scope": "产品/主题",
    "dimension": "指标",
    "stage": "阶段",
}

_STOP_SUBSTRINGS: tuple[str, ...] = (
    "公司", "证监会", "交易所", "投资者", "监管", "仲裁", "诉讼", "法院",
    "债券", "股票", "优先股", "发行", "律师", "会计师", "银行", "证券",
    "注册资本", "合计",
)


def _is_stopword(subject_name: str) -> bool:
    return any(s in (subject_name or "") for s in _STOP_SUBSTRINGS)


async def _resolve_anchor_ids(session, keyword: str) -> list[str]:
    from sqlalchemy import select

    from app.knowledge.linklayer.models import Keyword

    ids = (
        await session.execute(
            select(Keyword.keyword_id).where(Keyword.norm_text == keyword)
        )
    ).all()
    out = [r[0] for r in ids]
    if out:
        return out

    try:
        from app.knowledge.linklayer.dict_match import load_alias_table

        ts_code = load_alias_table().get(keyword)
        if ts_code:
            rows = (
                await session.execute(
                    select(Keyword.keyword_id).where(
                        Keyword.layer == "subject", Keyword.norm_text == ts_code
                    )
                )
            ).all()
            out += [r[0] for r in rows]
    except Exception:  # noqa: BLE001
        pass
    return out


async def related_nodes(
    *,
    keyword: str,
    layer: str | None = None,
    top_k: int = 20,
) -> dict:
    from sqlalchemy import func, select

    from app.core.database import async_session
    from app.knowledge.linklayer.models import Keyword, Link

    async with async_session() as session:
        anchor_ids = await _resolve_anchor_ids(session, keyword)
        if not anchor_ids:
            return {"keyword": keyword, "found": False, "neighbors": []}

        stmt = (
            select(
                Keyword.layer,
                Keyword.norm_text,
                func.count(func.distinct(Link.evidence_id)).label("cooccur"),
            )
            .select_from(Link)
            .join(Keyword, Keyword.keyword_id == Link.keyword_id)
            .where(
                Link.evidence_id.in_(
                    select(Link.evidence_id).where(Link.keyword_id.in_(anchor_ids))
                ),
                Keyword.keyword_id.notin_(anchor_ids),
            )
            .group_by(Keyword.layer, Keyword.norm_text)
            .order_by(func.count(func.distinct(Link.evidence_id)).desc())
            .limit(top_k * 3)
        )
        if layer:
            stmt = stmt.where(Keyword.layer == layer)
        rows = (await session.execute(stmt)).all()
        rows = [r for r in rows if not _is_stopword(r[1])]

    return {
        "keyword": keyword,
        "found": True,
        "neighbors": [
            {"layer": r[0], "layer_zh": _LAYER_ZH.get(r[0], r[0]),
             "name": r[1], "cooccur_evidence": r[2]}
            for r in rows[:top_k]
        ],
        "note": "cooccur_evidence = 共同出现的证据数（关联广度，非主营强度）",
    }


async def propagate_along(
    *,
    start: str,
    max_hops: int = 2,
    min_cooccur: int = 2,
    top_k: int = 15,
) -> dict:
    from sqlalchemy import func, select

    from app.core.database import async_session
    from app.knowledge.linklayer.models import Keyword, Link

    async with async_session() as session:
        async def neighbors(kw_ids: list[str], exclude: set[str]) -> list[tuple[str, str, str, int]]:
            stmt = (
                select(
                    Keyword.keyword_id,
                    Keyword.layer,
                    Keyword.norm_text,
                    func.count(func.distinct(Link.evidence_id)).label("cooccur"),
                )
                .select_from(Link)
                .join(Keyword, Keyword.keyword_id == Link.keyword_id)
                .where(
                    Link.evidence_id.in_(
                        select(Link.evidence_id).where(Link.keyword_id.in_(kw_ids))
                    ),
                    Keyword.keyword_id.notin_(list(exclude)),
                )
                .group_by(Keyword.keyword_id, Keyword.layer, Keyword.norm_text)
                .having(func.count(func.distinct(Link.evidence_id)) >= min_cooccur)
                .order_by(func.count(func.distinct(Link.evidence_id)).desc())
                .limit(top_k * 5)
            )
            return [(r[0], r[1], r[2], r[3]) for r in (await session.execute(stmt)).all()]

        start_ids = await _resolve_anchor_ids(session, start)
        if not start_ids:
            return {"start": start, "found": False, "paths": []}

        frontier = list(start_ids)
        visited: set[str] = set(frontier)
        layers_out: list[list[dict]] = []

        for hop in range(1, max_hops + 1):
            nb = await neighbors(frontier, visited)
            nb = [n for n in nb if not _is_stopword(n[2])]
            if not nb:
                break
            visited.update(n[0] for n in nb)
            layers_out.append([
                {"hop": hop, "layer": n[1], "layer_zh": _LAYER_ZH.get(n[1], n[1]),
                 "name": n[2], "cooccur_evidence": n[3]}
                for n in nb[:top_k]
            ])
            frontier = [n[0] for n in nb[:top_k]]

    flat = [x for layer in layers_out for x in layer]
    return {
        "start": start,
        "found": True,
        "max_hops": max_hops,
        "min_cooccur": min_cooccur,
        "reachable": flat,
        "count": len(flat),
        "note": "按跳层分组；共现≠因果，跳数越大越需交叉验证",
    }
