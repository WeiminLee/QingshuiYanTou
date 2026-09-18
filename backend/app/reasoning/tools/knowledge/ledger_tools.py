# backend/app/reasoning/tools/knowledge/ledger_tools.py
"""
判断台账工具 — write_observation / write_finding / watermark。

SearchAtlas 硬证据闸门（spec §4.3 修订 3）：所有写回必须句级锚定真实
evidence（evidence_id 存在 + span 在文本范围内），否则拒绝写入。
write_observation 顺带推进水位线（spec §4.3：水位线按写入维护）。

底层 async 写入通过 run_async 桥接（与 announcement/kline 等工具一致）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from langchain_core.tools import tool
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.reasoning.tools._async_runner import run_async


async def validate_supports(supports: list[dict], session) -> list[str]:
    """SearchAtlas 硬证据闸门：每个支撑必须真实存在且 span 在文本范围内。"""
    from app.knowledge.evidence_service import EvidenceService

    errors: list[str] = []
    svc = EvidenceService()
    for sup in supports:
        if not sup.get("evidence_id"):
            errors.append(f"缺少 evidence_id: {sup}")
            continue
        ev = await svc.get_evidence(sup["evidence_id"])
        if not ev:
            errors.append(f"evidence 不存在: {sup['evidence_id']}")
            continue
        text = ev.get("text_excerpt") or ""
        span_start, span_end = sup.get("span_start", 0), sup.get("span_end", 0)
        if span_start < 0 or span_end > len(text) or span_start >= span_end:
            errors.append(f"span 越界: {sup['evidence_id']} [{span_start}:{span_end}]")
    return errors


def _watermark_dict(wm) -> dict:
    from app.knowledge.linklayer.ledger_models import watermark_dict

    return watermark_dict(wm)


async def _advance_watermark(session, subject_ts_code: str, dimension: str, dimension_scope: str | None, level) -> dict:
    """水位线推进——共享 upsert（机械候选雷达链路同用），语义见 ledger_models.advance_watermark。"""
    from app.knowledge.linklayer.ledger_models import advance_watermark

    return await advance_watermark(session, subject_ts_code, dimension, dimension_scope, level)


async def save_observation(
    session,
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
    """写回观察（agent 确认 → status=verified）并推进水位线。校验失败返回 ok=False + errors。"""
    from app.knowledge.linklayer.ledger_models import Observation, make_obs_id

    errors = await validate_supports(
        [{"evidence_id": evidence_id, "span_start": span_start, "span_end": span_end}], session
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
    await session.execute(
        pg_insert(Observation).values(**values).on_conflict_do_update(index_elements=["obs_id"], set_=updatable)
    )
    watermark = await _advance_watermark(session, subject_ts_code, dimension, dimension_scope, stage_level)
    await session.commit()
    return {"ok": True, "obs_id": obs_id, "status": "verified", "watermark": watermark}


async def read_watermark(subject_ts_code: str, dimension: str, dimension_scope: str | None, session) -> dict:
    """读取水位线：(主体×维度[×scope]) 的历史最高 level。"""
    from app.knowledge.linklayer.ledger_models import Watermark, normalize_scope

    wm = (await session.execute(
        select(Watermark).where(
            Watermark.subject_ts_code == subject_ts_code,
            Watermark.dimension == dimension,
            Watermark.dimension_scope == normalize_scope(dimension_scope),
        )
    )).scalar_one_or_none()
    return {"found": wm is not None, "watermark": _watermark_dict(wm)}


async def save_finding(
    session,
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
    """写回判断（supports 必须句级锚定）。校验失败返回 ok=False + errors。"""
    from app.knowledge.linklayer.ledger_models import Finding, make_finding_id

    if not supports:
        return {"ok": False, "errors": ["supports 为空：判断必须句级锚定至少一条真实证据"]}
    errors = await validate_supports(supports, session)
    if errors:
        return {"ok": False, "errors": errors}

    to_level = int((to_state or {}).get("level") or 0)
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
        "confidence": confidence,
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
    await session.execute(
        pg_insert(Finding).values(**values).on_conflict_do_update(
            index_elements=["finding_id"], set_=updatable
        )
    )
    await session.commit()
    return {"ok": True, "finding_id": finding_id}


@tool("write_observation")
def write_observation_tool(
    subject_ts_code: Annotated[str, "主体 ts_code，如 003026.SZ"],
    dimension: Annotated[str, "维度名，如 产线进展/客户认证/毛利率"],
    evidence_id: Annotated[str, "支撑证据 ID"],
    span_start: Annotated[int, "句级锚点起始偏移（含）"],
    span_end: Annotated[int, "句级锚点结束偏移（不含）"],
    stage_raw: Annotated[str | None, "阶梯原始措辞（verbatim），如 增产上量"] = None,
    stage_level: Annotated[int | None, "阶梯归一化 level（1 起）"] = None,
    dimension_scope: Annotated[str | None, "细化范围（如 8英寸抛光硅片）；可空"] = None,
    subject_name: Annotated[str | None, "主体名称；缺省用 ts_code"] = None,
    event_date: Annotated[str | None, "事件日期 YYYY-MM-DD；可空"] = None,
    published_at: Annotated[str | None, "披露时间（ISO 格式）；可空"] = None,
) -> dict:
    """写回观察（task-time 确认，status=verified）并推进水位线；evidence+span 句级锚定为硬闸门。"""
    from app.core.database import async_session

    async def _run():
        async with async_session() as session:
            return await save_observation(
                session,
                subject_ts_code=subject_ts_code,
                dimension=dimension,
                evidence_id=evidence_id,
                span_start=span_start,
                span_end=span_end,
                stage_raw=stage_raw,
                stage_level=stage_level,
                dimension_scope=dimension_scope,
                subject_name=subject_name,
                event_date=event_date,
                published_at=published_at,
            )

    return run_async(_run())


@tool("write_finding")
def write_finding_tool(
    subject_ts_code: Annotated[str, "主体 ts_code，如 003026.SZ"],
    dimension: Annotated[str, "维度名，如 产线进展"],
    kind: Annotated[str, "判断类型：progression|regression|new_event|association|divergence"],
    judgment: Annotated[str, "判断结论文字"],
    supports: Annotated[list[dict], "支撑锚点列表，每项 {evidence_id, span_start, span_end, obs_id?}，至少 1 条"],
    dimension_scope: Annotated[str | None, "细化范围（如 8英寸抛光硅片）；可空"] = None,
    from_state: Annotated[dict | None, "来源状态 {stage, level, value, obs_id, date}；可空"] = None,
    to_state: Annotated[dict | None, "目标状态 {stage, level, value, obs_id, date}；可空"] = None,
    delta: Annotated[dict | None, "变化量 {stage_delta, value_delta, pct}；可空"] = None,
    contradicts: Annotated[list | None, "矛盾证据列表；可空"] = None,
    confidence: Annotated[float | None, "置信度 0-1；可空"] = None,
    supersedes: Annotated[str | None, "被本判断取代的 finding_id；可空"] = None,
    created_by: Annotated[dict | None, "来源信息 {task_id, agent_run_id, model, prompt_version}；可空"] = None,
) -> dict:
    """写回判断（递进/恶化/新事件/关联/矛盾）：supports 必须句级锚定真实 evidence，否则拒绝写入。"""
    from app.core.database import async_session

    async def _run():
        async with async_session() as session:
            return await save_finding(
                session,
                subject_ts_code=subject_ts_code,
                dimension=dimension,
                kind=kind,
                judgment=judgment,
                supports=supports,
                dimension_scope=dimension_scope,
                from_state=from_state,
                to_state=to_state,
                delta=delta,
                contradicts=contradicts,
                confidence=confidence,
                supersedes=supersedes,
                created_by=created_by,
            )

    return run_async(_run())


@tool("watermark")
def watermark_tool(
    subject_ts_code: Annotated[str, "主体 ts_code，如 003026.SZ"],
    dimension: Annotated[str, "维度名，如 产线进展"],
    dimension_scope: Annotated[str | None, "细化范围；可空"] = None,
) -> dict:
    """查水位线：该 (主体×维度[×scope]) 历史最高 level——判断"这是不是新台阶"的依据。"""
    from app.core.database import async_session

    async def _run():
        async with async_session() as session:
            return await read_watermark(subject_ts_code, dimension, dimension_scope, session)

    return run_async(_run())
