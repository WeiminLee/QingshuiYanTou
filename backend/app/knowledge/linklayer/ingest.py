# backend/app/knowledge/linklayer/ingest.py
"""链接层入库管线：dict match + LLM 浅提取 → 归一化 → keyword/link 幂等 upsert。"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.knowledge.evidence_service import EvidenceService
from app.knowledge.linklayer.dict_match import build_subject_index, match_all
from app.knowledge.linklayer.dictionaries import load_vocabulary
from app.knowledge.linklayer.llm_extract import extract_keywords
from app.knowledge.linklayer.models import Link
from app.knowledge.linklayer.normalize import (
    canonicalize_dimension,
    canonicalize_subject,
    ensure_keyword,
)

logger = logging.getLogger(__name__)

# 字典匹配的最小窗口：即使 LLM 窗口调小，也保证覆盖 evidence 主体段落
MATCH_MIN_CHARS = 12_000


def _normalize_for_match(text: str) -> str:
    """用于位置反查的归一化：全角→半角、去空白与连接符、统一小写。

    实测 9.4% 的 scope 词在原文中"找不到"只是格式差异（如
    "005L－CT 001沪" vs "005L-CT001沪"），归一化后可正确匹配，
    避免把格式变体误判为污染而丢弃。
    """
    out = []
    for ch in text:
        code = ord(ch)
        if 0xFF01 <= code <= 0xFF5E:  # 全角 ASCII → 半角
            ch = chr(code - 0xFEE0)
        elif code == 0x3000:  # 全角空格
            ch = " "
        out.append(ch)
    s = "".join(out).lower()
    return "".join(c for c in s if not c.isspace() and c not in "-_—–")


@dataclass
class LinkAction:
    layer: str
    norm_text: str
    source: str
    span_start: int
    span_end: int
    published_at: datetime | None = None
    dimension: str | None = None
    level: int | None = None
    # 开放词表的聚合锚点：细粒度词（"高速通信线营业收入"）挂到粗粒度标准维度（"营收"）。
    # 不是归一化替换，而是**保留原词 + 标注归属**，查询时可沿此上卷。
    parent: str | None = None
    # metric 结构化数值（LLM 已抽出，此前被丢弃）
    value: str | None = None
    unit: str | None = None
    period: str | None = None

    def to_payload(self) -> dict:
        return {
            "layer": self.layer,
            "norm_text": self.norm_text,
            "source": self.source,
            "span_start": self.span_start,
            "span_end": self.span_end,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "dimension": self.dimension,
            "level": self.level,
            "parent": self.parent,
            "value": self.value,
            "unit": self.unit,
            "period": self.period,
        }


async def compute_link_actions(
    evidence: dict,
    *,
    skip_llm: bool = False,
    subject_index=None,
    use_db: bool = True,
    persist_llm_cache: bool = True,
) -> tuple[list[LinkAction], bool]:
    """计算一条 evidence 的 link 行集合（不做任何落库）。返回 (actions, llm_used)。

    persist_llm_cache=False 供无 DB 通道的远端 worker 使用：LLM 提取结果不写 Mongo 缓存。
    """
    text = evidence.get("text_excerpt") or ""
    # 字典匹配窗口：与 LLM 浅提取窗口对齐（超长公告可达 26 万字，全量扫描会让
    # 单条耗时冲到 100s+ 并长期占用 PG 连接/slot）。截断口径与 LLM 一致，
    # 保证两条通道看到同一段文本，避免"字典命中但 LLM 未命中"的不一致。
    from app.knowledge.linklayer.llm_extract import LLM_INPUT_MAX_CHARS

    match_text = text[: max(LLM_INPUT_MAX_CHARS, MATCH_MIN_CHARS)]
    vocab = load_vocabulary()
    known_dimensions = set(vocab.dimensions.keys())
    if subject_index is None:
        subject_index = (
            await build_subject_index() if use_db else await build_subject_index(use_db=False)
        )

    actions: list[LinkAction] = []
    published = _parse_date(evidence.get("publish_date"))
    for m in match_all(match_text, vocab, subject_index):
        actions.append(LinkAction(m.layer, m.norm_text, "dictionary", m.span_start, m.span_end, published))
        if m.layer == "stage" and m.dimension:
            actions.append(LinkAction("dimension", m.dimension, "dictionary", m.span_start, m.span_end, published))

    hint_subject = _subject_from_hint(evidence.get("subject_hint"))
    if hint_subject:
        actions.append(LinkAction("subject", hint_subject, "hint", 0, 0, published))

    llm_result = (
        None if skip_llm
        else await extract_keywords(evidence, persist=persist_llm_cache)
    )
    llm_used = llm_result is not None
    if llm_result:
        # span 回填：LLM 只给 surface，机械层用 text.find() 反查真实位置。
        # 历史上 LLM 类 link 一律 span=0，导致无法校验"该词是否真在原文"，
        # 是污染（跨文档串台/幻觉）无法拦截的根因。反查失败即视为污染丢弃。
        def _locate(surface: str) -> int:
            if not surface:
                return -1
            pos = match_text.find(surface)
            if pos >= 0:
                return pos
            # 格式变体兜底（全角↔半角、空白差异）：归一化后再找
            norm_surface = _normalize_for_match(surface)
            if not norm_surface:
                return -1
            return _normalize_for_match(match_text).find(norm_surface)

        for surface in llm_result.get("company", []):
            norm = canonicalize_subject(surface, subject_index) or surface
            pos = _locate(surface)
            actions.append(LinkAction("subject", norm, "llm",
                                      pos if pos >= 0 else 0, (pos + len(surface)) if pos >= 0 else 0,
                                      published))
        for surface in llm_result.get("product", []):
            pos = _locate(surface)
            if pos < 0:
                continue  # 原文不含 → 丢弃（污染拦截）
            actions.append(LinkAction("scope", surface, "llm", pos, pos + len(surface), published))
        for m in llm_result.get("metric", []):
            # 开放词表策略：保留 LLM 原始指标名（细粒度可检索），同时标注其归属的
            # 标准维度 parent（若有）供上卷聚合。不丢弃、不替换——
            # "高速通信线营业收入"与"营业收入"是不同粒度的有效标尺，都该保留。
            name = (m.get("name") or "").strip()
            if not name:
                continue
            pos = _locate(name)
            if pos < 0:
                continue  # 原文不含 → 丢弃
            actions.append(LinkAction(
                "dimension", name, "llm", pos, pos + len(name), published,
                parent=canonicalize_dimension(name, known_dimensions),
                value=(str(m["value"]) if m.get("value") is not None else None),
                unit=m.get("unit"),
                period=m.get("period"),
            ))

    return actions, llm_used


async def persist_link_actions(session, evidence_id: str, actions: list[LinkAction]) -> int:
    """落库 link 行（幂等）。返回处理行数。"""
    link_count = 0
    for action in actions:
        kw_id = await ensure_keyword(
            session, action.layer, action.norm_text, source=action.source, parent=action.parent
        )
        base = pg_insert(Link).values(
            keyword_id=kw_id,
            evidence_id=evidence_id,
            span_start=action.span_start,
            span_end=action.span_end,
            published_at=action.published_at,
            source=action.source,
            metric_value=action.value,
            metric_unit=action.unit,
            metric_period=action.period,
        )
        if action.source == "hint":
            stmt = base.on_conflict_do_update(
                index_elements=["keyword_id", "evidence_id", "span_start"],
                set_={"source": "hint"},
            )
        else:
            stmt = base.on_conflict_do_nothing()
        await session.execute(stmt)
        link_count += 1
    await session.commit()
    return link_count


async def ingest_evidence(evidence_id: str, *, _session=None, skip_llm: bool = False) -> dict:
    """对单条 evidence 建链。幂等：link PK 冲突 do nothing。行为与拆分前一致。"""
    svc = EvidenceService()
    evidence = await svc.get_evidence(evidence_id)
    if not evidence:
        return {"links": 0, "keywords": 0, "llm_used": False}

    actions, llm_used = await compute_link_actions(evidence, skip_llm=skip_llm)
    assert _session is not None, "需要 PG session（由 worker / script 传入）"
    link_count = await persist_link_actions(_session, evidence_id, actions)
    return {"links": link_count, "keywords": len(actions), "llm_used": llm_used}


def _subject_from_hint(subject_hint) -> str | None:
    """从 evidence.subject_hint 提取主体规范键（spec §4.2 subject 层兜底）。

    观测到的形态：IRM 为 {"ts_code", "company_name"}，公告为
    {"ts_code", "name", "ann_type"}；上市主体规范键 = ts_code
    （与词典/查询侧 build_subject_index 的归一口径一致）。
    """
    if isinstance(subject_hint, dict):
        return (
            subject_hint.get("ts_code")
            or subject_hint.get("company_name")
            or subject_hint.get("name")
        )
    if isinstance(subject_hint, str):
        return subject_hint or None
    return None


def _parse_date(value) -> datetime | None:
    """publish_date 解析；无时区的 naive datetime 视为本地时间（补挂本地时区）。

    timestamptz 列遇到 naive datetime 会按 UTC 解释，直接落库会产生
    本地时区偏移（如 UTC+8 差 8 小时），故在边界处统一补挂时区。
    """
    if isinstance(value, datetime):
        return value if value.tzinfo else value.astimezone()
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.astimezone()
