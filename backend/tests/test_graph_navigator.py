"""Tests for graph_navigator — resolve + expand graph navigation tools."""

from __future__ import annotations

from unittest.mock import patch

# ── TestResolve ────────────────────────────────────────────────


class TestResolve:
    def test_resolve_returns_entity_on_exact_match(self):
        """resolve with exact entity name returns the entity."""
        from app.reasoning.tools.knowledge.graph_navigator import resolve

        mock_result = [{"entity_id": "C_宁德时代", "name": "宁德时代", "type": "Company", "score": 1.0}]
        with patch(
            "app.reasoning.tools.knowledge.graph_navigator._search_entity_by_name",
            return_value=mock_result,
        ):
            result = resolve.func("宁德时代")
        assert result is not None
        assert result["entity_id"] == "C_宁德时代"
        assert result["type"] == "Company"

    def test_resolve_returns_none_on_no_match(self):
        from app.reasoning.tools.knowledge.graph_navigator import resolve

        with patch(
            "app.reasoning.tools.knowledge.graph_navigator._search_entity_by_name",
            return_value=[],
        ):
            result = resolve.func("不存在的公司")
        assert result is None

    def test_resolve_with_entity_type_filter(self):
        from app.reasoning.tools.knowledge.graph_navigator import resolve

        mock_result = [{"entity_id": "P_电源模块", "name": "电源模块", "type": "Product", "score": 0.95}]
        with patch(
            "app.reasoning.tools.knowledge.graph_navigator._search_entity_by_name",
            return_value=mock_result,
        ) as mock_search:
            result = resolve.func("电源模块", entity_type="Product")
            mock_search.assert_called_once_with("电源模块", "Product")
        assert result["type"] == "Product"

    def test_resolve_normalizes_name(self):
        from app.reasoning.tools.knowledge.graph_navigator import _normalize_query

        assert _normalize_query("宁德时代") == "宁德时代"
        assert _normalize_query("　宁德时代　") == "宁德时代"
        assert _normalize_query("Ａ股") == "A股"


# ── TestExpand ─────────────────────────────────────────────────


class TestExpand:
    def test_expand_properties(self):
        from app.reasoning.tools.knowledge.graph_navigator import expand

        mock_entity = {
            "id": "C_新雷能",
            "name": "新雷能",
            "type": "Company",
            "description": "北京新雷能",
            "industry": "电子",
        }
        with patch(
            "app.reasoning.tools.knowledge.graph_navigator._fetch_entity",
            return_value=mock_entity,
        ):
            result = expand.func("C_新雷能", select=["properties"])
        assert result["entity"]["name"] == "新雷能"

    def test_expand_relations_with_filter(self):
        from app.reasoning.tools.knowledge.graph_navigator import expand

        mock_rels = [
            {
                "from": "C_新雷能",
                "to": "M_营收",
                "text": "营收120亿",
                "stmt_type": "Fact",
                "weight": 1.0,
            },
            {
                "from": "C_新雷能",
                "to": "M_营收",
                "text": "预计增长30%",
                "stmt_type": "Estimate",
                "weight": 0.7,
            },
        ]
        with patch(
            "app.reasoning.tools.knowledge.graph_navigator._fetch_relations",
            return_value=mock_rels,
        ):
            result = expand.func("C_新雷能", select=["relations"], filter_={"stmt_types": ["Fact"]})
        assert len(result["relations"]) == 1
        assert result["relations"][0]["stmt_type"] == "Fact"

    def test_expand_metrics(self):
        from app.reasoning.tools.knowledge.graph_navigator import expand

        mock_metrics = [
            {
                "entity_id": "M_营收",
                "name": "营收",
                "type": "Metric",
                "stmt_type": "Fact",
                "text": "2024年营收120亿",
                "weight": 1.0,
            },
            {
                "entity_id": "M_营收",
                "name": "营收",
                "type": "Metric",
                "stmt_type": "Estimate",
                "text": "预计2025年营收增长30%",
                "weight": 0.7,
            },
        ]
        with patch(
            "app.reasoning.tools.knowledge.graph_navigator._fetch_typed_neighbors",
            return_value=mock_metrics,
        ):
            result = expand.func("C_新雷能", select=["metrics"])
        assert "metrics" in result
        assert "M_营收" in result["metrics"]
        assert len(result["metrics"]["M_营收"]["facts"]) == 1
        assert len(result["metrics"]["M_营收"]["estimates"]) == 1

    def test_expand_peers(self):
        from app.reasoning.tools.knowledge.graph_navigator import expand

        mock_peers = [
            {
                "entity_id": "C_英维克",
                "name": "英维克",
                "type": "Company",
                "shared_count": 2,
                "shared_products": ["精密温控", "电源模块"],
            }
        ]
        with patch(
            "app.reasoning.tools.knowledge.graph_navigator._fetch_peers",
            return_value=mock_peers,
        ):
            result = expand.func("C_新雷能", select=["peers"])
        assert len(result["peers"]) == 1
        assert result["peers"][0]["name"] == "英维克"

    def test_expand_upstream(self):
        from app.reasoning.tools.knowledge.graph_navigator import expand

        mock_paths = [
            {
                "nodes": ["C_新雷能", "P_电源模块", "P_铜箔"],
                "edges": [
                    {
                        "from": "C_新雷能",
                        "to": "P_电源模块",
                        "text": "生产",
                        "subtype": "produces",
                    }
                ],
            }
        ]
        with patch(
            "app.reasoning.tools.knowledge.graph_navigator._fetch_chain",
            return_value=mock_paths,
        ):
            result = expand.func(
                "C_新雷能",
                select=["upstream"],
                filter_={"direction": "upstream", "depth": 2},
            )
        assert "paths" in result

    def test_expand_divergence(self):
        from app.reasoning.tools.knowledge.graph_navigator import expand

        mock_div = [
            {
                "metric_id": "M_营收",
                "metric_name": "营收",
                "facts": [{"text": "营收120亿", "period": "2024A"}],
                "estimates": [{"text": "预计营收150亿", "period": "2025E"}],
                "claims": [],
                "gap": {
                    "fact_value": 120,
                    "estimate_value": 150,
                    "gap_pct": "+25%",
                    "direction": "bullish",
                },
            }
        ]
        with patch(
            "app.reasoning.tools.knowledge.graph_navigator._fetch_divergence",
            return_value=mock_div,
        ):
            result = expand.func("C_新雷能", select=["divergence"])
        assert "divergences" in result
        assert result["divergences"][0]["gap"]["direction"] == "bullish"

    def test_expand_combines_multiple_selects(self):
        from app.reasoning.tools.knowledge.graph_navigator import expand

        mock_entity = {"id": "C_新雷能", "name": "新雷能", "type": "Company"}
        mock_metrics = [
            {
                "entity_id": "M_营收",
                "name": "营收",
                "type": "Metric",
                "stmt_type": "Fact",
                "text": "营收120亿",
                "weight": 1.0,
            }
        ]
        with (
            patch(
                "app.reasoning.tools.knowledge.graph_navigator._fetch_entity",
                return_value=mock_entity,
            ),
            patch(
                "app.reasoning.tools.knowledge.graph_navigator._fetch_typed_neighbors",
                return_value=mock_metrics,
            ),
        ):
            result = expand.func("C_新雷能", select=["properties", "metrics"])
        assert "entity" in result
        assert "metrics" in result
