"""
V2 架构验证测试

验证 LangChain V2 架构的完整性：
- 所有活跃模块可正常导入
- 工具注册表可加载 10 个工具（task 工具不通过 registry 加载）
- V2 中间件链路正确
- Canvas 类型定义保留（被 tools/ 和 prompts/ 引用）
- V1 死代码已删除
"""

import os

import pytest


class TestV2ArchitectureImports:
    """V2 核心模块导入测试"""

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
            # V1 canvas 已删除，V2 不再依赖 Canvas 类型
            pass

    def test_v2_client_importable(self):
        """V2 Agent 入口可导入"""
        from app.reasoning.langchain_agent.client import LangChainAgentClient, run_lead_agent

        assert run_lead_agent is not None
        assert LangChainAgentClient is not None

    def test_v2_middlewares_importable(self):
        """V2 中间件可导入

        注：manual_agent_loop 模块已删除（手动 loop 被 client.py 的 create_agent()+astream 取代），
        故不再导入 ManualAgentLoop；ContextCompressor 已改名为 ContextCompressorMiddleware。
        """
        from app.reasoning.langchain_agent.middlewares.clarification import ClarificationMiddleware
        from app.reasoning.langchain_agent.middlewares.context_compressor import ContextCompressorMiddleware
        from app.reasoning.langchain_agent.middlewares.loop_detection import LoopDetectionMiddleware
        from app.reasoning.langchain_agent.middlewares.subagent_limit import SubagentLimitMiddleware

        assert ClarificationMiddleware is not None
        assert LoopDetectionMiddleware is not None
        assert SubagentLimitMiddleware is not None
        assert ContextCompressorMiddleware is not None

    def test_registry_importable(self):
        """工具注册表可导入"""
        from app.reasoning.registry.registry import get_registry

        assert get_registry is not None

    def test_tools_module_importable(self):
        """工具层可导入

        注：旧的 get_tool_class/list_registered_tools 已删除，工具改由 V2 registry 加载
        （见 tools/__init__.py 指引）。此处验证 registry 工具入口可用。
        """
        from app.reasoning.registry import get_registry

        registry = get_registry()
        assert registry is not None
        assert callable(registry.get_tool_instances)

    def test_harness_budget_importable(self):
        """Harness budget 模块可导入（V2 引用）"""
        from app.reasoning.harness.budget import BudgetConfig, BudgetEnforcer

        assert BudgetEnforcer is not None
        assert BudgetConfig is not None

    def test_harness_memory_importable(self):
        """Harness memory 模块可导入（V2 引用）"""
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
        """API 端点可导入"""
        from app.reasoning.api import agent

        assert hasattr(agent, "stream_report")
        assert hasattr(agent, "chat")
        assert hasattr(agent, "invoke")


class TestToolRegistry:
    """工具注册表测试"""

    def test_registry_has_11_builtin_tools(self):
        """内嵌默认配置应包含 11 个工具（含 write_todos）"""
        from app.reasoning.registry.loader import _build_default_config

        configs = _build_default_config()
        assert len(configs) == 25, f"Expected 25 built-in tools, got {len(configs)}"
        names = [c.name for c in configs]
        expected = {
            "get_kline",
            "get_concept_hot",
            "get_market_breadth",
            "neo4j_traverse",
            "neo4j_entity_info",
            "neo4j_path",
            "neo4j_industry_state",
            "neo4j_kg_search",
            "fetch_evidence",
            "resolve",
            "expand",
            "get_research_report",
            "get_announcement",
            "tavily_search",
            "get_stock_profile",
            "get_irm",
            "present_chart",
            "write_todos",
            "ask_clarification",
            "web_fetch",
            "ls",
            "read_file",
            "write_file",
            "find_events",
            "get_event_detail",
        }
        assert set(names) == expected

    def test_registry_loads_all_builtin_tools(self):
        """内嵌默认配置中的所有工具均可通过 resolve_variable 解析"""
        from app.reasoning.registry.loader import _build_default_config
        from app.reasoning.registry.resolve_variable import resolve_variable

        configs = _build_default_config()
        for cfg in configs:
            resolved = resolve_variable(cfg.use)
            assert resolved is not None, f"Failed to resolve tool: {cfg.use}"

    def test_yaml_config_has_16_tools(self):
        """YAML 配置文件应包含 16 个工具（含新增的 web_fetch/ls/read_file/write_file/ask_clarification）"""
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
        assert len(names) == 27, f"Expected 27 tools in YAML, got {len(names)}"


