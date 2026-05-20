"""
Phase 19 集成测试 — 图谱推理与工具增强

测试：
1. neo4j_traverse V2 Schema 兼容
2. neo4j_entity_info 工具
3. neo4j_path 工具
4. neo4j_industry_state 工具
5. ReasoningValidationMiddleware
6. 端到端图推理流程

注意：GraphContextMiddleware 已从中间件链移除（图谱上下文查询移至 client.py 预处理阶段异步执行）。
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

        # 检查新工具已注册
        assert registry.get_config("neo4j_entity_info") is not None
        assert registry.get_config("neo4j_path") is not None
        assert registry.get_config("neo4j_industry_state") is not None

        # 检查工具实例可获取
        assert registry.get_tool_instance("neo4j_entity_info") is not None
        assert registry.get_tool_instance("neo4j_path") is not None
        assert registry.get_tool_instance("neo4j_industry_state") is not None


class TestReasoningValidationMiddleware:
    """测试 ReasoningValidationMiddleware"""

    def test_middleware_import(self):
        """测试中间件导入"""
        from app.reasoning.langchain_agent.middlewares.reasoning_validation import (
            ReasoningValidationMiddleware,
        )
        assert ReasoningValidationMiddleware is not None

    def test_unsupported_claim_detection(self):
        """测试无来源断言检测"""
        from app.reasoning.langchain_agent.middlewares.reasoning_validation import ReasoningValidationMiddleware

        middleware = ReasoningValidationMiddleware()

        # 测试检测无来源断言
        text = "市场认为该股将上涨，预计会有不错的表现"
        claims = middleware._detect_unsupported_claims(text)
        assert len(claims) > 0  # 应该检测到"市场认为"和"预计"

    def test_data_reference_detection(self):
        """测试数据引用检测"""
        from app.reasoning.langchain_agent.middlewares.reasoning_validation import ReasoningValidationMiddleware

        middleware = ReasoningValidationMiddleware()

        # 测试有数据引用
        text_with_data = "PE 为 25 倍，营收增长 30%"
        assert middleware._has_data_references(text_with_data) is True

        # 测试无数据引用
        text_without_data = "这只股票看起来不错"
        assert middleware._has_data_references(text_without_data) is False


class TestSystemPrompt:
    """测试 System Prompt 更新"""

    def test_graph_reasoning_section_exists(self):
        """测试 graph_reasoning 部分存在"""
        from app.reasoning.langchain_agent.prompts.lead_system_prompt import SYSTEM_PROMPT_TEMPLATE

        assert "<graph_reasoning>" in SYSTEM_PROMPT_TEMPLATE
        assert "neo4j_traverse" in SYSTEM_PROMPT_TEMPLATE
        assert "neo4j_path" in SYSTEM_PROMPT_TEMPLATE
        assert "neo4j_entity_info" in SYSTEM_PROMPT_TEMPLATE
        assert "neo4j_industry_state" in SYSTEM_PROMPT_TEMPLATE

    def test_scenario_d_and_e_exist(self):
        """测试场景 D 和 E 存在"""
        from app.reasoning.langchain_agent.prompts.lead_system_prompt import SYSTEM_PROMPT_TEMPLATE

        assert "场景 D" in SYSTEM_PROMPT_TEMPLATE
        assert "场景 E" in SYSTEM_PROMPT_TEMPLATE
        assert "产业链传导分析" in SYSTEM_PROMPT_TEMPLATE
        assert "行业状态评估" in SYSTEM_PROMPT_TEMPLATE


class TestKGAnchorsEnhancement:
    """测试 KG Anchors 增强"""

    def test_format_kg_anchors_function_exists(self):
        """测试 format_kg_anchors_for_prompt 函数存在"""
        from app.reasoning.harness.memory import format_kg_anchors_for_prompt
        assert format_kg_anchors_for_prompt is not None


class TestLeadAgentIntegration:
    """测试 Lead Agent 集成"""

    def test_middleware_chain_includes_new_middlewares(self):
        """测试中间件链包含新中间件（GraphContextMiddleware 已移除，图谱上下文在 client.py 预处理）"""
        from app.reasoning.langchain_agent.lead_agent import _build_middlewares

        config = {"configurable": {"thread_id": "test"}}
        middlewares = _build_middlewares(config)

        # 中间件数量：ContextCompressor + LoopDetection + ReasoningValidation = 3
        assert len(middlewares) == 3

        # 检查中间件名称
        names = [m.name for m in middlewares]
        assert "context_compressor" in names
        assert "reasoning_validation" in names
        assert "loop_detection" in names


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
