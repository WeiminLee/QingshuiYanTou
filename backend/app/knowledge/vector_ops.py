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
            client.upsert(COLLECTION_ENTITIES, [record])
            return True
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
            client.upsert(COLLECTION_RELATIONS, [record])
            return True
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
            client.upsert(COLLECTION_CHUNKS, [record])
            return True
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


# ── 向量补偿机制 ───────────────────────────────────────────────────────

async def retry_failed_vectors(
    failed_vectors: list[dict],
    max_retries: int = 2,
) -> dict:
    """
    重试失败的向量写入（用于 KG 抽取后补偿）。

    Args:
        failed_vectors: kg_extractor 返回的 failed_vectors 列表
            每项包含: chunk_id, ts_code, source_name, content_snippet, heading, error
        max_retries: 每个向量的最大重试次数

    Returns:
        {
            "retried": int,       # 尝试重试的数量
            "success": int,       # 成功数量
            "still_failed": int,  # 仍然失败的数量
            "details": list[dict] # 详细结果
        }
    """
    retried = success = still_failed = 0
    details: list[dict] = []

    for fv in failed_vectors:
        chunk_id = fv.get("chunk_id", "")
        if not chunk_id:
            continue

        retried += 1

        # 重试逻辑：多次尝试写入
        for attempt in range(1, max_retries + 1):
            try:
                # 由于 failed_vectors 只有 content_snippet，无法完全重建
                # 仅记录需要补偿，实际补偿需从 MongoDB Evidence 或 Neo4j 重新获取内容
                client = get_vector_client()
                embedder = get_embedding_model()

                # 尝试从 snippet 创建向量（数据可能不完整）
                content = fv.get("content_snippet", "")
                if not content:
                    raise ValueError("content_snippet 为空，无法重建向量")

                vec = embedder.embed(content)
                point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, chunk_id))
                record = VectorRecord(
                    id=point_id,
                    vector=vec,
                    payload={
                        "chunk_id": chunk_id,
                        "content": content,
                        "heading": fv.get("heading", ""),
                        "source": fv.get("source_name", ""),
                        "ts_code": fv.get("ts_code", ""),
                        "retried": True,
                    },
                )
                client.upsert(COLLECTION_CHUNKS, [record])

                success += 1
                details.append({
                    "chunk_id": chunk_id,
                    "status": "success",
                    "attempts": attempt,
                })
                break

            except Exception as e:
                if attempt >= max_retries:
                    still_failed += 1
                    details.append({
                        "chunk_id": chunk_id,
                        "status": "failed",
                        "error": str(e)[:200],
                        "attempts": attempt,
                    })
                    logger.warning("向量重试失败 [%s]: %s", chunk_id, e)
                else:
                    await asyncio.sleep(2 * attempt)  # 简单退避

    logger.info("向量补偿完成: retried=%d, success=%d, still_failed=%d",
                retried, success, still_failed)

    return {
        "retried": retried,
        "success": success,
        "still_failed": still_failed,
        "details": details,
    }


def enqueue_vector_retry_jobs(
    failed_vectors: list[dict],
) -> int:
    """
    将失败的向量记录到 MongoDB，等待后续补偿。

    Args:
        failed_vectors: kg_extractor 返回的 failed_vectors 列表

    Returns:
        入队的数量
    """
    if not failed_vectors:
        return 0

    try:
        from app.core.mongodb import get_mongo_db
        from datetime import datetime, timezone

        db = get_mongo_db()
        col = db["kg_vector_retry_queue"]

        now = datetime.now(timezone.utc)
        enqueued = 0

        for fv in failed_vectors:
            try:
                doc = {
                    "chunk_id": fv.get("chunk_id"),
                    "ts_code": fv.get("ts_code"),
                    "source_name": fv.get("source_name"),
                    "content_snippet": fv.get("content_snippet", ""),
                    "heading": fv.get("heading", ""),
                    "original_error": fv.get("error", ""),
                    "status": "pending",
                    "retry_count": 0,
                    "created_at": now,
                    "updated_at": now,
                }
                col.update_one(
                    {"chunk_id": doc["chunk_id"]},
                    {"$setOnInsert": doc},
                    upsert=True,
                )
                enqueued += 1
            except Exception as e:
                logger.warning("入队失败 [%s]: %s", fv.get("chunk_id"), e)

        logger.info("向量补偿队列入队: %d 条", enqueued)
        return enqueued

    except Exception as e:
        logger.error("向量补偿入队失败: %s", e)
        return 0
