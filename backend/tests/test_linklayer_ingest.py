# backend/tests/test_linklayer_ingest.py
"""ingest 管线测试：组件打桩，验证编排逻辑。"""

import pytest

from app.knowledge.linklayer import ingest as ingest_mod


class _StubSession:
    """记录 execute/commit 的伪 AsyncSession（同 test_linklayer_normalize 模式）。"""

    def __init__(self):
        self.executed = []
        self.commits = 0

    async def execute(self, stmt):
        self.executed.append(stmt)

    async def commit(self):
        self.commits += 1


@pytest.mark.asyncio
async def test_ingest_combines_dict_and_llm(monkeypatch):
    """词典命中 + LLM 提取都应生成 link。"""
    recorded = []

    async def fake_get_evidence(self, evidence_id):
        return {
            "evidence_id": evidence_id,
            "text_excerpt": "中晶科技产线处于调试阶段",
            "publish_date": "2026-06-15",
            "source_type": "irm",
        }

    async def fake_extract(evidence, *, use_cache=True):
        return {"company": ["中晶科技"], "product": ["8英寸抛光硅片"], "metric": []}

    monkeypatch.setattr(ingest_mod.EvidenceService, "get_evidence", fake_get_evidence)
    monkeypatch.setattr(ingest_mod, "extract_keywords", fake_extract)

    # DB 部分打桩：ensure_keyword/link 写入收集到 recorded
    async def fake_ensure(session, layer, norm_text, *, source):
        recorded.append((layer, norm_text, source))
        return f"KW:{layer}:{norm_text}"

    monkeypatch.setattr(ingest_mod, "ensure_keyword", fake_ensure)

    from app.knowledge.linklayer.dict_match import SubjectIndex

    fake_subject = SubjectIndex(alias_to_norm={"中晶科技": "003026.SZ"})

    async def fake_build_subject_index():
        return fake_subject

    monkeypatch.setattr(ingest_mod, "build_subject_index", fake_build_subject_index)

    session = _StubSession()
    result = await ingest_mod.ingest_evidence("EV:test", _session=session)
    assert ("subject", "003026.SZ", "dictionary") in recorded
    assert ("subject", "003026.SZ", "llm") in recorded
    assert ("scope", "8英寸抛光硅片", "llm") in recorded
    assert result["llm_used"] is True
    assert result["keywords"] == len(recorded)
    assert result["links"] == len(session.executed)
    assert session.commits == 1


@pytest.mark.asyncio
async def test_ingest_missing_evidence_short_circuits(monkeypatch):
    """evidence 不存在时零动作返回，不触碰 DB。"""

    async def fake_get_evidence(self, evidence_id):
        return None

    monkeypatch.setattr(ingest_mod.EvidenceService, "get_evidence", fake_get_evidence)

    session = _StubSession()
    result = await ingest_mod.ingest_evidence("EV:missing", _session=session)
    assert result == {"links": 0, "keywords": 0, "llm_used": False}
    assert session.executed == []
    assert session.commits == 0


@pytest.mark.asyncio
async def test_ingest_llm_failure_still_records_dict_matches(monkeypatch):
    """LLM 提取失败（None）时词典通道照常落库，llm_used=False。"""
    recorded = []

    async def fake_get_evidence(self, evidence_id):
        return {
            "evidence_id": evidence_id,
            "text_excerpt": "中晶科技产线处于调试阶段",
            "publish_date": "2026-06-15",
            "source_type": "irm",
        }

    async def fake_extract(evidence, *, use_cache=True):
        return None

    async def fake_ensure(session, layer, norm_text, *, source):
        recorded.append((layer, norm_text, source))
        return f"KW:{layer}:{norm_text}"

    monkeypatch.setattr(ingest_mod.EvidenceService, "get_evidence", fake_get_evidence)
    monkeypatch.setattr(ingest_mod, "extract_keywords", fake_extract)
    monkeypatch.setattr(ingest_mod, "ensure_keyword", fake_ensure)

    from app.knowledge.linklayer.dict_match import SubjectIndex

    fake_subject = SubjectIndex(alias_to_norm={"中晶科技": "003026.SZ"})

    async def fake_build_subject_index():
        return fake_subject

    monkeypatch.setattr(ingest_mod, "build_subject_index", fake_build_subject_index)

    session = _StubSession()
    result = await ingest_mod.ingest_evidence("EV:test", _session=session)
    assert ("subject", "003026.SZ", "dictionary") in recorded
    assert all(source == "dictionary" for _, _, source in recorded)
    assert result["llm_used"] is False
    assert result["keywords"] > 0
    assert result["links"] == len(session.executed)


def test_parse_date_treats_naive_as_local():
    """publish_date 无时区时按本地时间处理（墙钟不变，补挂本地时区）。"""
    from datetime import UTC, datetime

    from app.knowledge.linklayer.ingest import _parse_date

    naive = datetime(2026, 6, 15, 0, 30, 0)
    parsed = _parse_date(naive)
    assert parsed.tzinfo is not None
    assert parsed.replace(tzinfo=None) == naive

    assert _parse_date("2026-06-15T00:30:00").tzinfo is not None

    aware = datetime(2026, 6, 15, tzinfo=UTC)
    assert _parse_date(aware) == aware

    assert _parse_date(None) is None
    assert _parse_date("") is None
    assert _parse_date("不是日期") is None


