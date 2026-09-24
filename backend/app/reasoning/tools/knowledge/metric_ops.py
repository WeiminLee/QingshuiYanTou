# backend/app/reasoning/tools/knowledge/metric_ops.py
"""预期差引擎的 Agent 接口：数值对比 / 层次上卷 / 时序变化。

设计原则（owner 定调）：标尺不预设——任何 LLM 抽出的 keyword 都可作标尺；
数据架构只负责承载与检索，对比与推理由 Agent 在调用时选定维度。

三个工具覆盖三类预期差：
  · compare_metric  —— 横向：不同公司 × 同一标尺（谁高谁低、差距多少）
  · rollup_metric   —— 层次：细粒度指标上卷到粗粒度（"高速通信线营收" ⊂ "营收"）
  · metric_trend    —— 纵向：同一公司 × 时间（数值/表述的递进与回退）
"""
from __future__ import annotations

import re
from typing import Annotated

from langchain_core.tools import tool

from app.core.database import async_session
from app.knowledge.linklayer.models import Keyword, Link
from app.reasoning.tools.knowledge.link_queries import run_async


async def _with_fresh_pool(coro):
    """在隔离 loop 内执行；结束后归还连接池，避免跨 loop 复用。

    全局 async engine 的连接池绑定创建它的 loop。工具的临时 loop 结束后，
    池中残留的连接会在下一次调用（新 loop）里报
    'got Future attached to a different loop'（实测 rollup_metric 踩坑）。
    故每次用完显式 dispose，让下次重开干净连接池。
    """
    from app.core.database import engine
    try:
        return await coro
    finally:
        await engine.dispose()


def _run_sync(coro):
    return run_async(_with_fresh_pool(coro))


_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")


def _to_float(value: str | None) -> float | None:
    """数值字符串 → float；带"以上/以下/约"等修饰时取首个数字。"""
    if value is None:
        return None
    m = _NUM_RE.search(str(value))
    return float(m.group()) if m else None


async def _collect_rows(dimension: str, scope: str | None, as_of: str | None, limit: int) -> list[dict]:
    """按标尺（dimension × scope）收集带数值的 link 行。"""
    from sqlalchemy import and_, func, or_, select

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
            # 标尺匹配：精确命中 OR 沿 parent 上卷（细粒度指标归属到粗粒度标尺）。
            # 例：查"营业收入"时应同时命中"营业收入（2024年3月31日）"这类子指标，
            # 否则粗粒度标尺查不到值（实测 missing=86 全因此）。
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
        stmt = stmt.where(Link.evidence_id.in_(_scope_evidence_subquery(scope)))
    cutoff = _parse_cutoff(as_of)
    if cutoff is not None:
        stmt = stmt.where(Link.published_at <= cutoff)
    # 只取有数值的行：本工具是「数值对比」，无值行只会挤占 limit。
    # 期望差/无数值场景应由 metric_trend + fetch_evidence 处理。
    stmt = stmt.where(Link.metric_value.is_not(None))
    # 值优先 + 时间倒序：确保每主体拿到最新且有值的那条
    stmt = stmt.order_by(Link.metric_value.is_(None), Link.published_at.desc()).limit(limit * 20)

    async with async_session() as session:
        rows = (await session.execute(stmt)).all()
        # 主体归属（hint 优先）
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


@tool
def compare_metric(
    dimension: Annotated[str, "对比标尺：任意指标名，如 '毛利率'、'营业收入'、'高速通信线营业收入'"],
    scope: Annotated[str | None, "限定范围（产品/主题），如 '硅片'；不填则不限"] = None,
    as_of: Annotated[str | None, "时点（ISO 日期），只看该日之前的证据"] = None,
    top_k: Annotated[int, "返回主体数上限"] = 30,
) -> dict:
    """横向预期差：同一标尺下，不同公司的数值对比与排名。

    返回按数值降序排列的主体列表（含单位/期间），可直接看出谁高谁低、差距多少。
    若同一主体有多条记录，取最新一条。数值缺失者单列 missing_value。
    """
    rows = _run_sync(_collect_rows(dimension, scope, as_of, top_k))

    # 按主体取最新一条（有数值者优先）
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


@tool
def rollup_metric(
    parent: Annotated[str, "上卷目标（粗粒度标尺），如 '营收'、'毛利率'"],
    scope: Annotated[str | None, "限定范围（产品/主题）"] = None,
    top_k: Annotated[int, "返回子指标数上限"] = 30,
) -> dict:
    """层次上卷：把细粒度指标聚合到粗粒度标尺下。

    细粒度指标（如"高速通信线营业收入"、"汽车电子毛利率"）挂在其标准维度
    （parent_keyword_id）下。本工具列出某粗粒度标尺下的全部子指标及其命中情况，
    用于"这个大盘子由哪些细分构成"的分析。
    """
    async def _run() -> list[dict]:
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
                return []
            child_stmt = (
                select(Keyword.norm_text, func.count(Link.evidence_id).label("n"))
                .select_from(Keyword)
                .outerjoin(Link, Link.keyword_id == Keyword.keyword_id)
                .where(Keyword.layer == "dimension", Keyword.parent_keyword_id == parent_kw[0])
                .group_by(Keyword.norm_text)
                .order_by(func.count(Link.evidence_id).desc())
                .limit(top_k)
            )
            return [
                {"child_metric": r[0], "evidence_count": r[1]}
                for r in (await session.execute(child_stmt)).all()
            ]

    children = _run_sync(_run())
    return {
        "parent": parent,
        "scope": scope,
        "children": children,
        "count": len(children),
        "note": "child_metric 是细粒度标尺；可用 compare_metric 逐个深入",
    }


@tool
def metric_trend(
    subject: Annotated[str, "主体：公司 ts_code 或名称"],
    dimension: Annotated[str | None, "标尺：指标名；不填则取该主体全部指标"] = None,
    limit: Annotated[int, "返回记录数上限"] = 50,
) -> dict:
    """纵向预期差：同一主体在时间轴上的数值/表述变化。

    返回按时间正序排列的记录（含数值、单位、期间、证据 ID），
    供判断递进（progression）/回退（regression）/分歧（divergence）。
    无数值时也应结合 fetch_evidence 读取原文表述的变化。
    """
    async def _run() -> list[dict]:
        from sqlalchemy import and_, select

        async with async_session() as session:
            subj_kw = (
                await session.execute(
                    select(Keyword.keyword_id).where(
                        Keyword.layer == "subject", Keyword.norm_text == subject
                    )
                )
            ).first()
            if not subj_kw:
                return []
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
            return [
                {
                    "metric": r[0], "value": r[1], "unit": r[2], "period": r[3],
                    "published_at": str(r[4]) if r[4] else None, "evidence_id": r[5],
                }
                for r in (await session.execute(stmt)).all()
            ]

    rows = _run_sync(_run())
    return {
        "subject": subject,
        "dimension": dimension,
        "count": len(rows),
        "timeline": rows,
        "note": "按时间正序；数值变化可直接看趋势，表述变化需 fetch_evidence 读原文",
    }
