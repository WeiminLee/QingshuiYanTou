# backend/app/knowledge/linklayer/queries.py
"""链接层检索原语（spec §5.1）：时间线 / 双向引用 / 横截面 / 单跳聚合。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import and_, func, select
from sqlalchemy.orm import aliased

from app.core.database import async_session
from app.knowledge.linklayer.dict_match import build_subject_index
from app.knowledge.linklayer.models import Keyword, Link

# backlinks 每个 keyword 最多返回的关联 evidence 数（与 brief 的 .limit(50) 对齐）
MAX_RELATED_PER_KEYWORD = 50


def _parse_cutoff(value: str | datetime | None) -> datetime | None:
    """before/as_of 字符串 → datetime；None/空串返回 None，非法格式抛 ValueError。"""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError(f"无效的时间过滤参数: {value!r}") from exc


def build_pull_history_sql(
    subject: str, dimension: str | None = None, scope: str | None = None, before: str | None = None, limit: int = 100
):
    """构造时间线查询：subject 关键字 ∩ 可选 dimension/scope 关键字，按 published_at 倒序。

    返回 (stmt, params)，便于单测校验结构。norm_text 匹配用 keyword 表的
    display_text/aliases 兜底（如"中晶科技"未归一成 ts_code 时仍可命中）。
    dimension/scope 为 None 时跳过对应的交集子查询（不做过滤）。
    """
    stmt = (
        select(Link.evidence_id, Link.published_at)
        .select_from(Link)
        .join(Keyword, and_(Keyword.keyword_id == Link.keyword_id, Keyword.layer == "subject"))
        .where(Keyword.norm_text == subject)
    )
    if dimension:
        stmt = stmt.where(
            Link.evidence_id.in_(
                select(Link.evidence_id).where(
                    Link.keyword_id.in_(
                        select(Keyword.keyword_id).where(Keyword.layer == "dimension", Keyword.norm_text == dimension)
                    )
                )
            )
        )
    if scope:
        stmt = stmt.where(
            Link.evidence_id.in_(
                select(Link.evidence_id).where(
                    Link.keyword_id.in_(
                        select(Keyword.keyword_id).where(Keyword.layer == "scope", Keyword.norm_text == scope)
                    )
                )
            )
        )
    cutoff = _parse_cutoff(before)
    if cutoff is not None:
        stmt = stmt.where(Link.published_at < cutoff)
    # 同一 evidence 的同关键字多 span 会产生重复行，DISTINCT 在 SQL 侧先去重
    stmt = stmt.distinct().order_by(Link.published_at.desc()).limit(limit)
    return stmt, {"subject": subject, "dimension": dimension, "scope": scope}


async def pull_history(
    subject: str, dimension: str | None = None, scope: str | None = None, before: str | None = None, limit: int = 100
) -> dict:
    """时间线拉取：完整、有序、去重——判断任务的正门（spec §5.1 主原语）。

    dimension/scope 传 None 时不做交集过滤；link.published_at 缺失时回退
    evidence.publish_date，仍缺失则排序键按空串处理（不崩溃）。
    """
    from app.knowledge.evidence_service import EvidenceService

    # 1. 主体归一（"中晶科技" → ts_code）
    subject_index = await build_subject_index()
    norm = subject_index.alias_to_norm.get(subject, subject)
    async with async_session() as session:
        stmt, _ = build_pull_history_sql(norm, dimension, scope, before, limit)
        rows = (await session.execute(stmt)).all()
        matched: dict[str, list[str]] = {}
        if rows:
            kw_rows = (
                await session.execute(
                    select(Link.evidence_id, Keyword.norm_text)
                    .select_from(Link)
                    .join(Keyword, Keyword.keyword_id == Link.keyword_id)
                    .where(Link.evidence_id.in_({row[0] for row in rows}))
                )
            ).all()
            for evidence_id, norm_text in kw_rows:
                keywords = matched.setdefault(evidence_id, [])
                if norm_text not in keywords:
                    keywords.append(norm_text)

    svc = EvidenceService()
    items = []
    seen = set()
    for row in rows:
        evidence_id = row[0]
        if evidence_id in seen:
            continue
        seen.add(evidence_id)
        ev = await svc.get_evidence(evidence_id) or {}
        published = row[1] or ev.get("publish_date")
        items.append(
            {
                "evidence_id": evidence_id,
                "published_at": str(published) if published else None,
                "source_type": ev.get("source_type", ""),
                "source_name": ev.get("source_name", ""),
                "text_excerpt": ev.get("text_excerpt", ""),
                "matched_keywords": matched.get(evidence_id, []),
            }
        )
    items.sort(key=lambda x: x["published_at"] or "", reverse=True)
    return {"items": items, "count": len(items)}


async def backlinks(evidence_id: str) -> dict:
    """双向引用：evidence → 其全部关键字 → 各关键字下的其他 evidence。"""
    async with async_session() as session:
        kw_rows = (
            await session.execute(
                select(Keyword, Link)
                .select_from(Link)
                .join(Keyword, Keyword.keyword_id == Link.keyword_id)
                .where(Link.evidence_id == evidence_id)
            )
        ).all()
        keywords = [{"keyword_id": k.keyword_id, "layer": k.layer, "norm_text": k.norm_text} for k, _ in kw_rows]
        name_by_id = {k.keyword_id: k.norm_text for k, _ in kw_rows}
        related: dict[str, list[str]] = {norm: [] for norm in name_by_id.values()}
        if name_by_id:
            link_rows = (
                await session.execute(select(Link.keyword_id, Link.evidence_id).where(Link.keyword_id.in_(name_by_id)))
            ).all()
            for keyword_id, ev_id in link_rows:
                bucket = related[name_by_id[keyword_id]]
                if ev_id != evidence_id and len(bucket) < MAX_RELATED_PER_KEYWORD:
                    if ev_id not in bucket:
                        bucket.append(ev_id)
    return {"evidence_id": evidence_id, "keywords": keywords, "related": related}


def build_scan_dimension_sql(dimension: str, scope: str | None = None, as_of: str | None = None, limit: int = 50):
    """横截面查询（evidence 侧）：该维度（×可选 scope）的 DISTINCT evidence 集合。

    主体归属不在本查询内——evidence 的权威主体由 evidence.subject_hint（link.source='hint'）决定，
    scan_dimension 在本查询之后按 evidence 批量归属主体（hint 优先，任意 subject 链接兜底），
    避免年报前十大股东等共现主体污染归属。
    """
    stmt = (
        select(Link.evidence_id, func.max(Link.published_at).label("published_at"))
        .join(Keyword, and_(Keyword.keyword_id == Link.keyword_id, Keyword.layer == "dimension"))
        .where(Keyword.norm_text == dimension)
        .group_by(Link.evidence_id)
    )
    if scope:
        stmt = stmt.where(
            Link.evidence_id.in_(
                select(Link.evidence_id).where(
                    Link.keyword_id.in_(
                        select(Keyword.keyword_id).where(Keyword.layer == "scope", Keyword.norm_text == scope)
                    )
                )
            )
        )
    cutoff = _parse_cutoff(as_of)
    if cutoff is not None:
        stmt = stmt.having(func.max(Link.published_at) <= cutoff)
    stmt = stmt.having(func.max(Link.published_at).is_not(None)).order_by(
        func.max(Link.published_at).desc()
    ).limit(limit)
    return stmt, {"dimension": dimension, "scope": scope}


async def scan_dimension(
    dimension: str | None, scope: str | None = None, as_of: str | None = None, limit: int = 50
) -> dict:
    """横截面：该维度（×可选 scope）下，各主体的 evidence/数值观察。

    dimension=None 时（theme 类 gold 条目由向量通道负责，eval runner 会对 theme
    条目以 dimension=None 调入），链接层无横截面可扫，直接返回空结果 + note，
    不触碰数据库。
    """
    if not dimension:
        return {
            "dimension": dimension,
            "scope": scope,
            "items": [],
            "count": 0,
            "note": "dimension 未指定：theme 类查询由向量通道负责，链接层无横截面可扫",
        }
    async with async_session() as session:
        stmt, _ = build_scan_dimension_sql(dimension, scope, as_of, limit)
        rows = (await session.execute(stmt)).all()

    # 主体归属：hint（evidence 自报主体）优先，任意 subject 链接兜底
    evidence_ids = [r[0] for r in rows]
    hint_map, fallback_map = {}, {}
    if evidence_ids:
        subj_stmt = (
            select(Link.evidence_id, Keyword.norm_text, Link.source)
            .join(Keyword, and_(Keyword.keyword_id == Link.keyword_id, Keyword.layer == "subject"))
            .where(Link.evidence_id.in_(evidence_ids))
            .order_by(Link.evidence_id)
        )
        subj_rows = (await session.execute(subj_stmt)).all()
        for evid, norm, src in subj_rows:
            if src == "hint":
                hint_map.setdefault(evid, norm)
            fallback_map.setdefault(evid, norm)
    items = []
    for r in rows:
        evid = r[0]
        subject = hint_map.get(evid) or fallback_map.get(evid)
        if subject:
            items.append(
                {
                    "subject": subject,
                    "evidence_id": evid,
                    "published_at": str(r[1]) if r[1] else None,
                }
            )
    return {"dimension": dimension, "scope": scope, "items": items, "count": len(items)}


async def _cooccur_aggregate(anchor_layer: str, target_layer: str, anchor_norm: str, top_k: int) -> list[dict]:
    """单跳聚合通用骨架：anchor 关键字 → 同 evidence 的 target 层关键字聚合。"""
    async with async_session() as session:
        anchor_sub = (
            select(Keyword.keyword_id)
            .where(Keyword.layer == anchor_layer, Keyword.norm_text == anchor_norm)
            .scalar_subquery()
        )
        evidence_sub = select(Link.evidence_id).where(Link.keyword_id.in_(anchor_sub))
        mention_count = func.count(Link.evidence_id).label("mention_count")
        last_seen = func.max(Link.published_at).label("last_seen")
        stmt = (
            select(Keyword.norm_text, mention_count, last_seen)
            .select_from(Keyword)
            .join(Link, Link.keyword_id == Keyword.keyword_id)
            .where(Link.evidence_id.in_(evidence_sub), Keyword.layer == target_layer)
            .group_by(Keyword.norm_text)
            .order_by(mention_count.desc())
            .limit(top_k)
        )
        rows = (await session.execute(stmt)).all()
    return [{"norm_text": r[0], "mention_count": r[1], "last_seen": str(r[2]) if r[2] else None} for r in rows]


async def lookup_products(company: str, top_k: int = 20) -> list[dict]:
    """公司有哪些产品（spec §5.4 单跳聚合）。company 须为归一化后的 subject norm（如 ts_code）。"""
    return await _cooccur_aggregate("subject", "scope", company, top_k)


async def lookup_players(keyword_norm_text: str, top_k: int = 20) -> list[dict]:
    """某产品/关键字下的玩家有哪些（传导挖掘入口）。"""
    return await _cooccur_aggregate("scope", "subject", keyword_norm_text, top_k)
