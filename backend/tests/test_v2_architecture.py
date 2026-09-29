"""
V2 / cutover 后 live-path 架构验证

LangChain agent 包已迁至 archive/langchain_agent/；本文件只断言默认 serving 路径仍可用的模块。
中间件 / MemoryManager(langchain) / HarnessConfig(langchain) 的测试随归档迁出。
"""

import os

import pytest


class TestLiveArchitectureImports:
    """默认路径核心模块导入测试"""

    def test_canvas_types_importable(self):
        """Canvas 类型定义（若存在）保留供 prompts/ 引用；V1 canvas 已删除则跳过"""
        try:
            from app.reasoning.canvas import (
                CanvasConfig,
                CanvasState,
                ChunkRef,
                DocAgg,
                NodeResult,
                NodeStatus,
            )

            assert CanvasState is not None
            assert ChunkRef is not None
            assert DocAgg is not None
            assert CanvasConfig is not None
            assert NodeStatus is not None
            assert NodeResult is not None
        except (ModuleNotFoundError, NameError):
            pass

    def test_registry_importable(self):
        """工具注册表可导入"""
        from app.reasoning.registry.registry import get_registry

        assert get_registry is not None

    def test_tools_module_importable(self):
        """工具层可导入（registry 入口）"""
        from app.reasoning.registry import get_registry

        registry = get_registry()
        assert registry is not None
        assert callable(registry.get_tool_instances)

    def test_harness_budget_importable(self):
        """Harness budget 模块可导入"""
        from app.reasoning.harness.budget import BudgetConfig, BudgetEnforcer

        assert BudgetEnforcer is not None
        assert BudgetConfig is not None

    def test_harness_memory_importable(self):
        """Harness memory 模块可导入"""
        from app.reasoning.harness.memory import MemoryManager, increment_kg_anchor

        assert MemoryManager is not None
        assert increment_kg_anchor is not None

    def test_output_layer_importable(self):
        """Layer 4 决策输出层可导入"""
        from app.reasoning.output.compliance import scan_content
        from app.reasoning.output.confidence import merge_confidence, source_type_to_tier
        from app.reasoning.output.report import AnalysisReport

        assert AnalysisReport is not None
        assert source_type_to_tier is not None
        assert merge_confidence is not None
        assert scan_content is not None

    def test_api_endpoints_importable(self):
        """API 端点可导入（410 slim router after cutover）"""
        from app.reasoning.api import agent

        assert hasattr(agent, "stream_report")
        assert hasattr(agent, "chat")
        assert hasattr(agent, "invoke")