@pytest.mark.asyncio
async def test_ingest_subject_hint_fallback(monkeypatch):
    """正文不点名公司（IRM 常态）时，subject_hint 元数据应锚定主体（spec §4.2）。"""
    recorded = []

    async def fake_get_evidence(self, evidence_id):
        return {
            "evidence_id": evidence_id,
            "text_excerpt": "您好！募投项目以中晶新材料为实施主体，当前处于增产上量和新客户认证过程中",
            "publish_date": "2026-02-23",
            "source_type": "irm",
            "subject_hint": {"ts_code": "003026.SZ", "company_name": "中晶科技"},
        }

    async def fake_extract(evidence, *, use_cache=True):
        return None  # LLM 不可用（额度耗尽等）

    monkeypatch.setattr(ingest_mod.EvidenceService, "get_evidence", fake_get_evidence)
    monkeypatch.setattr(ingest_mod, "extract_keywords", fake_extract)

    async def fake_ensure(session, layer, norm_text, *, source):
        recorded.append((layer, norm_text, source))
        return f"KW:{layer}:{norm_text}"

    monkeypatch.setattr(ingest_mod, "ensure_keyword", fake_ensure)

    from app.knowledge.linklayer.dict_match import SubjectIndex

    async def fake_build_subject_index():
        return SubjectIndex(alias_to_norm={})  # stocks 名覆盖不到此正文

    monkeypatch.setattr(ingest_mod, "build_subject_index", fake_build_subject_index)

    session = _StubSession()
    result = await ingest_mod.ingest_evidence("EV:irm-nocallout", _session=session)
    assert any(r == ("subject", "003026.SZ", "hint") for r in recorded), recorded
    assert any(r[0] == "stage" and r[1] == "增产上量" for r in recorded), recorded
    assert result["llm_used"] is False


@pytest.mark.asyncio
async def test_ingest_subject_hint_skipped_when_text_names_subject(monkeypatch):
    """词典/LLM 已锚定主体时，hint 兜底不应重复追加。"""
    recorded = []

    async def fake_get_evidence(self, evidence_id):
        return {
            "evidence_id": evidence_id,
            "text_excerpt": "中晶科技处于增产上量阶段",
            "subject_hint": {"ts_code": "003026.SZ"},
        }

    async def fake_extract(evidence, *, use_cache=True):
        return None

    monkeypatch.setattr(ingest_mod.EvidenceService, "get_evidence", fake_get_evidence)
    monkeypatch.setattr(ingest_mod, "extract_keywords", fake_extract)

    async def fake_ensure(session, layer, norm_text, *, source):
        recorded.append((layer, norm_text, source))
        return f"KW:{layer}:{norm_text}"

    monkeypatch.setattr(ingest_mod, "ensure_keyword", fake_ensure)

    from app.knowledge.linklayer.dict_match import SubjectIndex

    async def fake_build_subject_index():
        return SubjectIndex(alias_to_norm={"中晶科技": "003026.SZ"})

    monkeypatch.setattr(ingest_mod, "build_subject_index", fake_build_subject_index)

    await ingest_mod.ingest_evidence("EV:dup-probe", _session=_StubSession())
    subject_hits = [r for r in recorded if r[0] == "subject" and r[1] == "003026.SZ"]
    # 词典行（正文 span）+ hint 行（span0，判定为权威主体）各一条
    assert ("subject", "003026.SZ", "dictionary") in subject_hits, recorded
    assert ("subject", "003026.SZ", "hint") in subject_hits, recorded


@pytest.mark.asyncio
async def test_ingest_stage_implies_dimension(monkeypatch):
    """阶梯词命中应机械挂上所属维度的链接（词表元数据推理）。"""
    recorded = []

    async def fake_get_evidence(self, evidence_id):
        return {
            "evidence_id": evidence_id,
            "text_excerpt": "公司产线处于调试阶段",
            "subject_hint": {"ts_code": "003026.SZ"},
        }

    async def fake_extract(evidence, *, use_cache=True):
        return None

    monkeypatch.setattr(ingest_mod.EvidenceService, "get_evidence", fake_get_evidence)
    monkeypatch.setattr(ingest_mod, "extract_keywords", fake_extract)

    async def fake_ensure(session, layer, norm_text, *, source):
        recorded.append((layer, norm_text, source))
        return f"KW:{layer}:{norm_text}"

    monkeypatch.setattr(ingest_mod, "ensure_keyword", fake_ensure)

    from app.knowledge.linklayer.dict_match import SubjectIndex

    async def fake_build_subject_index():
        return SubjectIndex(alias_to_norm={})

    monkeypatch.setattr(ingest_mod, "build_subject_index", fake_build_subject_index)

    await ingest_mod.ingest_evidence("EV:stage-dim", _session=_StubSession())
    assert ("dimension", "产线进展", "dictionary") in recorded, recorded


def test_compute_link_actions_payload_has_span_and_source():
    import asyncio

    from app.knowledge.linklayer.ingest import compute_link_actions

    evidence = {
        "evidence_id": "EV:1",
        "text_excerpt": "公司公告称量产。",
        "subject_hint": {"ts_code": "300001.SZ"},
        "publish_date": "2026-05-21",
    }
    actions, llm_used = asyncio.run(
        compute_link_actions(evidence, skip_llm=True, use_db=False)
    )
    assert llm_used is False
    assert any(a.source == "hint" and a.norm_text == "300001.SZ" for a in actions)
    payload = actions[0].to_payload()
    assert set(payload) >= {"layer", "norm_text", "source", "span_start", "span_end"}
