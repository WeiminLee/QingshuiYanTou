"""Integration tests for resolve + expand graph navigation.

These tests require a running Neo4j instance with test data.
They are marked with @pytest.mark.integration and skipped by default.
"""

import pytest

pytestmark = pytest.mark.integration


@pytest.fixture
def ensure_test_data():
    """Ensure test entities exist in Neo4j. Skip if not available."""
    try:
        from app.core.neo4j_client import run_single

        row = run_single("MATCH (e:Entity {id: 'C_新雷能'}) RETURN e.id AS id LIMIT 1")
        if not row:
            pytest.skip("Test entity C_新雷能 not found in Neo4j")
    except Exception as e:
        pytest.skip(f"Neo4j not available: {e}")


class TestResolveIntegration:
    def test_resolve_company(self, ensure_test_data):
        from app.reasoning.tools.knowledge.graph_navigator import resolve

        result = resolve("新雷能")
        if result is None:
            pytest.skip("新雷能 not found in graph")
        assert result["type"] == "Company"
        assert result["entity_id"].startswith("C_")

    def test_resolve_nonexistent(self, ensure_test_data):
        from app.reasoning.tools.knowledge.graph_navigator import resolve

        result = resolve("绝对不存在的公司XYZ123")
        assert result is None


class TestExpandIntegration:
    def test_expand_properties(self, ensure_test_data):
        from app.reasoning.tools.knowledge.graph_navigator import expand, resolve

        entity = resolve("新雷能")
        if entity is None:
            pytest.skip("新雷能 not found")
        result = expand(entity["entity_id"], select=["properties"])
        assert "entity" in result
        assert result["entity"]["name"] == "新雷能"

    def test_expand_metrics(self, ensure_test_data):
        from app.reasoning.tools.knowledge.graph_navigator import expand, resolve

        entity = resolve("新雷能")
        if entity is None:
            pytest.skip("新雷能 not found")
        result = expand(entity["entity_id"], select=["metrics"])
        assert "metrics" in result

    def test_expand_peers(self, ensure_test_data):
        from app.reasoning.tools.knowledge.graph_navigator import expand, resolve

        entity = resolve("新雷能")
        if entity is None:
            pytest.skip("新雷能 not found")
        result = expand(entity["entity_id"], select=["peers"])
        assert "peers" in result

    def test_expand_divergence(self, ensure_test_data):
        from app.reasoning.tools.knowledge.graph_navigator import expand, resolve

        entity = resolve("新雷能")
        if entity is None:
            pytest.skip("新雷能 not found")
        result = expand(entity["entity_id"], select=["divergence"])
        assert "divergences" in result

    def test_expand_invalid_select(self, ensure_test_data):
        from app.reasoning.tools.knowledge.graph_navigator import expand, resolve

        entity = resolve("新雷能")
        if entity is None:
            pytest.skip("新雷能 not found")
        result = expand(entity["entity_id"], select=["invalid_field"])
        assert "error" in result
