"""
Vector Operations - Hybrid RAG Retrieval and Async Upsert

Provides:
- hybrid_vector_search(): Parallel multi-collection search with RRF merge
- async_upsert_*(): Semaphore-gated async upsert wrappers
- reindex_missing_vectors(): Batch reindex for nightly job
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Optional

from app.knowledge.vector_client import (
    COLLECTION_ENTITIES,
    COLLECTION_RELATIONS,
    COLLECTION_CHUNKS,
    COLLECTION_QA,
    VectorRecord,
    SearchResult,
    get_vector_client,
    get_embedding_model,
)

logger = logging.getLogger(__name__)

# Concurrency limit for async embedding API calls (D-03: Claude's discretion)
SEMAPHORE = asyncio.Semaphore(10)


def _all_collections() -> list[str]:
    """All 4 Qdrant collections for parallel search."""
    return [
        COLLECTION_ENTITIES,
        COLLECTION_RELATIONS,
        COLLECTION_CHUNKS,
        COLLECTION_QA,
    ]


def _rrf_merge(
    results_per_coll: list[list[SearchResult] | Exception],
    top_k_per_collection: int,
    rrf_k: int = 60,
) -> list[tuple[str, float, dict]]:
    """
    Reciprocal Rank Fusion (RRF) merge across collections.

    RRF formula: score(d) = sum(1 / (k + rank(d)))

    Returns: list of (id, rrf_score, payload) sorted by rrf_score descending.
    """
    rrf_scores: dict[str, float] = {}
    rrf_payloads: dict[str, dict] = {}

    for coll_results in results_per_coll:
        if isinstance(coll_results, Exception):
            logger.warning(f"Collection search failed: {coll_results}")
            continue
        for rank, r in enumerate(coll_results):
            key = r.id
            rrf_scores[key] = rrf_scores.get(key, 0.0) + 1.0 / (rrf_k + rank + 1)
            if key not in rrf_payloads:
                rrf_payloads[key] = r.payload

    # Sort by rrf_score descending
    sorted_results = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)
    return [(r_id, score, rrf_payloads.get(r_id, {})) for r_id, score in sorted_results]


async def hybrid_vector_search(
    query: str,
    top_k_per_collection: int = 5,
    global_top_k: int = 10,
    filter_expr: Optional[str] = None,
) -> list[SearchResult]:
    """
    Parallel search across all 4 Qdrant collections with RRF merge.

    Flow:
    1. Generate query embedding (single text -> vector)
    2. Search all 4 collections in parallel (asyncio.gather)
    3. Merge results using Reciprocal Rank Fusion (RRF)
    4. Return top_k global results with merged payloads

    Args:
        query: Natural language query
        top_k_per_collection: Top k results per collection before merge
        global_top_k: Final number of results after merge
        filter_expr: Optional Qdrant filter expression

    Returns:
        List of SearchResult sorted by RRF score (descending)
    """
    embedder = get_embedding_model()
    client = get_vector_client()

    # Step 1: Generate query embedding
    try:
        q_vecs = await embedder.aembed([query])
        q_vec = q_vecs[0]
    except Exception as e:
        logger.warning(f"[HybridSearch] Embedding failed: {e}")
        return []

    # Step 2: Parallel search across all collections
    async def search_one(coll: str) -> list[SearchResult] | Exception:
        try:
            return client.search(
                collection=coll,
                query_vector=q_vec,
                top_k=top_k_per_collection,
                filter_expr=filter_expr,
            )
        except Exception as e:
            logger.warning(f"[HybridSearch] Collection {coll} failed: {e}")
            return e

    results_per_coll = await asyncio.gather(
        *[search_one(c) for c in _all_collections()],
        return_exceptions=True,
    )

    # Step 3: RRF merge
    merged = _rrf_merge(results_per_coll, top_k_per_collection)

    # Step 4: Convert back to SearchResult list
    out: list[SearchResult] = []
    for r_id, score, payload in merged[:global_top_k]:
        out.append(SearchResult(id=r_id, score=score, payload=payload))

    return out


# ── Async Upsert Wrappers ──────────────────────────────────────────────


async def async_upsert_entity_vector(
    entity_id: str,
    entity_name: str,
    description: str,
    entity_type: str = "",
    ts_code: str = "",
) -> bool:
    """Async upsert entity vector with Semaphore concurrency control."""
    async with SEMAPHORE:
        try:
            embedder = get_embedding_model()
            client = get_vector_client()
            vec = await embedder.aembed([f"{entity_name} {description}"])
            point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, str(entity_id)))
            record = VectorRecord(
                id=point_id,
                vector=vec[0],
                payload={
                    "entity_id": entity_id,
                    "entity_name": entity_name,
                    "description": description,
                    "entity_type": entity_type,
                    "ts_code": ts_code,
                },
            )
            return bool(client.upsert(COLLECTION_ENTITIES, [record]))
        except Exception as e:
            logger.warning(f"async_upsert_entity_vector failed: {e}")
            return False


async def async_upsert_relation_vector(
    relation_key: str,
    from_name: str,
    to_name: str,
    description: str,
    from_entity: str = "",
    to_entity: str = "",
    ts_code: str = "",
) -> bool:
    """Async upsert relation vector with Semaphore concurrency control."""
    async with SEMAPHORE:
        try:
            embedder = get_embedding_model()
            client = get_vector_client()
            vec = await embedder.aembed([f"{from_name} 与 {to_name}：{description}"])
            point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, str(relation_key)))
            record = VectorRecord(
                id=point_id,
                vector=vec[0],
                payload={
                    "from_entity": from_entity,
                    "to_entity": to_entity,
                    "from_name": from_name,
                    "to_name": to_name,
                    "description": description,
                    "ts_code": ts_code,
                },
            )
            return bool(client.upsert(COLLECTION_RELATIONS, [record]))
        except Exception as e:
            logger.warning(f"async_upsert_relation_vector failed: {e}")
            return False


async def async_upsert_chunk_vector(
    chunk_id: str,
    content: str,
    heading: str = "",
    source: str = "",
    ts_code: str = "",
) -> bool:
    """Async upsert document chunk vector with Semaphore concurrency control."""
    async with SEMAPHORE:
        try:
            embedder = get_embedding_model()
            client = get_vector_client()
            text = f"{heading} {content}" if heading else content
            vec = await embedder.aembed([text])
            point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, str(chunk_id)))
            record = VectorRecord(
                id=point_id,
                vector=vec[0],
                payload={
                    "content": content,
                    "heading": heading,
                    "source": source,
                    "ts_code": ts_code,
                },
            )
            return bool(client.upsert(COLLECTION_CHUNKS, [record]))
        except Exception as e:
            logger.warning(f"async_upsert_chunk_vector failed: {e}")
            return False


# ── Batch Reindex (for nightly job) ─────────────────────────────────────


async def reindex_missing_vectors(batch_size: int = 100) -> int:
    """
    Find KG extraction records with DONE status but missing vector records,
    regenerate and upsert.

    Returns count of successfully reindexed records.

    This is the core of the nightly batch job (D-07).

    NOTE: This is a stub implementation. Full implementation depends on
    Phase 05's MongoDB schema for kg_extraction_index collection.
    """
    total_reindexed = 0

    try:
        logger.info(f"[BatchReindex] Starting reindex batch (batch_size={batch_size})")
        # TODO: Implement actual MongoDB query and reindex logic
        # Expected flow:
        # 1. Query MongoDB: kg_extraction_index.find({"kg_status": "DONE", "vector_indexed": False})
        # 2. For each record, call async_upsert_* based on record type
        # 3. Update MongoDB: vector_indexed = True
        logger.info("[BatchReindex] Stub - returning 0 (depends on Phase 05 MongoDB schema)")

    except Exception as e:
        logger.error(f"[BatchReindex] Failed: {e}")

    return total_reindexed
