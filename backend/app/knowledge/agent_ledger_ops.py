# backend/app/knowledge/agent_ledger_ops.py
"""判断台账共享服务层（findings 判断台账设计草案 §4-§6 的 agent 工具面）。

三层：observation（append-only 观察）/ finding（判断，supports 句级锚定）/
watermark（(主体,维度) 水位线，advance_watermark 只升不降）。
写入幂等：obs_id / finding_id 为内容哈希，重跑合并而非重复建。

写路径硬闸门（草案 §1.4）：evidence_id 必须存在且 span 落在 text_excerpt 内，
校验失败返回 {"ok": False, "errors": [...]} 而非抛 4xx——沿用旧台账工具面惯例。
HTTP 面见 app/knowledge/api/agent_ledger.py；MCP 第一期只读，写工具不经 MCP。
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.database import async_session
from app.knowledge.linklayer.ledger_models import (
    SCOPE_SENTINEL,
    Finding,
    Observation,
    Watermark,
    advance_watermark,
    advance_watermark_numeric,
    make_finding_id,
    make_obs_id,
    normalize_scope,
    watermark_dict,
)
from app.knowledge.linklayer.queries import build_subject_index

logger = logging.getLogger(__name__)

FINDING_KINDS = ("progression", "regression", "new_event", "association", "divergence")


async def validate_supports(supports: list[dict]) -> list[str]:
    """硬证据闸门：每个支撑必须真实存在且 span 在文本范围内。"""
    from app.knowledge.evidence_service import EvidenceService

    errors: list[str] = []
    svc = EvidenceService()
    for sup in supports:
        evidence_id = sup.get("evidence_id")
        if not evidence_id:
            errors.append(f"缺少 evidence_id: {sup}")
            continue
        ev = await svc.get_evidence(evidence_id)
        if not ev:
            errors.append(f"evidence 不存在: {evidence_id}")
            continue
        text = ev.get("text_excerpt") or ""
        span_start, span_end = sup.get("span_start", 0), sup.get("span_end", 0)
        if span_start < 0 or span_end > len(text) or span_start >= span_end:
            errors.append(f"span 越界: {evidence_id} [{span_start}:{span_end}] 文本长度 {len(text)}")
    return errors


def _observation_dict(row: Observation) -> dict:
    return {
        "obs_id": row.obs_id,
        "subject_ts_code": row.subject_ts_code,
        "subject_name": row.subject_name,
        "dimension": row.dimension,
        "dimension_scope": row.dimension_scope or None,
        "stage_raw": row.stage_raw,
        "stage_level": row.stage_level,
        "metric_value": row.metric_value,
        "evidence_id": row.evidence_id,
        "span_start": row.span_start,
        "span_end": row.span_end,
        "event_date": row.event_date.isoformat() if row.event_date else None,
        "published_at": row.published_at.isoformat() if row.published_at else None,
        "written_by": row.written_by,
        "status": row.status,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _finding_dict(row: Finding) -> dict:
    return {
        "finding_id": row.finding_id,
        "kind": row.kind,
        "subject_ts_code": row.subject_ts_code,
        "dimension": row.dimension,
        "dimension_scope": row.dimension_scope or None,
        "from_state": row.from_state,
        "to_state": row.to_state,
        "delta": row.delta,
        "supports": row.supports,
        "support_count": len(row.supports or []),
        "contradicts": row.contradicts,
        "judgment": row.judgment,
        "confidence": row.confidence,
        "status": row.status,
        "supersedes": row.supersedes,
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


async def _numeric_novelty(
    session,
    subject_ts_code: str,
    dimension: str,
    dimension_scope: str | None,
    num: float,
    period: str | None,
    self_obs_id: str,
) -> dict:
    """数值新颖度判定（草案 §3）：环比 + 是否超出历史区间；幂等重写不自比。"""
    import math

    filters = [
        Observation.subject_ts_code == subject_ts_code,
        Observation.dimension == dimension,
        Observation.obs_id != self_obs_id,
    ]
    if dimension_scope:
        filters.append(Observation.dimension_scope == dimension_scope)
    else:
        filters.append(
            (Observation.dimension_scope.is_(None))
            | (Observation.dimension_scope == SCOPE_SENTINEL)
        )
    rows = (
        await session.execute(
            select(Observation.metric_value)
            .where(*filters)
            .order_by(Observation.published_at.desc().nullslast(), Observation.created_at.desc())
        )
    ).scalars().all()
    nums: list[float] = []
    last_num: float | None = None
    last_period: str | None = None
    for mv in rows:
        if not isinstance(mv, dict):
            continue
        try:
            v = float(mv.get("num"))
        except (TypeError, ValueError):
            continue
        if math.isnan(v) or math.isinf(v):
            continue
        nums.append(v)
        if last_num is None:
            last_num = v
            last_period = mv.get("period")
    if not nums:
        return {
            "is_new_high": True,
            "is_new_low": True,
            "is_new_extreme": True,
            "prev_num": None,
            "delta": None,
            "delta_pct": None,
            "same_period_restated": False,
            "numeric_history_count": 0,
        }
    hist_high, hist_low = max(nums), min(nums)
    is_new_high = num > hist_high
    is_new_low = num < hist_low
    delta = num - last_num if last_num is not None else None
    delta_pct = (delta / last_num * 100) if (last_num not in (None, 0) and delta is not None) else None
    return {
        "is_new_high": is_new_high,
        "is_new_low": is_new_low,
        "is_new_extreme": is_new_high or is_new_low,
        "prev_num": last_num,
        "delta": delta,
        "delta_pct": delta_pct,
        "same_period_restated": bool(period and last_period and period == last_period),
        "numeric_history_count": len(nums),
        "numeric_note": "区间外=数值新台阶；delta 为相对上一披露值的环比，方向语义由指标定",
    }


async def save_observation(
    *,
    subject_ts_code: str,
    dimension: str,
    evidence_id: str,
    span_start: int,
    span_end: int,
    stage_raw: str | None = None,
    stage_level: int | None = None,
    dimension_scope: str | None = None,
    subject_name: str | None = None,
    event_date: str | None = None,
    published_at: str | None = None,
    metric_value: dict | None = None,
) -> dict:
    """写回观察（agent → status=verified）并推进水位线（只升不降）。"""
    errors = await validate_supports(
        [{"evidence_id": evidence_id, "span_start": span_start, "span_end": span_end}]
    )

    parsed_event_date = None
    if event_date:
        try:
            parsed_event_date = datetime.fromisoformat(str(event_date)).date()
        except ValueError:
            errors.append(f"event_date 无法解析: {event_date}")
    parsed_published_at = None
    if published_at:
        try:
            parsed_published_at = datetime.fromisoformat(str(published_at))
        except ValueError:
            errors.append(f"published_at 无法解析: {published_at}")
    if errors:
        return {"ok": False, "errors": errors}

    obs_id = make_obs_id(evidence_id, subject_ts_code, dimension, dimension_scope)
    values = {
        "obs_id": obs_id,
        "subject_ts_code": subject_ts_code,
        "subject_name": subject_name or subject_ts_code,
        "dimension": dimension,
        "dimension_scope": dimension_scope,
        "stage_raw": stage_raw,
        "stage_level": stage_level,
        "metric_value": metric_value,
        "evidence_id": evidence_id,
        "span_start": span_start,
        "span_end": span_end,
        "event_date": parsed_event_date,
        "published_at": parsed_published_at,
        "written_by": "agent",
        "status": "verified",
    }
    updatable = {
        k: values[k]
        for k in (
            "subject_name", "dimension_scope", "stage_raw", "stage_level", "metric_value",
            "span_start", "span_end", "event_date", "published_at", "written_by", "status",
        )
    }
    numeric_result: dict | None = None
    watermark: dict = {}
    is_new_level = False
    async with async_session() as session:
        await session.execute(
            pg_insert(Observation)
            .values(**values)
            .on_conflict_do_update(index_elements=["obs_id"], set_=updatable)
        )
        if stage_level is not None:
            watermark = await advance_watermark(session, subject_ts_code, dimension, dimension_scope, stage_level)
            is_new_level = bool(watermark and watermark.get("max_level") == stage_level)
        else:
            mv = metric_value or {}
            try:
                num = float(mv.get("num"))
            except (TypeError, ValueError):
                num = None
            if num is not None:
                numeric_result = await _numeric_novelty(
                    session, subject_ts_code, dimension, dimension_scope, num,
                    mv.get("period"), obs_id,
                )
                watermark = await advance_watermark_numeric(
                    session, subject_ts_code, dimension, dimension_scope, num, mv.get("period")
                )
        await session.commit()
    result = {"ok": True, "obs_id": obs_id, "status": "verified", "is_new_level": is_new_level, "watermark": watermark}
    if numeric_result is not None:
        result.update(numeric_result)
        result["is_new_signal"] = bool(numeric_result.get("is_new_extreme"))
    else:
        result["is_new_signal"] = is_new_level
    return result


def _confidence_from_support_count(n: int) -> float:
    """无显式置信度时按证据锚点数推断：锚点越多越稳，但封顶不装满。

    一条锚点只给 0.50，别让单条证据装成很确信。
    """
    return round(min(0.85, 0.38 + n * 0.12), 2)


async def save_finding(
    *,
    subject_ts_code: str,
    dimension: str,
    kind: str,
    judgment: str,
    supports: list[dict],
    dimension_scope: str | None = None,
    from_state: dict | None = None,
    to_state: dict | None = None,
    delta: dict | None = None,
    contradicts: list | None = None,
    confidence: float | None = None,
    supersedes: str | None = None,
    created_by: dict | None = None,
) -> dict:
    """写回判断。supports 必须句级锚定；同 (主体,维度,to_level,支撑集) 重跑幂等合并。"""
    if kind not in FINDING_KINDS:
        return {"ok": False, "errors": [f"kind 非法: {kind}，允许 {FINDING_KINDS}"]}
    if not supports:
        return {"ok": False, "errors": ["supports 为空：判断必须句级锚定至少一条真实证据"]}
    if not judgment.strip():
        return {"ok": False, "errors": ["judgment 为空：判断必须给出结论文字"]}
    errors = await validate_supports(supports)
    if errors:
        return {"ok": False, "errors": errors}
    from app.knowledge.retrieval.entailment import entailment_errors

    mismatch = await entailment_errors(
        dimension=dimension,
        judgment=judgment,
        to_state=to_state,
        supports=supports,
    )
    if mismatch:
        return {"ok": False, "errors": mismatch}

    to_level = int((to_state or {}).get("level") or 0)
    resolved_confidence = confidence if confidence is not None else _confidence_from_support_count(len(supports))
    obs_ids = ",".join(sorted({str(s.get("obs_id") or s.get("evidence_id")) for s in supports}))
    finding_id = make_finding_id(subject_ts_code, dimension, to_level, obs_ids)
    values = {
        "finding_id": finding_id,
        "kind": kind,
        "subject_ts_code": subject_ts_code,
        "dimension": dimension,
        "dimension_scope": dimension_scope,
        "from_state": from_state,
        "to_state": to_state,
        "delta": delta,
        "supports": supports,
        "contradicts": contradicts or [],
        "judgment": judgment,
        "confidence": resolved_confidence,
        "status": "candidate",
        "supersedes": supersedes,
        "created_by": created_by,
    }
    updatable = {
        k: values[k]
        for k in (
            "dimension_scope", "from_state", "to_state", "delta", "supports", "contradicts",
            "judgment", "confidence", "supersedes", "created_by",
        )
    }
    async with async_session() as session:
        if supersedes:
            target = (
                await session.execute(
                    select(Finding).where(Finding.finding_id == supersedes)
                )
            ).scalar_one_or_none()
            if target is None:
                await session.rollback()
                return {"ok": False, "errors": [f"supersedes 目标不存在: {supersedes}"]}
            if target.subject_ts_code != subject_ts_code or target.dimension != dimension:
                await session.rollback()
                return {
                    "ok": False,
                    "errors": [
                        f"supersedes 跨主体/维度取代拒绝: "
                        f"目标 {target.subject_ts_code}/{target.dimension} vs 本次 {subject_ts_code}/{dimension}"
                    ],
                }
            if target.status == "superseded":
                await session.rollback()
                return {"ok": False, "errors": [f"supersedes 目标已被取代: {supersedes}"]}
        await session.execute(
            pg_insert(Finding)
            .values(**values)
            .on_conflict_do_update(index_elements=["finding_id"], set_=updatable)
        )
        if supersedes:
            await session.execute(
                update(Finding).where(Finding.finding_id == supersedes).values(status="superseded")
            )
        await session.commit()
    return {"ok": True, "finding_id": finding_id, "status": "candidate", "supersedes": supersedes}


async def read_watermark(*, subject_ts_code: str, dimension: str, dimension_scope: str | None = None) -> dict:
    """读取水位线：(主体×维度[×scope]) 的历史最高 level。"""
    scope = normalize_scope(dimension_scope)
    async with async_session() as session:
        wm = (
            await session.execute(
                select(Watermark).where(
                    Watermark.subject_ts_code == subject_ts_code,
                    Watermark.dimension == dimension,
                    Watermark.dimension_scope == scope,
                )
            )
        ).scalar_one_or_none()
    return {"found": wm is not None, "watermark": watermark_dict(wm)}


async def history_findings(
    *,
    subject: str,
    dimension: str | None = None,
    scope: str | None = None,
    before: str | None = None,
    limit: int = 50,
) -> dict:
    """按 (主体[, 维度]) 拉取观察 + 判断时间线，附当前水位线。

    主体经 build_subject_index 别名归一（与 pull_history 一致）；
    无 scope 时同时命中 NULL 与哨兵空串（兼容流水线/旧数据两种写入形态）。
    """
    subject_index = await build_subject_index()
    subject_ts_code = subject_index.alias_to_norm.get(subject, subject)

    obs_filters = [Observation.subject_ts_code == subject_ts_code]
    find_filters = [Finding.subject_ts_code == subject_ts_code]
    if dimension:
        obs_filters.append(Observation.dimension == dimension)
        find_filters.append(Finding.dimension == dimension)
    if scope:
        obs_filters.append(Observation.dimension_scope == scope)
        find_filters.append(Finding.dimension_scope == scope)
    else:
        no_scope = (Observation.dimension_scope.is_(None)) | (Observation.dimension_scope == SCOPE_SENTINEL)
        obs_filters.append(no_scope)
        find_filters.append(
            (Finding.dimension_scope.is_(None)) | (Finding.dimension_scope == SCOPE_SENTINEL)
        )
    parsed_before = None
    if before:
        try:
            parsed_before = datetime.fromisoformat(str(before))
        except ValueError:
            return {"ok": False, "errors": [f"before 无法解析: {before}"]}
    if parsed_before:
        obs_filters.append(Observation.published_at < parsed_before)
        find_filters.append(Finding.created_at < parsed_before)

    async with async_session() as session:
        obs_rows = (
            await session.execute(
                select(Observation)
                .where(*obs_filters)
                .order_by(Observation.published_at.asc().nullslast(), Observation.created_at.asc())
                .limit(limit)
            )
        ).scalars().all()
        find_rows = (
            await session.execute(
                select(Finding)
                .where(*find_filters)
                .order_by(Finding.created_at.desc())
                .limit(limit)
            )
        ).scalars().all()
        wm = None
        if dimension:
            wm = (
                await session.execute(
                    select(Watermark).where(
                        Watermark.subject_ts_code == subject_ts_code,
                        Watermark.dimension == dimension,
                        Watermark.dimension_scope == normalize_scope(scope),
                    )
                )
            ).scalar_one_or_none()

    return {
        "subject_ts_code": subject_ts_code,
        "observations": [_observation_dict(r) for r in obs_rows],
        "findings": [_finding_dict(r) for r in find_rows],
        "watermark": watermark_dict(wm),
        "note": "observations 按 published_at 升序；findings 按创建时间倒序（最新判断在前）",
    }


async def search_findings(
    *,
    dimension: str | None = None,
    kind: str | None = None,
    status: str | None = None,
    since: str | None = None,
    limit: int = 50,
) -> dict:
    """跨主体扫描判断；默认排除 dismissed。"""
    filters: list[Any] = [Finding.status.notin_(("dismissed", "superseded"))]
    if dimension:
        filters.append(Finding.dimension == dimension)
    if kind:
        if kind not in FINDING_KINDS:
            return {"ok": False, "errors": [f"kind 非法: {kind}，允许 {FINDING_KINDS}"]}
        filters.append(Finding.kind == kind)
    if status:
        filters = [Finding.status == status]
    parsed_since = None
    if since:
        try:
            parsed_since = datetime.fromisoformat(str(since))
        except ValueError:
            return {"ok": False, "errors": [f"since 无法解析: {since}"]}
    if parsed_since:
        filters.append(Finding.created_at >= parsed_since)

    async with async_session() as session:
        rows = (
            await session.execute(
                select(Finding).where(*filters).order_by(Finding.created_at.desc()).limit(limit)
            )
        ).scalars().all()
    return {"items": [_finding_dict(r) for r in rows], "count": len(rows)}