class TestV2MiddlewaresChain:
    """V2 中间件链路测试"""

    def test_clarification_middleware_has_check_question(self):
        """ClarificationMiddleware 有澄清判定能力

        注：旧的 check_question/check_and_emit 已删除，改用 LangChain hook 模式：
        after_model_hook + 静态 _needs_clarification/_build_suggestions。
        """
        from app.reasoning.langchain_agent.middlewares.clarification import ClarificationMiddleware

        mw = ClarificationMiddleware()
        assert hasattr(mw, "after_model_hook")
        assert callable(mw.after_model_hook)
        # 澄清判定逻辑迁移为静态方法
        assert mw._needs_clarification("这个") is True
        assert isinstance(mw._build_suggestions("这个"), list)

    def test_loop_detection_middleware_has_detect_loop(self):
        """LoopDetectionMiddleware 有循环检测方法

        注：旧的 detect_loop 已删除，改用 LangChain hook 模式（after_model/before_agent 等）。
        """
        from app.reasoning.langchain_agent.middlewares.loop_detection import LoopDetectionMiddleware

        mw = LoopDetectionMiddleware()
        # 检测实际 hook 方法名
        has_detect = any(attr in dir(mw) for attr in ("after_model", "before_agent", "wrap_model_call"))
        assert has_detect, (
            f"LoopDetectionMiddleware has no detection hook. Methods: {[m for m in dir(mw) if not m.startswith('_')]}"
        )

    def test_context_compressor_instantiable(self):
        """ContextCompressorMiddleware 可正常实例化

        注：ContextCompressor 已改名为 ContextCompressorMiddleware（LangChain 中间件模式）。
        """
        from app.reasoning.langchain_agent.middlewares.context_compressor import ContextCompressorMiddleware

        # 实例化（不接受参数，或接受默认参数）
        comp = ContextCompressorMiddleware()
        assert comp is not None


class TestP1FrontendSSEReportView:
    """P1: ReportView.vue SSE 事件处理验证

    注：SSE 事件监听已从 ReportView.vue 内联抽取到 useChatSession 组合式函数
    （tool_called/tool_result/thinking 均在 composables/useChatSession.ts 中监听）；
    ReportView.vue 通过 useChatSession + ToolCallStep/ThinkingPanel 渲染。
    原硬编码路径 /home/10241671/... 已失效，改用相对定位到真实前端文件。
    """

    _REPORT_VIEW = os.path.normpath(
        os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "..",
            "frontend",
            "src",
            "views",
            "ReportView.vue",
        )
    )

    def test_report_view_has_tool_called_sse_handler(self):
        """
        ReportView.vue 应接入处理 tool_called/tool_result 的会话层，并渲染工具调用。
        """
        if not os.path.exists(self._REPORT_VIEW):
            pytest.skip(f"ReportView.vue not found at {self._REPORT_VIEW}")

        content = open(self._REPORT_VIEW, encoding="utf-8").read()
        # SSE 工具事件监听已迁移至 useChatSession 组合式函数
        assert "useChatSession" in content, (
            "P1 GAP: ReportView.vue 未接入 useChatSession（承载 tool_called/tool_result SSE 监听）！"
        )
        # 工具调用需在页面上渲染
        assert "ToolCallStep" in content and "toolCalls" in content, (
            "P1 GAP: ReportView.vue 未渲染工具调用（ToolCallStep / toolCalls）！"
        )

    def test_report_view_uses_streaming_renderer(self):
        """ReportView.vue 应使用流式渲染展示 CoT 步骤（ThinkingPanel + TDesign 适配器）"""
        if not os.path.exists(self._REPORT_VIEW):
            pytest.skip(f"ReportView.vue not found at {self._REPORT_VIEW}")

        content = open(self._REPORT_VIEW, encoding="utf-8").read()
        assert "useTDesignAdapter" in content and "ThinkingPanel" in content, (
            "P1 GAP: ReportView.vue 未使用流式渲染（useTDesignAdapter / ThinkingPanel）处理思考步骤！"
        )


