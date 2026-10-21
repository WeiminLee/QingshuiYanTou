"""Fuse dense and sparse candidate lists by rank, then let the reranker order the shortlist."""
from __future__ import annotations


def fuse_ranks_by_reciprocal_rank(
    rankings: list[list[tuple[str, float]]],
    *,
    rrf_k: int = 60,
) -> list[tuple[str, float]]:
    """RRF over list position. The raw score in each tuple is ignored."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        seen: set[str] = set()
        rank = 0
        for doc_id, _raw in ranking:
            if doc_id in seen:
                continue
            seen.add(doc_id)
            rank += 1
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (rrf_k + rank)
    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))


def apply_reranker(shortlist: list[str], scores: dict[str, float]) -> list[str]:
    """Reorder only the shortlist. A high score outside this list cannot enter."""
    indexed = list(enumerate(shortlist))
    indexed.sort(key=lambda pair: (-scores.get(pair[1], float("-inf")), pair[0]))
    return [doc_id for _, doc_id in indexed]


def shortlist_then_rerank(
    dense: list[tuple[str, float]],
    sparse: list[tuple[str, float]],
    reranker_scores: dict[str, float],
    *,
    shortlist_size: int = 30,
    rrf_k: int = 60,
) -> list[str]:
    fused = fuse_ranks_by_reciprocal_rank([dense, sparse], rrf_k=rrf_k)
    shortlist = [doc_id for doc_id, _score in fused[:shortlist_size]]
    return apply_reranker(shortlist, reranker_scores)
