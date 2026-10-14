from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import settings
from app.knowledge import agent_ledger_ops
from app.knowledge.api.agent_ledger import router as agent_ledger_router

HEADERS = {"X-API-Key": "test-key"}


@pytest.fixture(autouse=True)
def _api_key(monkeypatch):
    monkeypatch.setattr(settings, "knowledge_api_key", "test-key", raising=False)
    monkeypatch.setattr(settings, "api_key", "", raising=False)


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(agent_ledger_router)
    return TestClient(app)


# ── validate_supports：硬证据闸门 ─────────────────────────────


class _FakeEvidenceService:
    def __init__(self, evidence: dict | None):
        self._evidence = evidence

    async def get_evidence(self, evidence_id: str):
        return self._evidence


@pytest.mark.asyncio
async def test_validate_supports_rejects_missing_evidence(monkeypatch):
    monkeypatch.setattr(
        "app.knowledge.evidence_service.EvidenceService",
        lambda: _FakeEvidenceService(None),
    )
    errors = await agent_ledger_ops.validate_supports(
        [{"evidence_id": "EV:none", "span_start": 0, "span_end": 5}]
    )
    assert any("不存在" in e for e in errors)


@pytest.mark.asyncio
async def test_validate_supports_rejects_span_out_of_range(monkeypatch):
    monkeypatch.setattr(
        "app.knowledge.evidence_service.EvidenceService",
        lambda: _FakeEvidenceService({"text_excerpt": "提高产能利用率"}),
    )
    errors = await agent_ledger_ops.validate_supports(
        [{"evidence_id": "EV:1", "span_start": 2, "span_end": 99}]
    )
    assert any("span 越界" in e for e in errors)


@pytest.mark.asyncio
async def test_validate_supports_accepts_anchored_span(monkeypatch):
    text = "公司 8 英寸抛光硅片处于客户认证阶段"
    monkeypatch.setattr(
        "app.knowledge.evidence_service.EvidenceService",
        lambda: _FakeEvidenceService({"text_excerpt": text}),
    )
    errors = await agent_ledger_ops.validate_supports(
        [{"evidence_id": "EV:1", "span_start": 0, "span_end": len(text)}]
    )
    assert errors == []


# ── save_finding 校验（不触库） ────────────────────────────────


@pytest.mark.asyncio
async def test_save_finding_rejects_bad_kind(monkeypatch):
    monkeypatch.setattr(
        "app.knowledge.evidence_service.EvidenceService",
        lambda: _FakeEvidenceService({"text_excerpt": "x"}),
    )
    result = await agent_ledger_ops.save_finding(
        subject_ts_code="003026.SZ",
        dimension="产线进展",
        kind="hunch",
        judgment="随便",
        supports=[{"evidence_id": "EV:1", "span_start": 0, "span_end": 1}],
    )
    assert result["ok"] is False
    assert any("kind 非法" in e for e in result["errors"])


@pytest.mark.asyncio
async def test_save_finding_rejects_empty_supports():
    result = await agent_ledger_ops.save_finding(
        subject_ts_code="003026.SZ",
        dimension="产线进展",
        kind="progression",
        judgment="结论",
        supports=[],
    )
    assert result["ok"] is False


@pytest.mark.asyncio
async def test_save_finding_rejects_unanchored_supports(monkeypatch):
    monkeypatch.setattr(
        "app.knowledge.evidence_service.EvidenceService",
        lambda: _FakeEvidenceService(None),
    )
    result = await agent_ledger_ops.save_finding(
        subject_ts_code="003026.SZ",
        dimension="产线进展",
        kind="progression",
        judgment="结论",
        supports=[{"evidence_id": "EV:none", "span_start": 0, "span_end": 3}],
    )
    assert result["ok"] is False
    assert any("不存在" in e for e in result["errors"])


# ── HTTP 面薄壳 ────────────────────────────────────────────────