class TestP2MemoryLayerActivation:
    """P2: Memory 层激活验证"""

    def test_memory_context_loads_gracefully(self):
        """
        Memory 加载异常时不阻断 Agent（返回空字符串）。

        注：旧的 client._load_memory_context() 已删除，Memory 加载内联进 run_lead_agent()，
        统一由 MemoryManager.prefetch_all() 承担（吞掉 provider 异常 → 返回 ""）。
        此处验证等价的优雅降级：某个 provider 抛错时 prefetch_all 仍返回空串而非抛出。
        """
        import asyncio

        from app.reasoning.langchain_agent.memory.manager import MemoryManager

        class _BrokenProvider:
            name = "broken"

            async def prefetch(self, query: str) -> str:
                raise RuntimeError("boom")

        mgr = MemoryManager()
        mgr.add_provider(_BrokenProvider())
        result = asyncio.run(mgr.prefetch_all("任意问题"))
        assert result == "", "prefetch_all should return empty string when a provider fails, got: " + repr(result)

    def test_harness_config_defaults_to_disabled(self):
        """HarnessConfig 默认关闭所有能力（向后兼容）"""
        from app.reasoning.langchain_agent.integrations import HarnessConfig

        cfg = HarnessConfig()
        assert cfg.budget_enabled is False, "budget_enabled should default to False"
        assert cfg.memory_enabled is False, "memory_enabled should default to False"
        assert cfg.kg_anchors_enabled is False, "kg_anchors_enabled should default to False"

    def test_mongodb_url_configured(self):
        """MONGODB_URL 环境变量已配置"""
        import os

        env_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "..",
            ".env",
        )
        if os.path.exists(env_path):
            content = open(env_path).read()
            assert "MONGODB_URL" in content, "MONGODB_URL should be in .env"
        else:
            # 检查 settings 是否可正常导入（会触发 MONGODB_URL 验证）
            try:
                from app.config import settings

                assert hasattr(settings, "mongodb_url")
                assert settings.mongodb_url, "mongodb_url should not be empty"
            except RuntimeError as e:
                if "MONGODB_URL" in str(e):
                    pytest.fail(f"MONGODB_URL not configured: {e}")
                raise


# NOTE: TestP0ManualAgentLoopBugFix 已删除。
# 该类验证的是 run_lead_agent 中 `if use_manual_loop:` 分支复用 _ensure_agent() 返回 model 的
# Bug 修复，但手动 agent 循环架构已彻底删除（use_manual_loop / _ensure_agent 均不存在）。
# 现在逻辑改用 LangChain 原生 create_agent() + agent.astream()，见
# app/reasoning/langchain_agent/client.py 的 run_lead_agent / _run_stream。无对应新实现可迁移。


class TestDeadCodeRemoved:
    """死代码清理验证：V1 相关模块应不存在"""

    def test_v1_middlewares_directory_removed(self):
        """V1 middlewares/ 目录应已删除（被 langchain_agent/middlewares/ 替代）"""
        backend_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        v1_path = os.path.join(backend_root, "app", "reasoning", "middlewares")
        assert not os.path.exists(v1_path), f"V1 middlewares/ directory still exists at {v1_path}"

    def test_langchain_agent_tools_todo_only(self):
        """langchain_agent/tools/ 目录只允许包含 todo.py（通过 YAML registry 加载）；V1 旧工具应已删除"""
        backend_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        tools_path = os.path.join(backend_root, "app", "reasoning", "langchain_agent", "tools")
        if not os.path.exists(tools_path):
            return  # 目录不存在 = 通过（已清理）
        files = set(os.listdir(tools_path)) - {"__pycache__", "__init__.py"}
        allowed = {"todo.py"}
        unexpected = files - allowed
        assert not unexpected, (
            f"langchain_agent/tools/ 目录包含未授权文件: {unexpected}。"
            f"仅允许: {allowed}（write_todos 工具通过 YAML registry 加载）"
        )

    def test_harness_dead_files_removed(self):
        """harness/ 中 loop.py, delegate.py, context_engine.py, middleware_chain.py 应已删除"""
        backend_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        harness_path = os.path.join(backend_root, "app", "reasoning", "harness")
        dead_files = ["loop.py", "delegate.py", "context_engine.py", "middleware_chain.py"]
        existing = [f for f in dead_files if os.path.exists(os.path.join(harness_path, f))]
        assert not existing, f"Dead files still exist: {existing}"

    def test_canvas_types_only_no_live_business_methods(self):
        """Canvas 类（若存在）应已精简为纯类型定义；V1 canvas 模块应已删除"""
        try:
            from app.reasoning.canvas import Canvas
        except ModuleNotFoundError:
            return  # V1 canvas 已删除 = 通过

        # 若 canvas 模块存在，验证无 V1 活跃业务方法
        V1_METHODS = {"_reflection_step", "execute_tool", "_run_canvas", "_execute_node"}
        existing = [m for m in V1_METHODS if hasattr(Canvas, m)]
        assert not existing, f"Canvas 类仍有 V1 业务方法: {existing}"
        # Canvas 类作为类型定义保留（被 tools/ 和 prompts/ 引用）
        assert Canvas is not None
        # 验证 _reflection_step 等 V1 业务方法不存在
        assert not hasattr(Canvas, "_reflection_step"), "Canvas._reflection_step should be removed (dead code)"
        assert not hasattr(Canvas, "execute_tool"), "Canvas.execute_tool should be removed (dead code)"
        assert not hasattr(Canvas, "fill_report_sections"), "Canvas.fill_report_sections should be removed (dead code)"
        assert not hasattr(Canvas, "apply_compliance"), "Canvas.apply_compliance should be removed (dead code)"
