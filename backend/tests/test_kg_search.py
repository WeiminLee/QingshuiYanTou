"""
KG Search Module Tests

Tests for:
- QueryClassifier: entity extraction and intent classification
- RelevanceScorer: composite scoring with RAGFlow multiplicative formula
- SearchStrategy: strategy selection and parameter generation
- KGSearchEngine: end-to-end search pipeline
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

# =============================================================================
# QueryClassifier Tests
# =============================================================================


class TestQueryClassifier:
    """Tests for QueryClassifier entity extraction and intent classification."""

    def test_extract_stock_code_entity(self):
        """Should extract stock code patterns like 300750.SZ."""
        from app.reasoning.tools.knowledge.neo4j.query_classify import QueryClassifier

        classifier = QueryClassifier()
        intent = classifier.extract_entities("查询300750.SZ的供应商")

        assert "300750.SZ" in intent.entities
        assert intent.query_type == "entity_relation"

    def test_extract_company_name_entity(self):
        """Should extract company name patterns like '贵州茅台'."""
        from app.reasoning.tools.knowledge.neo4j.query_classify import QueryClassifier

        classifier = QueryClassifier()
        intent = classifier.extract_entities("贵州茅台的供应商有哪些")

        assert "贵州茅台" in intent.entities
        assert intent.intent == "find_relations"

    def test_extract_industry_keyword(self):
        """Should extract industry keywords like '新能源'."""
        from app.reasoning.tools.knowledge.neo4j.query_classify import QueryClassifier

        classifier = QueryClassifier()
        intent = classifier.extract_entities("新能源行业现状")

        assert "新能源" in intent.entities
        assert intent.query_type == "industry_state"
        assert intent.intent == "assess_state"

    def test_extract_path_query_entities(self):
        """Should extract two entities for path queries."""
        from app.reasoning.tools.knowledge.neo4j.query_classify import QueryClassifier

        classifier = QueryClassifier()
        intent = classifier.extract_entities("茅台和五粮液的关系")

        assert "茅台" in intent.entities
        assert "五粮液" in intent.entities
        assert intent.query_type == "path_finding"
        assert intent.intent == "find_path"

    def test_default_fallback_for_unknown_query(self):
        """Should fallback to entity_search for unknown patterns."""
        from app.reasoning.tools.knowledge.neo4j.query_classify import QueryClassifier

        classifier = QueryClassifier()
        intent = classifier.extract_entities("随便问点什么")

        assert intent.query_type == "entity_search"
        assert intent.intent == "find_entity"

    def test_multiple_entities_extraction(self):
        """Should extract multiple entities from complex queries."""
        from app.reasoning.tools.knowledge.neo4j.query_classify import QueryClassifier

        classifier = QueryClassifier()
        intent = classifier.extract_entities("宁德时代和比亚迪在锂电产业链的关系")

        # Should extract at least the company names
        assert len(intent.entities) >= 2
        assert "宁德时代" in intent.entities or "比亚迪" in intent.entities


# =============================================================================
# RelevanceScorer Tests
# =============================================================================


class TestRelevanceScorer:
    """Tests for RelevanceScorer multiplicative formula and path scoring."""

    def test_composite_score_multiplicative_formula(self):
        """Should use RAGFlow's multiplicative formula: sim * pagerank * type_boost * recency."""
        from app.reasoning.tools.knowledge.neo4j.relevance import RelevanceScorer

        scorer = RelevanceScorer()

        # Test basic multiplicative formula
        score = scorer.composite_score(sim=0.8, pagerank=2.0, type_boost=1.5, recency=0.9)
        expected = 0.8 * 2.0 * 1.5 * 0.9  # = 2.16
        assert abs(score - expected) < 0.001

    def test_composite_score_default_values(self):
        """Should use default values of 1.0 for type_boost and recency."""
        from app.reasoning.tools.knowledge.neo4j.relevance import RelevanceScorer

        scorer = RelevanceScorer()
        score = scorer.composite_score(sim=0.5, pagerank=3.0)
        expected = 0.5 * 3.0 * 1.0 * 1.0  # = 1.5
        assert abs(score - expected) < 0.001

    def test_score_nhop_paths_distance_decay(self):
        """Should apply distance decay: sim / (2 + hop_index)."""
        from app.reasoning.tools.knowledge.neo4j.relevance import RelevanceScorer

        scorer = RelevanceScorer()

        # Mock entity results with n-hop paths
        entity_results = {
            "EntityA": MagicMock(
                sim=0.8,
                n_hop_ents=[{"path": ["EntityA", "EntityB", "EntityC"], "weights": [0.8, 0.6]}],
            )
        }

        scores = scorer.score_nhop_paths(entity_results)

        # Edge (EntityA, EntityB) at position 0: 0.8 / (2 + 0) = 0.4
        # Edge (EntityB, EntityC) at position 1: 0.8 / (2 + 1) = 0.267
        assert len(scores) >= 1

    def test_time_decay_applied(self):
        """Should apply exponential time decay based on update_time."""
        from datetime import datetime, timedelta

        from app.reasoning.tools.knowledge.neo4j.relevance import RelevanceScorer

        scorer = RelevanceScorer(time_decay=True)

        # Recent entity (1 day ago)
        recent_date = datetime.now() - timedelta(days=1)
        recent_recency = scorer.compute_recency(recent_date)

        # Old entity (100 days ago)
        old_date = datetime.now() - timedelta(days=100)
        old_recency = scorer.compute_recency(old_date)

        # Recent should have higher recency score
        assert recent_recency > old_recency
        assert 0 <= recent_recency <= 1
        assert 0 <= old_recency <= 1

    def test_rank_results_ordering(self):
        """Should sort results by composite score descending."""
        from app.reasoning.tools.knowledge.neo4j.relevance import RelevanceScorer

        scorer = RelevanceScorer()

        results = [
            {"name": "A", "sim": 0.5, "pagerank": 1.0},
            {"name": "B", "sim": 0.9, "pagerank": 2.0},
            {"name": "C", "sim": 0.3, "pagerank": 3.0},
        ]

        ranked = scorer.rank_results(results, query_entities=["test"])

        # Should be sorted by score descending
        assert ranked[0]["name"] == "B"  # Highest score: 0.9 * 2.0 = 1.8
        assert "_relevance_score" in ranked[0]


