"""
semantic_search — 语义向量检索（前置探查）工具。

在不知道图谱 entity_id 时，先用语义向量检索模糊定位候选：
- entities: 返回实体候选，每项含 entity_id，可直接接 expand 做精准图穿透。
- chunks:   返回证据文档片段，每项含 evidence_id，可直接接 fetch_evidence 追溯原文。

底层依赖 app.knowledge.vector_client 的 semantic_search_entities / semantic_search_chunks。
"""

from __future__ import annotations

import logging
from typing import Annotated

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

_VALID_SCOPES = frozenset({"entities", "chunks", "both"})
_SNIPPET_MAX = 200


def _shape_entity(r) -> dict:
    """把实体检索命中整形为可接 expand 的结构（暴露图谱 entity_id 而非 uuid point_id）。"""
    payload = r.payload or {}
    return {
        "entity_id": payload.get("entity_id") or r.id,
        "name": payload.get("entity_name", ""),
        "type": payload.get("entity_type", ""),
        "ts_code": payload.get("ts_code", ""),
        "score": round(float(r.score), 4),
    }


def _shape_chunk(r) -> dict:
    """把文档片段命中整形为可接 fetch_evidence 的结构（暴露 evidence_id）。"""
    payload = r.payload or {}
    content = payload.get("content", "") or ""
    snippet = content[:_SNIPPET_MAX] + ("…" if len(content) > _SNIPPET_MAX else "")
    return {
        "evidence_id": payload.get("evidence_id", ""),
        "snippet": snippet,
        "source_type": payload.get("source_type", ""),
        "source_name": payload.get("source_name", ""),
        "score": round(float(r.score), 4),
    }


@tool("semantic_search")
def semantic_search(
    query: Annotated[str, "自然语言检索词（如'固态电池 龙头'、'产能翻倍'）"],
    scope: Annotated[str, "检索范围：entities(实体候选，默认) | chunks(证据片段) | both"] = "entities",
    ts_code: Annotated[str | None, "可选，限定某只股票（如'300750.SZ'）"] = None,
    top_k: Annotated[int, "每类返回的候选数量，默认 5"] = 5,
) -> dict:
    """语义向量检索（前置探查）：模糊搜索实体/证据片段，用于不知道 entity_id 时先定位候选。

    典型用法：
    - 不知道确切实体名 → semantic_search(query, scope="entities") 拿到 entity_id
      → expand(entity_id, select=[...]) 做精准图穿透。
    - 想找支撑某说法的原文 → semantic_search(query, scope="chunks") 拿到 evidence_id
      → fetch_evidence(evidence_id) 读原文。

    Returns:
        {"entities": [{entity_id, name, type, ts_code, score}], ...}
        或 {"chunks": [{evidence_id, snippet, source_type, source_name, score}], ...}
        scope=both 时两者都返回。scope 非法时返回 {"error": ...}。
    """
    if scope not in _VALID_SCOPES:
        return {"error": f"无效 scope={scope}，可选值: {sorted(_VALID_SCOPES)}"}

    from app.knowledge import vector_client

    result: dict = {}

    if scope in ("entities", "both"):
        try:
            hits = vector_client.semantic_search_entities(query, ts_code=ts_code, top_k=top_k)
            result["entities"] = [_shape_entity(h) for h in hits]
        except Exception as e:  # 向量检索失败降级为空，不阻断 agent
            logger.warning("semantic_search entities 失败: %s", e)
            result["entities"] = []

    if scope in ("chunks", "both"):
        try:
            hits = vector_client.semantic_search_chunks(query, ts_code=ts_code, top_k=top_k)
            result["chunks"] = [_shape_chunk(h) for h in hits]
        except Exception as e:
            logger.warning("semantic_search chunks 失败: %s", e)
            result["chunks"] = []

    return result