class TestToolRegistry:
    """工具注册表测试"""

    def test_registry_has_builtin_tools(self):
        """内嵌默认配置应包含内置工具清单"""
        from app.reasoning.registry.loader import _build_default_config

        configs = _build_default_config()
        names = [c.name for c in configs]
        # write_todos archived with langchain_agent — may or may not remain in defaults
        expected_core = {
            "get_kline",
            "get_concept_hot",
            "get_market_breadth",
            "neo4j_path",
            "neo4j_industry_state",
            "fetch_evidence",
            "resolve",
            "expand",
            "get_research_report",
            "get_announcement",
            "tavily_search",
            "get_stock_profile",
            "get_irm",
            "present_chart",
            "ask_clarification",
            "web_fetch",
            "ls",
            "read_file",
            "write_file",
        }
        missing = expected_core - set(names)
        assert not missing, f"Expected core tools missing from defaults: {missing}"

    def test_registry_loads_all_builtin_tools(self):
        """内嵌默认配置中的所有工具均可通过 resolve_variable 解析"""
        from app.reasoning.registry.loader import _build_default_config
        from app.reasoning.registry.resolve_variable import resolve_variable

        configs = _build_default_config()
        for cfg in configs:
            # skip archived write_todos if still listed
            if "langchain_agent" in cfg.use or "archive/" in cfg.use:
                continue
            resolved = resolve_variable(cfg.use)
            assert resolved is not None, f"Failed to resolve tool: {cfg.use}"

    def test_yaml_config_has_new_tools(self):
        """YAML 配置文件应包含 web_fetch/ls/read_file/write_file/ask_clarification"""
        import yaml

        from app.reasoning.registry.loader import _CONFIG_PATH

        if not _CONFIG_PATH.exists():
            pytest.skip("config.yaml not present")
        with open(_CONFIG_PATH, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        names = {t["name"] for t in data["tools"]}
        expected_new = {"web_fetch", "ls", "read_file", "write_file", "ask_clarification"}
        missing = expected_new - names
        assert not missing, f"New tools missing from config.yaml: {missing}"


class TestP1FrontendSSEReportView:
    """P1: ReportView.vue — frontend archived; skip if missing"""

    _REPORT_VIEW = os.path.normpath(
        os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "..",
            "archive",
            "frontend",
            "src",
            "views",
            "ReportView.vue",
        )
    )

    def test_report_view_has_tool_called_sse_handler(self):
        if not os.path.exists(self._REPORT_VIEW):
            pytest.skip(f"ReportView.vue not found at {self._REPORT_VIEW} (Vue archived)")
        content = open(self._REPORT_VIEW, encoding="utf-8").read()
        assert "useChatSession" in content
        assert "ToolCallStep" in content and "toolCalls" in content

    def test_report_view_uses_streaming_renderer(self):
        if not os.path.exists(self._REPORT_VIEW):
            pytest.skip(f"ReportView.vue not found at {self._REPORT_VIEW} (Vue archived)")
        content = open(self._REPORT_VIEW, encoding="utf-8").read()
        assert "useTDesignAdapter" in content and "ThinkingPanel" in content


class TestMongoConfigured:
    def test_mongodb_url_configured(self):
        """MONGODB_URL 环境变量已配置"""
        env_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "..",
            ".env",
        )
        if os.path.exists(env_path):
            content = open(env_path).read()
            assert "MONGODB_URL" in content, "MONGODB_URL should be in .env"
        else:
            try:
                from app.config import settings

                assert hasattr(settings, "mongodb_url")
                assert settings.mongodb_url, "mongodb_url should not be empty"
            except RuntimeError as e:
                if "MONGODB_URL" in str(e):
                    pytest.fail(f"MONGODB_URL not configured: {e}")
                raise


class TestDeadCodeRemoved:
    """死代码清理验证：V1 相关模块应不存在；langchain_agent 已归档"""

    def test_v1_middlewares_directory_removed(self):
        backend_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        v1_path = os.path.join(backend_root, "app", "reasoning", "middlewares")
        assert not os.path.exists(v1_path), f"V1 middlewares/ directory still exists at {v1_path}"

    def test_langchain_agent_not_on_default_path(self):
        """live app path must not contain langchain_agent (archived)"""
        backend_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        live = os.path.join(backend_root, "app", "reasoning", "langchain_agent")
        assert not os.path.exists(live), f"langchain_agent still under app/: {live}"
        archived = os.path.normpath(
            os.path.join(backend_root, "..", "archive", "langchain_agent")
        )
        assert os.path.isdir(archived), f"expected archive at {archived}"

    def test_harness_dead_files_removed(self):
        backend_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        harness_path = os.path.join(backend_root, "app", "reasoning", "harness")
        dead_files = ["loop.py", "delegate.py", "context_engine.py", "middleware_chain.py"]
        existing = [f for f in dead_files if os.path.exists(os.path.join(harness_path, f))]
        assert not existing, f"Dead files still exist: {existing}"

    def test_canvas_types_only_no_live_business_methods(self):
        try:
            from app.reasoning.canvas import Canvas
        except ModuleNotFoundError:
            return

        V1_METHODS = {"_reflection_step", "execute_tool", "_run_canvas", "_execute_node"}
        existing = [m for m in V1_METHODS if hasattr(Canvas, m)]
        assert not existing, f"Canvas 类仍有 V1 业务方法: {existing}"