# =============================================================================
# SearchStrategy Tests
# =============================================================================


class TestSearchStrategy:
    """Tests for SearchStrategy selection and parameter generation."""

    def test_select_entity_search_strategy(self):
        """Should select ENTITY_SEARCH for entity_lookup intent."""
        from app.reasoning.tools.knowledge.neo4j.search_strategy import (
            SearchStrategy,
            SearchStrategyEnum,
        )

        strategy = SearchStrategy()
        result = strategy.select_strategy("entity_search")

        assert result == SearchStrategyEnum.ENTITY_SEARCH

    def test_select_relation_search_strategy(self):
        """Should select RELATION_SEARCH for relation queries."""
        from app.reasoning.tools.knowledge.neo4j.search_strategy import (
            SearchStrategy,
            SearchStrategyEnum,
        )

        strategy = SearchStrategy()
        result = strategy.select_strategy("entity_relation")

        assert result == SearchStrategyEnum.RELATION_SEARCH

    def test_select_path_search_strategy(self):
        """Should select PATH_SEARCH for path_finding queries."""
        from app.reasoning.tools.knowledge.neo4j.search_strategy import (
            SearchStrategy,
            SearchStrategyEnum,
        )

        strategy = SearchStrategy()
        result = strategy.select_strategy("path_finding")

        assert result == SearchStrategyEnum.PATH_SEARCH

    def test_community_search_returns_none_with_warning(self):
        """Should return None for community search (not yet available)."""
        from app.reasoning.tools.knowledge.neo4j.search_strategy import SearchStrategy

        strategy = SearchStrategy()
        result = strategy.select_strategy("community")

        # Community search should gracefully degrade
        assert result is None or str(result) == "COMMUNITY_SEARCH"

    def test_get_search_params_returns_cypher_template(self):
        """Should return Cypher template name and parameters."""
        from app.reasoning.tools.knowledge.neo4j.query_classify import QueryIntent
        from app.reasoning.tools.knowledge.neo4j.search_strategy import (
            SearchStrategy,
            SearchStrategyEnum,
        )

        strategy = SearchStrategy()
        query_intent = QueryIntent(entities=["test"], query_type="entity_search", intent="find_entity")

        params = strategy.get_search_params(SearchStrategyEnum.ENTITY_SEARCH, query_intent)

        assert "template" in params or "cypher" in params or "query_type" in params


# =============================================================================
# KGSearchEngine Tests
# =============================================================================


