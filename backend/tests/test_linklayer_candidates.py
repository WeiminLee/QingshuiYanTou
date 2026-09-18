# backend/tests/test_linklayer_candidates.py
"""机械候选观察测试：零 LLM，纯 SQL 组装逻辑。"""

from sqlalchemy.dialects import postgresql

from app.knowledge.linklayer.candidates import (
    build_candidates_from_links,
    emit_radar_signals,
    generate_candidates,
)
from app.knowledge.linklayer.ledger_models import Watermark
from app.knowledge.linklayer.models import Keyword, Link


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _Scalar:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class FakeLinkSession:
    """generate_candidates 的假会话：execute(select(Keyword, Link)...) → (Keyword, Link) 行。"""

    def __init__(self, rows):
        self._rows = rows

    async def execute(self, stmt):
        return _Rows(self._rows)


class FakeRadarSession:
    """emit_radar_signals 的假会话：水位线查询返回预置行，insert 语句全部捕获。"""

    def __init__(self, watermark=None, insert_returning=(1,)):
        self.watermark = watermark
        self.insert_returning = insert_returning
        self.watermark_queries = []
        self.inserts = []
        self.commits = 0

    async def execute(self, stmt):
        entities = [d["entity"] for d in getattr(stmt, "column_descriptions", [])]
        if Watermark in entities:
            self.watermark_queries.append(stmt)
            return _Scalar(self.watermark)
        self.inserts.append(stmt)
        rows = [] if self.insert_returning is None else [self.insert_returning]
        return _Rows(rows)

    async def commit(self):
        self.commits += 1


def _kw(norm_text, layer, keyword_id=None, aliases=None):
    return Keyword(
        keyword_id=keyword_id or f"KW:{norm_text}",
        layer=layer,
        norm_text=norm_text,
        display_text=norm_text,
        aliases=aliases if aliases is not None else [],
    )


def _link(evidence_id="EV:1", span_start=0):
    return Link(keyword_id="KW:x", evidence_id=evidence_id, span_start=span_start, span_end=0, source="dictionary")


def test_build_candidates_from_links():
    """同 evidence 下 subject×stage 共现 → 一条候选观察。"""
    links = [
        {"evidence_id": "EV:1", "keyword_id": "KW:subj", "layer": "subject", "norm_text": "003026.SZ", "published_at": "2026-06-15"},
        {"evidence_id": "EV:1", "keyword_id": "KW:stage", "layer": "stage", "norm_text": "增产上量", "dimension": "产线进展", "level": 6, "published_at": "2026-06-15"},
        {"evidence_id": "EV:1", "keyword_id": "KW:dim", "layer": "dimension", "norm_text": "产线进展", "published_at": "2026-06-15"},
    ]
    candidates = build_candidates_from_links(links, evidence_text="公司8英寸抛光硅片产线已进入增产上量阶段")
    assert len(candidates) == 1
    cand = candidates[0]
    assert cand["subject_ts_code"] == "003026.SZ"
    assert cand["dimension"] == "产线进展"
    assert cand["stage_level"] == 6
    assert cand["status"] == "candidate"


def test_build_candidates_scope_and_cross_product():
    """scope 关键字落到 dimension_scope；2 主体 × 1 阶梯 → 2 条候选。"""
    links = [
        {"evidence_id": "EV:2", "layer": "subject", "norm_text": "003026.SZ"},
        {"evidence_id": "EV:2", "layer": "subject", "norm_text": "300308.SZ"},
        {"evidence_id": "EV:2", "layer": "scope", "norm_text": "8英寸抛光硅片"},
        {"evidence_id": "EV:2", "layer": "stage", "norm_text": "量产", "dimension": "产线进展", "level": 6},
    ]
    candidates = build_candidates_from_links(links, evidence_text="")
    assert len(candidates) == 2
    assert all(c["dimension_scope"] == "8英寸抛光硅片" for c in candidates)
    assert {c["subject_ts_code"] for c in candidates} == {"003026.SZ", "300308.SZ"}


def test_build_candidates_dedup_keeps_max_level():
    """同一 (evidence, subject, dimension, scope) 的多条 stage 共现只产一条，保留最高 level。"""
    links = [
        {"evidence_id": "EV:3", "layer": "subject", "norm_text": "003026.SZ"},
        {"evidence_id": "EV:3", "layer": "stage", "norm_text": "试生产", "dimension": "产线进展", "level": 4},
        {"evidence_id": "EV:3", "layer": "stage", "norm_text": "量产", "dimension": "产线进展", "level": 6},
    ]
    candidates = build_candidates_from_links(links, evidence_text="")
    assert len(candidates) == 1
    assert candidates[0]["stage_level"] == 6
    assert candidates[0]["stage_raw"] == "量产"


