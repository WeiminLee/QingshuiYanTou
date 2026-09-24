# backend/app/reasoning/tools/knowledge/graph_walk.py
"""基于 link 层的图传递（不依赖 Neo4j）。

设计意图（owner 定调）：关系不用 LLM 抽，而是从 link 的「共现」中涌现。
本模块把 link 层当作图：
  · 节点 = keyword（subject / scope / dimension / stage）
  · 边   = 同一 evidence 内的共现
  · 边权 = 共现的 evidence 数（非"主营强度"，而是"关联广度"）

两个工具：
  · related_nodes  —— 一跳邻居（某节点的关联节点 + 共现证据数）
  · propagate_along —— 多跳传递（沿共现链找间接关联，用于产业链/传导推理）
"""
from __future__ import annotations

from typing import Annotated

from langchain_core.tools import tool

from app.reasoning.tools.knowledge.link_queries import run_async

_LAYER_ZH = {
    "subject": "公司",
    "scope": "产品/主题",
    "dimension": "指标",
    "stage": "阶段",
}


def _run_sync(coro):
    from app.reasoning.tools.knowledge.metric_ops import _run_sync as _rs

    return _rs(coro)


async def _resolve_anchor_ids(session, keyword: str) -> list[str]:
    """起点解析：支持 公司名 / ts_code / 产品名。

    subject 层的 norm_text 是 ts_code（如 003026.SZ），用户通常给中文简称，
    故经 company_aliases 反查；同时保留原名精确匹配（产品/指标层直接用原名）。
    """
    from sqlalchemy import select

    from app.core.database import async_session  # noqa: F401
    from app.knowledge.linklayer.models import Keyword

    ids = (
        await session.execute(
            select(Keyword.keyword_id).where(Keyword.norm_text == keyword)
        )
    ).all()
    out = [r[0] for r in ids]
    if out:
        return out

    # 别名反查（公司名 → ts_code）
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
    except Exception:  # noqa: BLE001 别名表缺失不应阻断
        pass
    return out


@tool
def related_nodes(
    keyword: Annotated[str, "起点节点：公司名/ts_code、产品或指标名"],
    layer: Annotated[str | None, "限定邻居层：subject|scope|dimension|stage；不填则全部"] = None,
    top_k: Annotated[int, "返回邻居数上限"] = 20,
) -> dict:
    """图传递（一跳）：某节点在图上的直接邻居及其共现广度。

    边由「同一 evidence 内共现」涌现——无需 LLM 抽关系。共现证据数越大，
    说明两者在该语料中被反复一起提及（既是关联广度，也是可交叉验证的机会面）。
    用于：某产品的相关公司有哪些、某公司的关联指标/主题是什么。
    """
    async def _run() -> dict:
        from sqlalchemy import and_, func, select

        from app.core.database import async_session
        from app.knowledge.linklayer.models import Keyword, Link

        async with async_session() as session:
            anchor_ids = await _resolve_anchor_ids(session, keyword)
            if not anchor_ids:
                return {"keyword": keyword, "found": False, "neighbors": []}

            # 与 anchor 共现的所有 keyword（排除自身），按共现 evidence 数排序
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

    return _run_sync(_run())


@tool
def propagate_along(
    start: Annotated[str, "起点：公司名/ts_code 或产品名"],
    max_hops: Annotated[int, "最大跳数（1-3；越大越容易引入噪音）"] = 2,
    min_cooccur: Annotated[int, "边的最小共现证据数（过滤弱关联）"] = 2,
    top_k: Annotated[int, "每返回节点数上限"] = 15,
) -> dict:
    """图传递（多跳）：沿共现链寻找间接关联节点。

    例：从"某公司"出发经"某产品"到"其他生产该产品的公司"（潜在同业/竞品），
    或经"某材料"到"下游应用"。用于产业链传导、隐藏关联发现。

    注意：跳数越多噪音越大（共现不等于因果），min_cooccur 用于过滤弱边。
    """
    async def _run() -> dict:
        from sqlalchemy import func, select

        from app.core.database import async_session
        from app.knowledge.linklayer.models import Keyword, Link

        async with async_session() as session:
            async def neighbors(kw_ids: list[str], exclude: set[str]) -> list[tuple[str, str, str, int]]:
                """返回 (kw_id, layer, norm_text, cooccur) 的邻居。"""
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

    return _run_sync(_run())