def test_observation_requires_api_key(client):
    r = client.post(
        "/api/v1/knowledge/ledger/observation",
        json={
            "subject_ts_code": "003026.SZ",
            "dimension": "产线进展",
            "evidence_id": "EV:1",
            "span_start": 0,
            "span_end": 10,
        },
    )
    assert r.status_code == 401


def test_observation_ok(client, monkeypatch):
    fake = MagicMock(return_value={
        "ok": True, "obs_id": "OB:test", "status": "verified",
        "is_new_level": True, "watermark": {"max_level": 5},
    })
    import asyncio

    async def fake_save(**kwargs):
        return fake(**kwargs)

    monkeypatch.setattr(agent_ledger_ops, "save_observation", fake_save)
    r = client.post(
        "/api/v1/knowledge/ledger/observation",
        headers=HEADERS,
        json={
            "subject_ts_code": "003026.SZ",
            "dimension": "产线进展",
            "evidence_id": "EV:1",
            "span_start": 0,
            "span_end": 10,
            "stage_raw": "客户认证",
            "stage_level": 4,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["obs_id"] == "OB:test"
    assert body["is_new_level"] is True
    del asyncio  # noqa


def test_finding_ok_and_passes_supports(client, monkeypatch):
    captured: dict = {}

    async def fake_save(**kwargs):
        captured.update(kwargs)
        return {"ok": True, "finding_id": "FD:test", "status": "candidate"}

    monkeypatch.setattr(agent_ledger_ops, "save_finding", fake_save)
    r = client.post(
        "/api/v1/knowledge/ledger/finding",
        headers=HEADERS,
        json={
            "subject_ts_code": "003026.SZ",
            "dimension": "产线进展",
            "kind": "progression",
            "judgment": "从调试推进到增产上量，跨过新台阶",
            "supports": [{"evidence_id": "EV:1", "span_start": 0, "span_end": 8, "obs_id": "OB:1"}],
            "to_state": {"level": 5, "stage": "增产上量"},
            "confidence": 0.8,
        },
    )
    assert r.status_code == 200
    assert r.json()["finding_id"] == "FD:test"
    assert captured["supports"][0]["evidence_id"] == "EV:1"
    assert captured["to_state"]["level"] == 5


def test_history_ok(client, monkeypatch):
    async def fake_history(**kwargs):
        return {
            "subject_ts_code": "003026.SZ",
            "observations": [{"obs_id": "OB:1"}],
            "findings": [],
            "watermark": {"max_level": 5},
        }

    monkeypatch.setattr(agent_ledger_ops, "history_findings", fake_history)
    r = client.post(
        "/api/v1/knowledge/ledger/history",
        headers=HEADERS,
        json={"subject": "中晶科技", "dimension": "产线进展"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["observations"][0]["obs_id"] == "OB:1"
    assert body["watermark"]["max_level"] == 5


def test_search_rejects_bad_kind(client):
    """校验失败契约：HTTP 200 + ok=False + errors（非 4xx，沿用旧台账工具面惯例）。"""
    r = client.post(
        "/api/v1/knowledge/ledger/search",
        headers=HEADERS,
        json={"kind": "hunch"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert any("kind 非法" in e for e in body["errors"])


def test_watermark_ok(client, monkeypatch):
    async def fake_wm(**kwargs):
        return {"found": True, "watermark": {"max_level": 5}}

    monkeypatch.setattr(agent_ledger_ops, "read_watermark", fake_wm)
    r = client.post(
        "/api/v1/knowledge/ledger/watermark",
        headers=HEADERS,
        json={"subject_ts_code": "003026.SZ", "dimension": "产线进展"},
    )
    assert r.status_code == 200
    assert r.json()["watermark"]["max_level"] == 5


def test_ledger_write_tools_absent_from_mcp():
    """MCP 第一期只读：台账写端点不得注册为 MCP 工具。"""
    from app.mcp_data import tools_readonly

    names = set(tools_readonly.TOOL_NAMES)
    assert "write_observation" not in names
    assert "write_finding" not in names


# ── Phase A（2026-10-14）：数值新颖度 + supersede 语义 ─────────────────────


def test_merge_numeric_stats_first_value():
    from app.knowledge.linklayer.ledger_models import merge_numeric_stats

    stats = merge_numeric_stats(None, 40.02, "FY2025")
    assert stats == {"high": 40.02, "low": 40.02, "last": 40.02, "last_period": "FY2025", "updates": 1}


def test_merge_numeric_stats_monotone_high_low_and_last_update():
    from app.knowledge.linklayer.ledger_models import merge_numeric_stats

    prev = {"high": 40.0, "low": 10.0, "last": 40.0, "last_period": "FY2025", "updates": 3}
    s1 = merge_numeric_stats(prev, 50.0, "FY2026")
    assert s1["high"] == 50.0 and s1["low"] == 10.0 and s1["last"] == 50.0 and s1["updates"] == 4
    s2 = merge_numeric_stats(s1, 5.0, "FY2026H1")
    assert s2["high"] == 50.0 and s2["low"] == 5.0 and s2["last"] == 5.0 and s2["last_period"] == "FY2026H1"


@pytest.mark.asyncio
async def test_numeric_novelty_new_high_and_delta(monkeypatch):
    import math

    class _FakeResult:
        def __init__(self, rows):
            self._rows = rows

        def scalars(self):
            return self

        def all(self):
            return self._rows

    class _FakeSession:
        def __init__(self, rows):
            self._rows = rows

        async def execute(self, *_a, **_k):
            return _FakeResult(self._rows)

    from app.knowledge import agent_ledger_ops as ops

    rows = [
        {"num": 40.02, "period": "FY2025"},
        {"num": 32.58, "period": "FY2024"},
        {"num": 22.23, "period": "H1 2024"},
    ]
    out = await ops._numeric_novelty(_FakeSession(rows), "003026.SZ", "毛利率", None, 45.0, "FY2026", "OB:self")
    assert out["is_new_high"] is True and out["is_new_low"] is False
    assert out["is_new_extreme"] is True
    assert math.isclose(out["delta"], 45.0 - 40.02, abs_tol=1e-9)
    assert out["same_period_restated"] is False
    assert out["numeric_history_count"] == 3


@pytest.mark.asyncio
async def test_numeric_novelty_same_period_restated(monkeypatch):
    class _FakeResult:
        def __init__(self, rows):
            self._rows = rows

        def scalars(self):
            return self

        def all(self):
            return self._rows

    class _FakeSession:
        def __init__(self, rows):
            self._rows = rows

        async def execute(self, *_a, **_k):
            return _FakeResult(self._rows)

    from app.knowledge import agent_ledger_ops as ops

    rows = [{"num": 40.02, "period": "FY2025"}]
    out = await ops._numeric_novelty(_FakeSession(rows), "003026.SZ", "毛利率", None, 40.02, "FY2025", "OB:self")
    assert out["same_period_restated"] is True
    assert out["is_new_extreme"] is False  # 区间内复述不是新台阶


@pytest.mark.asyncio
async def test_numeric_novelty_mid_range_delta_negative(monkeypatch):
    class _FakeResult:
        def __init__(self, rows):
            self._rows = rows

        def scalars(self):
            return self

        def all(self):
            return self._rows

    class _FakeSession:
        def __init__(self, rows):
            self._rows = rows

        async def execute(self, *_a, **_k):
            return _FakeResult(self._rows)

    from app.knowledge import agent_ledger_ops as ops

    rows = [{"num": 40.0, "period": "FY2025"}, {"num": 20.0, "period": "FY2023"}]
    out = await ops._numeric_novelty(_FakeSession(rows), "X", "毛利率", None, 30.0, "FY2026", "OB:self")
    assert out["is_new_extreme"] is False
    assert out["delta"] == 30.0 - 40.0
    assert out["delta_pct"] == -25.0


@pytest.mark.asyncio
async def test_save_finding_supersedes_missing_target(monkeypatch):
    import app.knowledge.agent_ledger_ops as ops

    class _FakeResult:
        def scalar_one_or_none(self):
            return None

    class _FakeSession:
        async def execute(self, *_a, **_k):
            return _FakeResult()

        async def rollback(self):
            pass

    class _Ctx:
        async def __aenter__(self):
            return _FakeSession()

        async def __aexit__(self, *a):
            return None

    monkeypatch.setattr(ops, "async_session", lambda: _Ctx())
    monkeypatch.setattr(
        "app.knowledge.evidence_service.EvidenceService",
        lambda: _FakeEvidenceService({"text_excerpt": "毛利率提升至 40%"}),
    )
    result = await ops.save_finding(
        subject_ts_code="003026.SZ",
        dimension="毛利率",
        kind="progression",
        judgment="新判断",
        supports=[{"evidence_id": "EV:1", "span_start": 0, "span_end": 5}],
        supersedes="FD:missing",
    )
    assert result["ok"] is False
    assert any("目标不存在" in e for e in result["errors"])


@pytest.mark.asyncio
async def test_save_finding_supersedes_cross_subject_rejected(monkeypatch):
    import app.knowledge.agent_ledger_ops as ops

    class _Target:
        subject_ts_code = "600000.SH"
        dimension = "毛利率"
        status = "candidate"

    class _FakeResult:
        def scalar_one_or_none(self):
            return _Target()

    class _FakeSession:
        async def execute(self, *_a, **_k):
            return _FakeResult()

        async def rollback(self):
            pass

    class _Ctx:
        async def __aenter__(self):
            return _FakeSession()

        async def __aexit__(self, *a):
            return None

    monkeypatch.setattr(ops, "async_session", lambda: _Ctx())
    monkeypatch.setattr(
        "app.knowledge.evidence_service.EvidenceService",
        lambda: _FakeEvidenceService({"text_excerpt": "毛利率提升至 40%"}),
    )
    result = await ops.save_finding(
        subject_ts_code="003026.SZ",
        dimension="毛利率",
        kind="progression",
        judgment="新判断",
        supports=[{"evidence_id": "EV:1", "span_start": 0, "span_end": 5}],
        supersedes="FD:other-subject",
    )
    assert result["ok"] is False
    assert any("取代拒绝" in e for e in result["errors"])


@pytest.mark.asyncio
async def test_save_finding_supersedes_already_superseded_rejected(monkeypatch):
    import app.knowledge.agent_ledger_ops as ops

    class _Target:
        subject_ts_code = "003026.SZ"
        dimension = "毛利率"
        status = "superseded"

    class _FakeResult:
        def scalar_one_or_none(self):
            return _Target()

    class _FakeSession:
        async def execute(self, *_a, **_k):
            return _FakeResult()

        async def rollback(self):
            pass

    class _Ctx:
        async def __aenter__(self):
            return _FakeSession()

        async def __aexit__(self, *a):
            return None

    monkeypatch.setattr(ops, "async_session", lambda: _Ctx())
    monkeypatch.setattr(
        "app.knowledge.evidence_service.EvidenceService",
        lambda: _FakeEvidenceService({"text_excerpt": "毛利率提升至 40%"}),
    )
    result = await ops.save_finding(
        subject_ts_code="003026.SZ",
        dimension="毛利率",
        kind="progression",
        judgment="新判断",
        supports=[{"evidence_id": "EV:1", "span_start": 0, "span_end": 5}],
        supersedes="FD:old",
    )
    assert result["ok"] is False
    assert any("已被取代" in e for e in result["errors"])


def test_search_findings_default_excludes_superseded():
    """搜索默认过滤条件应包含 superseded 排除（源码断言）。"""
    import inspect

    from app.knowledge import agent_ledger_ops as ops

    src = inspect.getsource(ops.search_findings)
    assert 'notin_(("dismissed", "superseded"))' in src
