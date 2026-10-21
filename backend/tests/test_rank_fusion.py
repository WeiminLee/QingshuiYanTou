"""Dense and sparse ranks fuse by reciprocal rank; the reranker orders the shortlist."""
from __future__ import annotations

import pytest

from app.knowledge.api.agent_search import search_current_text
from app.knowledge.retrieval.facts import ShortFact, register_short_fact, reset_catalog
from app.knowledge.retrieval.search import install_rank_adapters, reset_rank_adapters

AS_OF = "2026-10-18"


class _ListRanker:
    def __init__(self, ordered: list[tuple[str, float]]):
        self.ordered = ordered
        self.seen: list[list[str]] = []

    def rank(self, query: str, facts: list[ShortFact]) -> list[tuple[str, float]]:
        present = {fact.fact_id for fact in facts}
        self.seen.append(sorted(present))
        return [(fact_id, score) for fact_id, score in self.ordered if fact_id in present]


class _ScoreReranker:
    def __init__(self, scores: dict[str, float]):
        self.scores = scores
        self.seen: list[list[str]] = []

    def score(self, query: str, facts: list[ShortFact]) -> dict[str, float]:
        self.seen.append([fact.fact_id for fact in facts])
        return {fact.fact_id: self.scores.get(fact.fact_id, 0.0) for fact in facts}


@pytest.fixture(autouse=True)
def _clean():
    reset_catalog()
    reset_rank_adapters()
    yield
    reset_catalog()
    reset_rank_adapters()


def _fact(fact_id: str, dimension: str, period: str, value: str) -> ShortFact:
    return ShortFact(
        fact_id=fact_id,
        subject="宁德时代",
        dimension=dimension,
        period=period,
        value=value,
        unit="%",
        evidence_id=f"EV:{fact_id}",
        valid_from="2025-01-01",
        valid_until=None,
    )


def test_fusion_follows_rank_not_raw_score():
    """A much larger raw score in one modality must not beat a better rank."""
    register_short_fact(_fact("rank-winner", "综合毛利率", "2025Q3", "22.5"), "原文甲，综合毛利率为22.5%。")
    register_short_fact(_fact("raw-winner", "综合毛利率", "2025Q2", "21.0"), "原文乙，综合毛利率为21.0%。")
    dense = [("rank-winner", 0.10), ("raw-winner", 0.95)]
    sparse = [("rank-winner", 0.10), ("raw-winner", 0.05)]
    raw_sum: dict[str, float] = {}
    for fact_id, score in dense + sparse:
        raw_sum[fact_id] = raw_sum.get(fact_id, 0.0) + score
    assert max(raw_sum, key=raw_sum.get) == "raw-winner"

    install_rank_adapters(
        _ListRanker(dense),
        _ListRanker(sparse),
        _ScoreReranker({"rank-winner": 0.5, "raw-winner": 0.5}),
    )

    hits = search_current_text("宁德时代 综合毛利率", as_of=AS_OF)

    assert [hit["fact_id"] for hit in hits][0] == "rank-winner"


def test_reranker_picks_matching_metric_over_bi_encoder_neighbor():
    """Same company, adjacent period, different metric: rerank beats bi-encoder order."""
    register_short_fact(
        _fact("gross", "综合毛利率", "2025Q3", "22.5"),
        "宁德时代2025年第三季度综合毛利率为22.5%。",
    )
    register_short_fact(
        _fact("deduct", "扣非毛利率", "2025Q2", "18.1"),
        "宁德时代2025年第二季度扣非毛利率为18.1%。",
    )
    # Both modalities rank the neighbor first and give it the larger raw score.
    dense = _ListRanker([("deduct", 0.99), ("gross", 0.01)])
    sparse = _ListRanker([("deduct", 0.80), ("gross", 0.02)])
    reranker = _ScoreReranker({"gross": 0.91, "deduct": 0.15})
    install_rank_adapters(dense, sparse, reranker)

    hits = search_current_text("宁德时代 2025Q3 综合毛利率", as_of=AS_OF)

    assert dense.ordered[0][0] == "deduct"
    assert sparse.ordered[0][0] == "deduct"
    assert hits[0]["fact_id"] == "gross"
    assert hits[0]["dimension"] == "综合毛利率"
    assert hits[1]["dimension"] == "扣非毛利率"
    assert reranker.seen, "reranker was not asked to score the shortlist"
    assert "gross" in reranker.seen[0]
    assert "deduct" in reranker.seen[0]