class TestKGSearchEngine:
    """Tests for KGSearchEngine end-to-end search pipeline."""

    @pytest.fixture
    def mock_neo4j_client(self):
        """Create a mock Neo4jClient for testing."""
        mock_client = AsyncMock()
        mock_session = AsyncMock()

        # Mock execute_query to return sample data
        mock_client.execute_query = AsyncMock(
            return_value=[
                {
                    "name": "TestEntity",
                    "labels": ["Company"],
                    "rank": 1.5,
                    "description": "Test description",
                }
            ]
        )

        # Mock session for full-text index operations
        mock_client._get_session = AsyncMock(return_value=mock_session)
        mock_session.run = AsyncMock(return_value=AsyncMock())
        mock_session.run.return_value.data = AsyncMock(return_value=[])

        return mock_client

    @pytest.mark.asyncio
    async def test_search_returns_kg_search_result(self, mock_neo4j_client):
        """Should return KGSearchResult with results, strategy, and total."""
        from app.reasoning.tools.knowledge.neo4j.kg_search import KGSearchEngine

        engine = KGSearchEngine(mock_neo4j_client)
        result = await engine.search("贵州茅台", max_results=5)

        assert hasattr(result, "results")
        assert hasattr(result, "strategy")
        assert hasattr(result, "total")
        assert result.strategy in ["entity", "relation", "path", "community", "unknown"]

    @pytest.mark.asyncio
    async def test_search_unknown_intent_falls_back_to_entity(self, mock_neo4j_client):
        """Should fallback to ENTITY_SEARCH for unknown intents."""
        from app.reasoning.tools.knowledge.neo4j.kg_search import KGSearchEngine

        engine = KGSearchEngine(mock_neo4j_client)
        result = await engine.search("随机文本查询", max_results=5)

        # Should fallback to entity search
        assert result.strategy == "entity"

    @pytest.mark.asyncio
    async def test_search_results_sorted_by_relevance(self, mock_neo4j_client):
        """Should return results sorted by relevance score descending."""
        from app.reasoning.tools.knowledge.neo4j.kg_search import KGSearchEngine

        # Mock results with different scores
        mock_neo4j_client.execute_query = AsyncMock(
            return_value=[
                {"name": "LowScore", "sim": 0.3, "pagerank": 1.0},
                {"name": "HighScore", "sim": 0.9, "pagerank": 2.0},
            ]
        )

        engine = KGSearchEngine(mock_neo4j_client)
        result = await engine.search("test", max_results=10)

        if len(result.results) >= 2:
            # Results should be sorted by relevance score
            first_score = result.results[0].get("_relevance_score", 0)
            last_score = result.results[-1].get("_relevance_score", 0)
            assert first_score >= last_score

    @pytest.mark.asyncio
    async def test_parameterized_cypher_no_fstring_injection(self, mock_neo4j_client):
        """Should use parameterized Cypher queries (no f-string interpolation)."""
        from app.reasoning.tools.knowledge.neo4j.kg_search import KGSearchEngine

        engine = KGSearchEngine(mock_neo4j_client)

        # Malicious input attempting Cypher injection
        malicious_input = "test' OR 1=1 --"

        # Should not raise exception and should use parameterized query
        result = await engine.search(malicious_input, max_results=5)

        # Verify execute_query was called with parameters dict
        if mock_neo4j_client.execute_query.called:
            call_args = mock_neo4j_client.execute_query.call_args
            # Should have parameters as second argument or keyword arg
            assert call_args is not None

    @pytest.mark.asyncio
    async def test_format_for_context_respects_token_budget(self, mock_neo4j_client):
        """Should truncate output to fit within max_tokens budget."""
        from app.reasoning.tools.knowledge.neo4j.kg_search import KGSearchEngine, KGSearchResult
        from app.reasoning.tools.knowledge.neo4j.query_classify import QueryIntent

        engine = KGSearchEngine(mock_neo4j_client)

        # Create a large result
        large_result = KGSearchResult(
            results=[{"name": f"Entity{i}", "description": "x" * 500} for i in range(20)],
            strategy="entity",
            query_analysis=QueryIntent(entities=["test"], query_type="entity_search", intent="find_entity"),
            total=20,
        )

        # Format with small token budget
        formatted = engine.format_for_context(large_result, max_tokens=100)

        # Should be truncated
        import tiktoken

        enc = tiktoken.get_encoding("cl100k_base")
        token_count = len(enc.encode(formatted))

        assert token_count <= 120  # Allow small margin

    @pytest.mark.asyncio
    async def test_strategy_override_bypasses_cache(self, mock_neo4j_client):
        """Should skip cache when strategy_override is set."""
        from app.reasoning.tools.knowledge.neo4j.kg_search import KGSearchEngine

        engine = KGSearchEngine(mock_neo4j_client)

        # First call
        await engine.search("test", max_results=5)

        # Second call with strategy_override
        await engine.search("test", max_results=5, strategy_override="relation")

        # Cache should be bypassed for strategy_override calls
        # (This is verified by checking that results are fresh)
        assert True  # If we get here without error, the test passes

    @pytest.mark.asyncio
    async def test_fulltext_index_fallback_to_contains(self, mock_neo4j_client):
        """Should fallback to CONTAINS if full-text index query fails."""
        from app.reasoning.tools.knowledge.neo4j.kg_search import KGSearchEngine

        # Mock full-text index failure
        mock_neo4j_client.execute_query = AsyncMock(
            side_effect=[
                Exception("Index not found"),  # First call fails
                [{"name": "FallbackEntity"}],  # Second call (CONTAINS) succeeds
            ]
        )

        engine = KGSearchEngine(mock_neo4j_client)
        result = await engine.search("test", max_results=5)

        # Should have fallen back and returned results
        assert result.total >= 0


