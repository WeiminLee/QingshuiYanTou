"""Current-fact search. Validity is applied before any ranker sees the candidates."""
from __future__ import annotations

from app.knowledge.retrieval.facts import (
    ShortFact,
    fact_is_in_force,
    fact_view,
    get_catalog,
    retrieval_key,
)
from app.knowledge.retrieval.rank import fuse_ranks_by_reciprocal_rank, shortlist_then_rerank

_adapters: dict[str, object | None] = {"dense": None, "sparse": None, "reranker": None}


def install_rank_adapters(dense, sparse, reranker) -> None:
    _adapters["dense"] = dense
    _adapters["sparse"] = sparse
    _adapters["reranker"] = reranker


def reset_rank_adapters() -> None:
    _adapters["dense"] = None
    _adapters["sparse"] = None
    _adapters["reranker"] = None


class _LexicalRanker:
    """Token overlap stand-in used only when no rank adapter is installed."""

    def rank(self, query: str, facts: list[ShortFact]) -> list[tuple[str, float]]:
        scored = [(fact.fact_id, self._overlap(query, fact)) for fact in facts]
        scored.sort(key=lambda item: (-item[1], item[0]))
        return scored

    def score(self, query: str, facts: list[ShortFact]) -> dict[str, float]:
        return {fact.fact_id: self._overlap(query, fact) for fact in facts}

    @staticmethod
    def _overlap(query: str, fact: ShortFact) -> float:
        key = retrieval_key(fact)
        return float(sum(1 for token in query.split() if token and token in key))


def _rankers():
    lexical = _LexicalRanker()
    dense = _adapters["dense"] or lexical
    sparse = _adapters["sparse"] or lexical
    reranker = _adapters["reranker"] or lexical
    return dense, sparse, reranker


def search_current_facts(
    query: str,
    *,
    as_of: str,
    shortlist_size: int = 30,
    rrf_k: int = 60,
) -> list[dict]:
    catalog = get_catalog()
    candidates = [fact for fact in catalog.facts() if fact_is_in_force(fact, as_of)]
    if not candidates:
        return []
    dense, sparse, reranker = _rankers()
    allowed = {fact.fact_id for fact in candidates}
    by_id = {fact.fact_id: fact for fact in candidates}
    dense_ranks = [(fact_id, score) for fact_id, score in dense.rank(query, candidates) if fact_id in allowed]
    sparse_ranks = [(fact_id, score) for fact_id, score in sparse.rank(query, candidates) if fact_id in allowed]
    fused = fuse_ranks_by_reciprocal_rank([dense_ranks, sparse_ranks], rrf_k=rrf_k)
    shortlist_ids = [fact_id for fact_id, _score in fused[:shortlist_size] if fact_id in by_id]
    scores = reranker.score(query, [by_id[fact_id] for fact_id in shortlist_ids])
    ordered = shortlist_then_rerank(
        dense_ranks,
        sparse_ranks,
        scores,
        shortlist_size=shortlist_size,
        rrf_k=rrf_k,
    )
    return [fact_view(by_id[fact_id]) for fact_id in ordered if fact_id in by_id]


def search_fact_history(*, subject: str, dimension: str | None = None) -> list[dict]:
    """History keeps facts whose validity interval has ended."""
    hits = []
    for fact in get_catalog().facts():
        if fact.subject != subject:
            continue
        if dimension and fact.dimension != dimension:
            continue
        hits.append(fact_view(fact))
    return hits
