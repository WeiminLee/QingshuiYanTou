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
