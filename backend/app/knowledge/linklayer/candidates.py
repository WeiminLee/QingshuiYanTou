# backend/app/knowledge/linklayer/candidates.py
"""机械候选观察（spec §4.3 修订 1）：批量侧零 LLM 的广度触发器。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.knowledge.linklayer.ledger_models import Watermark, make_obs_id, normalize_scope
from app.knowledge.linklayer.models import Keyword, Link
from app.signals.models import Signal


def _stage_level(cand: dict) -> int:
    """level 缺失按 0 处理（阶梯 level 从 1 起）。"""
    return cand.get("stage_level") or 0


def _guess_scope(links: list[dict], stage: dict) -> str | None:
    """scope 关键字取同 evidence 的首个（可空）。"""
    scopes = [l["norm_text"] for l in links if l["layer"] == "scope"]
    return scopes[0] if scopes else None


def build_candidates_from_links(links: list[dict], evidence_text: str) -> list[dict]:
    """从单条 evidence 的 link 集合组装候选观察：subject × stage 共现。

    obs_id = hash(evidence × subject × dimension × scope)，同一 obs_id 的
    多条 stage 共现只产一条候选（保留 level 最高者）——观察是"这条证据
    说了什么"，不是"说了几次"。evidence_text 为 METRIC 邻近提取预留。
    """
    subjects = [l for l in links if l["layer"] == "subject"]
    stages = [l for l in links if l["layer"] == "stage"]
    by_obs: dict[str, dict] = {}
    for subj in subjects:
        for stage in stages:
            scope = _guess_scope(links, stage)
            obs_id = make_obs_id(
                links[0]["evidence_id"], subj["norm_text"],
                stage.get("dimension") or stage["norm_text"], scope,
            )
            cand = {
                "obs_id": obs_id,
                "subject_ts_code": subj["norm_text"],
                "dimension": stage.get("dimension") or stage["norm_text"],
                "dimension_scope": scope,
                "stage_raw": stage["norm_text"],
                "stage_level": stage.get("level"),
                "evidence_id": links[0]["evidence_id"],
                "published_at": links[0].get("published_at"),
                "status": "candidate",
            }
            prev = by_obs.get(obs_id)
            if prev is None or _stage_level(cand) > _stage_level(prev):
                by_obs[obs_id] = cand
    return list(by_obs.values())


def _stage_metadata(keyword: Keyword) -> tuple[str | None, int | None]:
    """从 keyword 行内 aliases JSONB 读 stage 元数据 (dimension, level)。

    支持两种形状：{"dimension": ..., "level": ...} 或
    [{"dimension": ..., "level": ...}]（aliases 声明为 list）。
    """
    aliases = getattr(keyword, "aliases", None)
    payloads: list
    if isinstance(aliases, dict):
        payloads = [aliases]
    elif isinstance(aliases, list):
        payloads = [a for a in aliases if isinstance(a, dict)]
    else:
        payloads = []
    for payload in payloads:
        if payload.get("dimension") and payload.get("level") is not None:
            return payload["dimension"], payload["level"]
    return None, None


def _vocab_stage_lookup(norm_text: str, vocab) -> tuple[str | None, int | None]:
    """词表回填兜底：stage 词 → (dimension, level)。"""
    for name, dim in vocab.dimensions.items():
        for stage in dim.stages:
            if norm_text in stage["words"]:
                return name, stage["level"]
    return None, None


async def generate_candidates(evidence_id: str, session) -> list[dict]:
    """读取 link 表，生成候选观察（不写库——由 emit 阶段统一写）。

    stage 关键字的 dimension/level 优先读 keyword 行内元数据（aliases
    JSONB），缺失时由阶梯词表回填兜底。
    """
    from app.knowledge.linklayer.dictionaries import load_vocabulary

    vocab = load_vocabulary()
    rows = (await session.execute(
        select(Keyword, Link).join(Link, Link.keyword_id == Keyword.keyword_id)
        .where(Link.evidence_id == evidence_id)
    )).all()
    links = []
    for k, l in rows:
        dimension, level = k.norm_text, None
        if k.layer == "stage":
            dimension, level = _stage_metadata(k)
            if dimension is None:
                dimension, level = _vocab_stage_lookup(k.norm_text, vocab)
            if dimension is None:
                dimension = k.norm_text
        links.append({
            "layer": k.layer,
            "norm_text": k.norm_text,
            "dimension": dimension,
            "level": level,
            "evidence_id": l.evidence_id,
            "published_at": str(l.published_at) if l.published_at else None,
        })
    return build_candidates_from_links(links, "")


def _signal_values_from_candidate(cand: dict) -> dict:
    """机械候选 → 雷达 Signal 字段映射（低置信线索，source_type=link_layer）。"""
    level = cand["stage_level"]
    return {
        "signal_id": f"LL:{cand['obs_id']}",
        "source_type": "link_layer",
        "source_id": cand["evidence_id"],
        "subject_name": cand["subject_ts_code"],
        "subject_type": "company",
        "signal_type": cand["dimension"],
        "polarity": "positive",
        "strength": min(100, level * 15),
        "confidence": 0.5,  # 机械候选=低置信线索
        "freshness_score": 0,
        "value_score": level * 10,
        "summary": f"[{cand['dimension']}] {cand.get('stage_raw')}（候选 level={level}）",
    }


def _parse_published_at(value) -> datetime | None:
    """published_at 字符串/naive datetime → aware datetime；无效返回 None。"""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.astimezone()
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.astimezone()


async def persist_candidates(candidates: list[dict], session) -> int:
    """候选观察落库（written_by=pipeline, status=candidate）。

    obs_id 冲突静默跳过（do nothing），返回实际新插入数。
    """
    from app.knowledge.linklayer.ledger_models import Observation

    persisted = 0
    for cand in candidates:
        stmt = (
            pg_insert(Observation)
            .values(
                obs_id=cand["obs_id"],
                subject_ts_code=cand["subject_ts_code"],
                subject_name=cand["subject_ts_code"],
                dimension=cand["dimension"],
                dimension_scope=cand.get("dimension_scope"),
                stage_raw=cand.get("stage_raw"),
                stage_level=cand.get("stage_level"),
                evidence_id=cand["evidence_id"],
                published_at=_parse_published_at(cand.get("published_at")),
                written_by="pipeline",
                status="candidate",
            )
            .on_conflict_do_nothing(index_elements=["obs_id"])
            .returning(Observation.id)
        )
        inserted = (await session.execute(stmt)).all()
        persisted += len(inserted)
    return persisted


async def emit_radar_signals(candidates: list[dict], session) -> int:
    """水位线对比（spec §4.3 修订 1）：level > 水位线 → 写 Signal + 推进水位线。

    level == 水位线 → 不产信号（旧闻去噪）；水位线按 (subject, dimension,
    scope) 三键匹配（无 scope 归一化为哨兵空串），推进走 advance_watermark
    （GREATEST 只升不降）。signal_id = "LL:" + obs_id 确定性生成，冲突时
    静默跳过（RETURNING 计数）。
    """
    from app.knowledge.linklayer.ledger_models import advance_watermark

    emitted = 0
    for cand in candidates:
        level = cand.get("stage_level")
        if not level:
            continue
        wm = (await session.execute(
            select(Watermark).where(
                Watermark.subject_ts_code == cand["subject_ts_code"],
                Watermark.dimension == cand["dimension"],
                Watermark.dimension_scope == normalize_scope(cand.get("dimension_scope")),
            )
        )).scalar_one_or_none()
        max_level = wm.max_level if wm and wm.max_level is not None else 0
        if level <= max_level:
            continue
        stmt = (
            pg_insert(Signal)
            .values(**_signal_values_from_candidate(cand))
            .on_conflict_do_nothing(index_elements=["signal_id"])
            .returning(Signal.id)
        )
        inserted = (await session.execute(stmt)).all()
        emitted += len(inserted)
        await advance_watermark(session, cand["subject_ts_code"], cand["dimension"], cand.get("dimension_scope"), level)
    await session.commit()
    return emitted
