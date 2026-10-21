"""Finding write rejects a citation that does not entail period, metric, or unit."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import settings
from app.knowledge import agent_ledger_ops
from app.knowledge.api.agent_search import router as agent_search_router
from app.knowledge.retrieval.entailment import SlotJudgment, install_entailment_model, reset_entailment_model
from app.knowledge.retrieval.route import build_hypothetical_document, hypothetical_document_calls, reset_hypothetical_document_calls

HEADERS = {"X-API-Key": "test-key"}


class _Evidence:
    def __init__(self, text: str):
        self._text = text

    async def get_evidence(self, evidence_id: str):
        return {"evidence_id": evidence_id, "text_excerpt": self._text}


class _Result:
    def scalar_one_or_none(self):
        return None


class _Session:
    def __init__(self):
        self.executed = 0
        self.committed = False

    async def execute(self, stmt, *_a, **_k):
        self.executed += 1
        self.stmt = stmt
        return _Result()

    async def commit(self):
        self.committed = True

    async def rollback(self):
        pass


class _Ctx:
    def __init__(self, session: _Session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *_a):
        return None


@pytest.fixture(autouse=True)
def _api_key(monkeypatch):
    monkeypatch.setattr(settings, "knowledge_api_key", "test-key", raising=False)
    monkeypatch.setattr(settings, "api_key", "", raising=False)
    reset_entailment_model()
    reset_hypothetical_document_calls()
    yield
    reset_entailment_model()
    reset_hypothetical_document_calls()


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(agent_search_router)
    return TestClient(app)


def _patch_store(monkeypatch, text: str) -> _Session:
    session = _Session()
    monkeypatch.setattr(
        "app.knowledge.evidence_service.EvidenceService",
        lambda: _Evidence(text),
    )
    monkeypatch.setattr(agent_ledger_ops, "async_session", lambda: _Ctx(session))
    return session


def _supports(text: str) -> list[dict]:
    return [{"evidence_id": "EV:cited", "span_start": 0, "span_end": len(text)}]


async def _save(monkeypatch, text: str, **overrides):
    session = _patch_store(monkeypatch, text)
    payload = {
        "subject_ts_code": "300750.SZ",
        "dimension": "综合毛利率",
        "kind": "progression",
        "judgment": "宁德时代2025年第三季度综合毛利率为22.5%",
        "supports": _supports(text),
        "to_state": {"period": "2025Q3", "unit": "%", "value": "22.5"},
    }
    payload.update(overrides)
    result = await agent_ledger_ops.save_finding(**payload)
    return result, session


@pytest.mark.asyncio
async def test_period_mismatch_is_not_stored(monkeypatch):
    text = "宁德时代2024年全年综合毛利率为22.5%。"
    result, session = await _save(monkeypatch, text, created_by={"relevance_score": 0.99})
    assert result["ok"] is False
    assert any("期间" in error for error in result["errors"])
    assert session.executed == 0
    assert session.committed is False


@pytest.mark.asyncio
async def test_metric_variant_mismatch_is_not_stored(monkeypatch):
    text = "宁德时代2025年第三季度扣非毛利率为18.1%。"
    result, session = await _save(monkeypatch, text)
    assert result["ok"] is False
    assert any("口径" in error for error in result["errors"])
    assert session.committed is False


@pytest.mark.asyncio
async def test_unit_mismatch_is_not_stored(monkeypatch):
    text = "宁德时代2025年第三季度营业收入为12.5万元。"
    result, session = await _save(
        monkeypatch,
        text,
        dimension="营业收入",
        judgment="宁德时代2025年第三季度营业收入为12.5亿元",
        to_state={"period": "2025Q3", "unit": "亿元", "value": "12.5"},
    )
    assert result["ok"] is False
    assert any("单位" in error for error in result["errors"])
    assert session.committed is False


@pytest.mark.asyncio
async def test_entailed_claim_is_stored(monkeypatch):
    text = "宁德时代2025年第三季度综合毛利率为22.5%。"
    result, session = await _save(monkeypatch, text)
    assert result["ok"] is True
    assert result["finding_id"]
    assert session.committed is True
    assert session.executed == 1


@pytest.mark.asyncio
async def test_injected_judgment_rejects_without_gpu(monkeypatch):
    text = "宁德时代2025年第三季度综合毛利率为22.5%。"

    def judge(claim: dict, passage: str) -> SlotJudgment:
        assert "22.5%" in passage
        assert claim["period"] == "2025Q3"
        return SlotJudgment(period_ok=False, metric_ok=True, unit_ok=True)

    install_entailment_model(judge)
    result, session = await _save(monkeypatch, text)
    assert result["ok"] is False
    assert any("期间" in error for error in result["errors"])
    assert session.committed is False


def test_filled_numeric_slot_uses_compare_and_history_not_hyde(client, monkeypatch):
    calls: dict[str, dict] = {}

    async def compare_metric(*, dimension, scope=None, as_of=None, top_k=30):
        calls["compare"] = {"dimension": dimension, "scope": scope, "as_of": as_of}
        return {"dimension": dimension, "items": [{"value": "22.5", "period": "2025Q3"}]}

    async def pull_history(subject, dimension=None, scope=None, before=None, limit=100):
        calls["history"] = {"subject": subject, "dimension": dimension}
        return {"items": [{"evidence_id": "EV:gross"}], "count": 1}

    monkeypatch.setattr("app.knowledge.agent_metric_ops.compare_metric", compare_metric)
    monkeypatch.setattr("app.knowledge.linklayer.queries.pull_history", pull_history)
    reset_hypothetical_document_calls()

    response = client.post(
        "/api/v1/knowledge/search/semantic",
        headers=HEADERS,
        json={
            "query": "毛利率为什么下降",
            "subject": "300750.SZ",
            "dimension": "综合毛利率",
            "period": "2025Q3",
            "value": "22.5",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["route"] == "structured"
    assert body["hypothetical_document"] is None
    assert calls["compare"]["dimension"] == "综合毛利率"
    assert calls["history"]["subject"] == "300750.SZ"
    assert calls["history"]["dimension"] == "综合毛利率"
    assert hypothetical_document_calls == 0
    with pytest.raises(RuntimeError, match="hypothetical"):
        build_hypothetical_document("毛利率为什么下降")


def test_unbound_residual_does_not_build_a_hypothetical_document(client, monkeypatch):
    async def compare_metric(*, dimension, scope=None, as_of=None, top_k=30):
        raise AssertionError("filled slots are not on this query")

    async def pull_history(subject, dimension=None, scope=None, before=None, limit=100):
        raise AssertionError("filled slots are not on this query")

    monkeypatch.setattr("app.knowledge.agent_metric_ops.compare_metric", compare_metric)
    monkeypatch.setattr("app.knowledge.linklayer.queries.pull_history", pull_history)
    monkeypatch.setattr(
        "app.knowledge.api.agent_search.semantic_search_chunks",
        lambda *args, **kwargs: [],
    )
    reset_hypothetical_document_calls()

    response = client.post(
        "/api/v1/knowledge/search/semantic",
        headers=HEADERS,
        json={"query": "毛利率下降的原因是什么", "scope": "chunks"},
    )

    assert response.status_code == 200
    assert "facts" not in response.json()
    assert hypothetical_document_calls == 0
