"""
Phase 19 集成测试 — 图谱工具（live path）

LangChain middleware / lead_agent / system-prompt 断言已随 archive/langchain_agent 迁出。
"""

import pytest


class TestNeo4jTools:
    """测试 Neo4j 图谱工具"""

    def test_neo4j_traverse_import(self):
        """测试 neo4j_traverse 导入"""
        from app.reasoning.tools.knowledge.neo4j import neo4j_traverse

        assert neo4j_traverse is not None
        assert neo4j_traverse.name == "neo4j_traverse"

    def test_neo4j_entity_info_import(self):
        """测试 neo4j_entity_info 导入"""
        from app.reasoning.tools.knowledge.neo4j import neo4j_entity_info

        assert neo4j_entity_info is not None
        assert neo4j_entity_info.name == "neo4j_entity_info"

    def test_neo4j_path_import(self):
        """测试 neo4j_path 导入"""
        from app.reasoning.tools.knowledge.neo4j import neo4j_path

        assert neo4j_path is not None
        assert neo4j_path.name == "neo4j_path"

    def test_neo4j_industry_state_import(self):
        """测试 neo4j_industry_state 导入"""
        from app.reasoning.tools.knowledge.neo4j import neo4j_industry_state

        assert neo4j_industry_state is not None
        assert neo4j_industry_state.name == "neo4j_industry_state"

    def test_tool_registry(self):
        """测试工具注册"""
        from app.reasoning.registry import get_registry, load_tools_from_config

        load_tools_from_config()
        registry = get_registry()

        # neo4j_traverse / neo4j_entity_info 已被 resolve+expand 替代（config.yaml enabled:false），
        # 禁用工具不进注册表；仅 resolve/expand 无法替代的 neo4j_path / neo4j_industry_state 保留。
        assert registry.get_config("neo4j_traverse") is None
        assert registry.get_config("neo4j_entity_info") is None

        # 检查保留工具已注册
        assert registry.get_config("neo4j_path") is not None
        assert registry.get_config("neo4j_industry_state") is not None

        # 检查工具实例可获取
        assert registry.get_tool_instance("neo4j_path") is not None
        assert registry.get_tool_instance("neo4j_industry_state") is not None


class TestKGAnchorsEnhancement:
    """测试 KG Anchors 增强"""

    def test_format_kg_anchors_function_exists(self):
        """测试 format_kg_anchors_for_prompt 函数存在"""
        from app.reasoning.harness.memory import format_kg_anchors_for_prompt

        assert format_kg_anchors_for_prompt is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