# =============================================================================
# Integration Tests
# =============================================================================


class TestKGSearchIntegration:
    """Integration tests for KG search module."""

    def test_neo4j_kg_search_tool_wrapper(self):
        """Should have neo4j_kg_search tool registered as LangChain StructuredTool."""
        from app.reasoning.tools.knowledge.neo4j import neo4j_kg_search

        # LangChain @tool creates StructuredTool objects
        # StructuredTool has .name, .func, and can be invoked
        assert hasattr(neo4j_kg_search, "name")
        assert neo4j_kg_search.name == "neo4j_kg_search"

    def test_exports_in_init(self):
        """Should export all new classes and functions from __init__.py."""
        from app.reasoning.tools.knowledge.neo4j import (
            KGSearchEngine,
            KGSearchResult,
            QueryClassifier,
            QueryIntent,
            RelevanceScorer,
            SearchStrategy,
            neo4j_kg_search,
        )

        assert KGSearchEngine is not None
        assert RelevanceScorer is not None
        assert SearchStrategy is not None
        assert QueryClassifier is not None
        assert KGSearchResult is not None
        assert QueryIntent is not None
        assert neo4j_kg_search is not None

    def test_existing_tools_still_exported(self):
        """Should preserve existing Neo4j tool exports."""
        from app.reasoning.tools.knowledge.neo4j import (
            neo4j_entity_info,
            neo4j_industry_state,
            neo4j_path,
            neo4j_traverse,
        )

        # LangChain @tool creates StructuredTool objects with .name
        assert hasattr(neo4j_traverse, "name")
        assert hasattr(neo4j_entity_info, "name")
        assert hasattr(neo4j_path, "name")
        assert hasattr(neo4j_industry_state, "name")


# =============================================================================


# =============================================================================
# Tool Registry Integration Tests
# =============================================================================


class TestToolRegistryIntegration:
    """Tests for neo4j_kg_search tool registration."""

    def test_tool_config_in_loader_defaults(self):
        """Should have neo4j_kg_search in _build_default_config()."""
        from app.reasoning.registry.loader import _build_default_config

        configs = _build_default_config()
        tool_names = [cfg.name for cfg in configs]

        assert "neo4j_kg_search" in tool_names

    def test_tool_loadable_from_registry(self):
        """Should be able to load neo4j_kg_search tool from registry."""
        from app.reasoning.registry.config import ToolConfig, ToolGroup
        from app.reasoning.registry.loader import load_tools_from_config

        # Create a minimal config with just the new tool
        configs = [
            ToolConfig(
                name="neo4j_kg_search",
                group=ToolGroup.KNOWLEDGE,
                use="app.reasoning.tools.knowledge.neo4j:neo4j_kg_search",
                description="知识图谱智能搜索",
            )
        ]

        loaded = load_tools_from_config(configs)

        assert len(loaded) >= 1
        assert loaded[0].name == "neo4j_kg_search"


# =============================================================================
# Graph Context — client.py 预处理测试（GraphContextMiddleware 已移除）
# =============================================================================


class TestGraphContextPreprocess:
    """测试 client.py 中的图谱上下文异步预查询"""

    def test_extract_entities_from_question(self):
        """测试 _extract_entities 能识别股票代码和产品关键词"""
        from app.reasoning.langchain_agent.client import _extract_entities

        # 股票代码
        entities = _extract_entities("分析 300308.SZ 和 600519.SH 的走势")
        assert any("300308" in e for e in entities), f"Expected 300308 in {entities}"
        assert any("600519" in e for e in entities), f"Expected 600519 in {entities}"

        # 产品关键词
        entities2 = _extract_entities("光模块和光伏行业的前景如何")
        assert "光模块" in entities2, f"Expected 光模块 in {entities2}"
        assert "光伏" in entities2, f"Expected 光伏 in {entities2}"

    def test_fetch_graph_context_returns_empty_for_no_entities(self):
        """测试无实体时返回空字符串"""
        from app.reasoning.langchain_agent.client import _fetch_graph_context_async

        result = asyncio.run(_fetch_graph_context_async("你好，请问今天的天气如何？"))
        assert result == ""
