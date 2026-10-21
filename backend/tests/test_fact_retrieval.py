"""Current-fact retrieval: in-force short facts point at the original passage."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import settings
from app.knowledge.api.agent_search import search_current_text, search_fact_history_text
from app.knowledge.api.worker_jobs import evidence_router
from app.knowledge.retrieval.facts import ShortFact, register_short_fact, reset_catalog, retrieval_key
from app.knowledge.retrieval.search import install_rank_adapters, reset_rank_adapters

HEADERS = {"X-API-Key": "test-key"}
AS_OF = "2026-10-18"

PASSAGE_GROSS = (
    "宁德时代2025年第三季度报告披露，综合毛利率为22.5%，"
    "较上年同期上升。电池业务仍是主要来源，此处保留整段以便回查原文。"
)
PASSAGE_DEDUCT = (
    "宁德时代2025年第二季度报告披露，扣非毛利率为18.1%，"
    "与综合口径不是同一指标，不可互相替代。"
)
PASSAGE_OLD = (
    "宁德时代2024年第三季度报告披露，综合毛利率为19.0%。"
    "该表述已被2025年第三季度报告替代。"
)


class _OrderRanker:
    """Return a fixed rank order. Raw scores are large on the wrong fact on purpose."""

    def __init__(self, order: list[str], raw: dict[str, float]):
        self.order = order
        self.raw = raw
        self.seen: list[list[str]] = []

    def rank(self, query: str, facts: list[ShortFact]) -> list[tuple[str, float]]:
        present = {fact.fact_id for fact in facts}
        self.seen.append(sorted(present))
        return [(fact_id, self.raw[fact_id]) for fact_id in self.order if fact_id in present]


class _PreferGross:
    def __init__(self):
        self.seen: list[list[str]] = []

    def score(self, query: str, facts: list[ShortFact]) -> dict[str, float]:
        self.seen.append([fact.fact_id for fact in facts])
        return {fact.fact_id: 1.0 if fact.dimension == "综合毛利率" else 0.1 for fact in facts}


@pytest.fixture(autouse=True)
def _clean_catalog():
    reset_catalog()
    reset_rank_adapters()
    yield
    reset_catalog()
    reset_rank_adapters()


@pytest.fixture()
def evidence_client(monkeypatch):
    monkeypatch.setattr(settings, "knowledge_api_key", "test-key", raising=False)
    monkeypatch.setattr(settings, "api_key", "", raising=False)
    app = FastAPI()
    app.include_router(evidence_router)
    return TestClient(app)


def _register_margin_facts() -> tuple[_OrderRanker, _OrderRanker, _PreferGross]:
    register_short_fact(
        ShortFact(
            fact_id="fact-old",
            subject="宁德时代",
            dimension="综合毛利率",
            period="2024Q3",
            value="19.0",
            unit="%",
            evidence_id="EV:oldgross",
            valid_from="2024-10-01",
            valid_until="2025-10-01",
        ),
        PASSAGE_OLD,
    )
    register_short_fact(
        ShortFact(
            fact_id="fact-gross",
            subject="宁德时代",
            dimension="综合毛利率",
            period="2025Q3",
            value="22.5",
            unit="%",
            evidence_id="EV:gross",
            valid_from="2025-10-01",
            valid_until=None,
        ),
        PASSAGE_GROSS,
    )
    register_short_fact(
        ShortFact(
            fact_id="fact-deduct",
            subject="宁德时代",
            dimension="扣非毛利率",
            period="2025Q2",
            value="18.1",
            unit="%",
            evidence_id="EV:deduct",
            valid_from="2025-07-01",
            valid_until=None,
        ),
        PASSAGE_DEDUCT,
    )
    # If the ended fact is still in the candidate set, both rankers put it first.
    order = ["fact-old", "fact-gross", "fact-deduct"]
    raw = {"fact-old": 0.99, "fact-gross": 0.10, "fact-deduct": 0.50}
    dense = _OrderRanker(order, raw)
    sparse = _OrderRanker(order, raw)
    reranker = _PreferGross()
    install_rank_adapters(dense, sparse, reranker)
    return dense, sparse, reranker


def test_current_search_returns_in_force_fact_and_hides_superseded():
    dense, sparse, reranker = _register_margin_facts()

    hits = search_current_text("宁德时代 综合毛利率", as_of=AS_OF)

    assert hits, "current search returned nothing"
    top = hits[0]
    assert top["fact_id"] == "fact-gross"
    assert top["subject"] == "宁德时代"
    assert top["dimension"] == "综合毛利率"
    assert top["period"] == "2025Q3"
    assert top["value"] == "22.5"
    assert top["evidence_id"] == "EV:gross"
    assert "text_excerpt" not in top
    assert "passage" not in top
    assert PASSAGE_GROSS not in top.values()
    ranked_ids = [hit["fact_id"] for hit in hits]
    assert "fact-old" not in ranked_ids
    assert "fact-deduct" in ranked_ids
    seen = set().union(*dense.seen, *sparse.seen, *reranker.seen)
    assert "fact-old" not in seen


def test_history_keeps_the_superseded_fact():
    _register_margin_facts()

    history = search_fact_history_text(subject="宁德时代", dimension="综合毛利率")

    ids = [hit["fact_id"] for hit in history]
    assert "fact-old" in ids
    assert "fact-gross" in ids
    assert "fact-deduct" not in ids
    old = next(hit for hit in history if hit["fact_id"] == "fact-old")
    assert old["period"] == "2024Q3"
    assert old["value"] == "19.0"
    assert old["evidence_id"] == "EV:oldgross"


def test_evidence_fetch_returns_the_original_passage(evidence_client):
    _register_margin_facts()
    hits = search_current_text("宁德时代 综合毛利率", as_of=AS_OF)
    evidence_id = hits[0]["evidence_id"]
    key = retrieval_key(
        ShortFact(
            fact_id="fact-gross",
            subject="宁德时代",
            dimension="综合毛利率",
            period="2025Q3",
            value="22.5",
            unit="%",
            evidence_id=evidence_id,
            valid_from="2025-10-01",
        )
    )

    response = evidence_client.get(f"/api/v1/knowledge/evidence/{evidence_id}", headers=HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert body["text_excerpt"] == PASSAGE_GROSS
    assert body["text_excerpt"] != key
    assert "电池业务仍是主要来源" in body["text_excerpt"]
    assert key not in body["text_excerpt"]