async def test_generate_candidates_prefers_keyword_metadata():
    """keyword 行内 aliases 元数据优先于词表（词表里没有"圆片满产"也能定维度）。"""
    rows = [
        (_kw("003026.SZ", "subject"), _link()),
        (_kw("圆片满产", "stage", aliases=[{"dimension": "产能", "level": 5}]), _link(span_start=10)),
    ]
    candidates = await generate_candidates("EV:1", FakeLinkSession(rows))
    assert len(candidates) == 1
    assert candidates[0]["dimension"] == "产能"
    assert candidates[0]["stage_level"] == 5


async def test_generate_candidates_vocab_fallback():
    """无行内元数据时回退词表回填："量产" → 产线进展 level 6。"""
    rows = [
        (_kw("003026.SZ", "subject"), _link()),
        (_kw("量产", "stage"), _link(span_start=10)),
    ]
    candidates = await generate_candidates("EV:1", FakeLinkSession(rows))
    assert len(candidates) == 1
    assert candidates[0]["dimension"] == "产线进展"
    assert candidates[0]["stage_level"] == 6


async def test_emit_radar_signals_new_level():
    """无水位线 → level 6 候选产雷达信号，字段映射按 brief。"""
    cand = {
        "obs_id": "OB:deadbeef",
        "subject_ts_code": "003026.SZ",
        "dimension": "产线进展",
        "dimension_scope": None,
        "stage_raw": "量产",
        "stage_level": 6,
        "evidence_id": "EV:1",
    }
    session = FakeRadarSession(watermark=None)
    emitted = await emit_radar_signals([cand], session)
    assert emitted == 1
    assert session.commits == 1

    params = session.inserts[0].compile(dialect=postgresql.dialect()).params
    assert params["signal_id"] == "LL:OB:deadbeef"
    assert params["source_type"] == "link_layer"
    assert params["source_id"] == "EV:1"
    assert params["subject_name"] == "003026.SZ"
    assert params["subject_type"] == "company"
    assert params["signal_type"] == "产线进展"
    assert params["polarity"] == "positive"
    assert params["strength"] == 90
    assert params["confidence"] == 0.5
    assert params["freshness_score"] == 0
    assert params["value_score"] == 60
    assert "量产" in params["summary"]


async def test_emit_radar_signals_watermark_blocks():
    """level ≤ 水位线 → 不产信号（去噪关键）。"""
    cand = {
        "obs_id": "OB:deadbeef",
        "subject_ts_code": "003026.SZ",
        "dimension": "产线进展",
        "dimension_scope": None,
        "stage_raw": "量产",
        "stage_level": 3,
        "evidence_id": "EV:1",
    }
    session = FakeRadarSession(watermark=Watermark(subject_ts_code="003026.SZ", dimension="产线进展", max_level=6))
    emitted = await emit_radar_signals([cand], session)
    assert emitted == 0
    assert session.inserts == []


async def test_emit_radar_signals_conflict_not_counted():
    """同 signal_id 已存在（RETURNING 空）→ 不计数，即 signal_id 幂等安全。"""
    cand = {
        "obs_id": "OB:deadbeef",
        "subject_ts_code": "003026.SZ",
        "dimension": "产线进展",
        "dimension_scope": None,
        "stage_raw": "量产",
        "stage_level": 6,
        "evidence_id": "EV:1",
    }
    session = FakeRadarSession(watermark=None, insert_returning=None)
    emitted = await emit_radar_signals([cand], session)
    assert emitted == 0


async def test_emit_radar_signals_scope_matched_lookup():
    """带 scope 的候选按 (subject, dimension, scope) 查水位线。"""
    cand = {
        "obs_id": "OB:deadbeef",
        "subject_ts_code": "003026.SZ",
        "dimension": "产线进展",
        "dimension_scope": "8英寸抛光硅片",
        "stage_raw": "量产",
        "stage_level": 6,
        "evidence_id": "EV:1",
    }
    session = FakeRadarSession(watermark=None)
    await emit_radar_signals([cand], session)
    sql = str(session.watermark_queries[0].compile(dialect=postgresql.dialect()))
    assert "dimension_scope" in sql
    assert "IS NULL" not in sql
