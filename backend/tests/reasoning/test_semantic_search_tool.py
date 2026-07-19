"""Tests for semantic_search — 语义向量检索（前置探查）工具。"""

from __future__ import annotations

from unittest.mock import patch

from app.knowledge.vector_client import SearchResult


def _entity_hit(entity_id="C_宁德时代", name="宁德时代", etype="Company", ts_code="300750.SZ", score=0.91):
    return SearchResult(
        id="uuid-point-1",  # 注意：id 是 uuid5 point_id，不是图谱 entity_id
        score=score,
        payload={
            "entity_id": entity_id,
            "entity_name": name,
            "entity_type": etype,
            "ts_code": ts_code,
        },
    )


def _chunk_hit(evidence_id="EV:abc123", content="公司预计2024年产能翻倍。", score=0.83):
    return SearchResult(
        id="uuid-point-2",
        score=score,
        payload={
            "evidence_id": evidence_id,
            "content": content,
            "source_type": "announcement",
            "source_name": "2024年度报告",
        },
    )


class TestSemanticSearchEntities:
    def test_surfaces_graph_entity_id_not_point_id(self):
        """实体结果必须暴露 payload.entity_id（可接 expand），而非 SearchResult.id。"""
        from app.reasoning.tools.knowledge.semantic_search import semantic_search

        with patch(
            "app.knowledge.vector_client.semantic_search_entities",
            return_value=[_entity_hit()],
        ):
            result = semantic_search.func("宁德 电池龙头")

        assert "entities" in result
        assert len(result["entities"]) == 1
        hit = result["entities"][0]
        assert hit["entity_id"] == "C_宁德时代"  # 图谱 ID，不是 uuid-point-1
        assert hit["name"] == "宁德时代"
        assert hit["type"] == "Company"
        assert hit["score"] == 0.91

    def test_default_scope_is_entities_only(self):
        from app.reasoning.tools.knowledge.semantic_search import semantic_search

        with (
            patch(
                "app.knowledge.vector_client.semantic_search_entities",
                return_value=[_entity_hit()],
            ),
            patch("app.knowledge.vector_client.semantic_search_chunks") as mock_chunks,
        ):
            result = semantic_search.func("宁德时代")

        assert "entities" in result
        assert "chunks" not in result
        mock_chunks.assert_not_called()

    def test_forwards_ts_code_and_top_k(self):
        from app.reasoning.tools.knowledge.semantic_search import semantic_search

        with patch(
            "app.knowledge.vector_client.semantic_search_entities",
            return_value=[],
        ) as mock_search:
            semantic_search.func("电源模块", ts_code="300593.SZ", top_k=8)

        mock_search.assert_called_once_with("电源模块", ts_code="300593.SZ", top_k=8)

    def test_entity_id_falls_back_to_point_id_when_missing(self):
        from app.reasoning.tools.knowledge.semantic_search import semantic_search

        hit = SearchResult(id="uuid-x", score=0.5, payload={"entity_name": "无ID实体"})
        with patch(
            "app.knowledge.vector_client.semantic_search_entities",
            return_value=[hit],
        ):
            result = semantic_search.func("something")

        assert result["entities"][0]["entity_id"] == "uuid-x"

    def test_empty_results(self):
        from app.reasoning.tools.knowledge.semantic_search import semantic_search

        with patch(
            "app.knowledge.vector_client.semantic_search_entities",
            return_value=[],
        ):
            result = semantic_search.func("不存在的东西")

        assert result["entities"] == []


class TestSemanticSearchChunks:
    def test_chunk_scope_surfaces_evidence_id(self):
        """chunk 结果必须暴露 evidence_id（可接 fetch_evidence）。"""
        from app.reasoning.tools.knowledge.semantic_search import semantic_search

        with patch(
            "app.knowledge.vector_client.semantic_search_chunks",
            return_value=[_chunk_hit()],
        ):
            result = semantic_search.func("产能翻倍", scope="chunks")

        assert "chunks" in result
        assert "entities" not in result
        hit = result["chunks"][0]
        assert hit["evidence_id"] == "EV:abc123"
        assert hit["source_type"] == "announcement"
        assert hit["score"] == 0.83
        assert "产能翻倍" in hit["snippet"] or hit["snippet"]

    def test_both_scope_returns_entities_and_chunks(self):
        from app.reasoning.tools.knowledge.semantic_search import semantic_search

        with (
            patch(
                "app.knowledge.vector_client.semantic_search_entities",
                return_value=[_entity_hit()],
            ),
            patch(
                "app.knowledge.vector_client.semantic_search_chunks",
                return_value=[_chunk_hit()],
            ),
        ):
            result = semantic_search.func("宁德 产能", scope="both")

        assert result["entities"][0]["entity_id"] == "C_宁德时代"
        assert result["chunks"][0]["evidence_id"] == "EV:abc123"

    def test_invalid_scope_returns_error(self):
        from app.reasoning.tools.knowledge.semantic_search import semantic_search

        result = semantic_search.func("x", scope="bogus")
        assert "error" in result
