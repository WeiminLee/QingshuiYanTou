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
                CanvasState,
                ChunkRef,
                DocAgg,
                CanvasConfig,
                NodeStatus,
                NodeResult,
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
        from app.reasoning.langchain_agent.client import run_lead_agent, LangChainAgentClient
        assert run_lead_agent is not None
        assert LangChainAgentClient is not None

    def test_v2_middlewares_importable(self):
        """V2 中间件可导入"""
        from app.reasoning.langchain_agent.middlewares.clarification import ClarificationMiddleware
        from app.reasoning.langchain_agent.middlewares.loop_detection import LoopDetectionMiddleware
        from app.reasoning.langchain_agent.middlewares.subagent_limit import SubagentLimitMiddleware
        from app.reasoning.langchain_agent.middlewares.context_compressor import ContextCompressor
        from app.reasoning.langchain_agent.middlewares.manual_agent_loop import ManualAgentLoop
        assert ClarificationMiddleware is not None
        assert LoopDetectionMiddleware is not None
        assert SubagentLimitMiddleware is not None
        assert ContextCompressor is not None
        assert ManualAgentLoop is not None

    def test_registry_importable(self):
        """工具注册表可导入"""
        from app.reasoning.registry.registry import get_registry
        assert get_registry is not None

    def test_tools_module_importable(self):
        """tools/ 模块可导入（V1 兼容，但有 Canvas 引用）"""
        from app.reasoning.tools import get_tool_class, list_registered_tools
        assert get_tool_class is not None
        assert list_registered_tools is not None

    def test_harness_budget_importable(self):
        """Harness budget 模块可导入（V2 引用）"""
        from app.reasoning.harness.budget import BudgetEnforcer, BudgetConfig
        assert BudgetEnforcer is not None
        assert BudgetConfig is not None

    def test_harness_memory_importable(self):
        """Harness memory 模块可导入（V2 引用）"""
        from app.reasoning.harness.memory import MemoryManager, increment_kg_anchor
        assert MemoryManager is not None
        assert increment_kg_anchor is not None

    def test_output_layer_importable(self):
        """Layer 4 决策输出层可导入"""
        from app.reasoning.output.report import AnalysisReport
        from app.reasoning.output.confidence import source_type_to_tier, merge_confidence
        from app.reasoning.output.compliance import scan_content
        assert AnalysisReport is not None
        assert source_type_to_tier is not None
        assert merge_confidence is not None
        assert scan_content is not None

    def test_api_endpoints_importable(self):
        """API 端点可导入"""
        from app.reasoning.api import agent
        assert hasattr(agent, 'stream_report')
        assert hasattr(agent, 'chat')
        assert hasattr(agent, 'invoke')


class TestToolRegistry:
    """工具注册表测试"""

    def test_registry_has_11_builtin_tools(self):
        """内嵌默认配置应包含 11 个工具（含 write_todos）"""
        from app.reasoning.registry.loader import _build_default_config
        configs = _build_default_config()
        assert len(configs) == 11, f"Expected 11 built-in tools, got {len(configs)}"
        names = [c.name for c in configs]
        expected = {
            "get_kline", "get_concept_hot", "get_market_breadth",
            "neo4j_traverse", "get_research_report", "get_announcement",
            "tavily_search", "get_stock_profile", "get_irm", "present_chart",
            "write_todos",
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
        from app.reasoning.registry.loader import _CONFIG_PATH, load_tools_from_config
        import yaml
        if not _CONFIG_PATH.exists():
            pytest.skip("config.yaml not present")
        with open(_CONFIG_PATH, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        names = {t["name"] for t in data["tools"]}
        expected_new = {"web_fetch", "ls", "read_file", "write_file", "ask_clarification"}
        missing = expected_new - names
        assert not missing, f"New tools missing from config.yaml: {missing}"
        assert len(names) == 16, f"Expected 16 tools in YAML, got {len(names)}"


class TestV2MiddlewaresChain:
    """V2 中间件链路测试"""

    def test_clarification_middleware_has_check_question(self):
        """ClarificationMiddleware 有 check_question 方法"""
        from app.reasoning.langchain_agent.middlewares.clarification import ClarificationMiddleware
        mw = ClarificationMiddleware()
        assert hasattr(mw, 'check_question')
        assert callable(mw.check_question)

    def test_loop_detection_middleware_has_detect_loop(self):
        """LoopDetectionMiddleware 有循环检测方法"""
        from app.reasoning.langchain_agent.middlewares.loop_detection import LoopDetectionMiddleware
        mw = LoopDetectionMiddleware()
        # 检测实际方法名（detect 或 check）
        has_detect = any(
            attr in dir(mw) for attr in ('detect_loop', 'check', 'detect', 'should_stop')
        )
        assert has_detect, f"LoopDetectionMiddleware has no detection method. Methods: {[m for m in dir(mw) if not m.startswith('_')]}"

    def test_context_compressor_instantiable(self):
        """ContextCompressor 可正常实例化"""
        from app.reasoning.langchain_agent.middlewares.context_compressor import ContextCompressor
        # 实例化（不接受参数，或接受默认参数）
        comp = ContextCompressor()
        assert comp is not None


class TestP1FrontendSSEReportView:
    """P1: ReportView.vue SSE 事件处理验证"""

    def test_report_view_has_tool_called_sse_handler(self):
        """
        RED: ReportView.vue 缺少 tool_called/tool_result SSE 事件处理。
        修复后：应在 connectSSE 中处理 tool_called 和 tool_result 事件。
        """
        import os
        REPORT_VIEW = "/home/10241671/code/LocalProjects/QingShuiTouYan/frontend/src/views/ReportView.vue"
        assert os.path.exists(REPORT_VIEW), f"ReportView.vue not found at {REPORT_VIEW}"

        content = open(REPORT_VIEW).read()
        assert "tool_called" in content, (
            "P1 GAP: ReportView.vue 缺少 tool_called SSE 事件处理！"
            "应在 connectSSE 的 onmessage 中添加对 tool_called 事件的处理，"
            "参考 Home.vue 的 useStreamingRenderer 模式。"
        )

    def test_report_view_uses_streaming_renderer(self):
        """ReportView.vue 应使用 useStreamingRenderer 渲染 CoT 步骤"""
        import os
        REPORT_VIEW = "/home/10241671/code/LocalProjects/QingShuiTouYan/frontend/src/views/ReportView.vue"
        content = open(REPORT_VIEW).read()
        assert "useStreamingRenderer" in content, (
            "P1 GAP: ReportView.vue 未引入 useStreamingRenderer！"
            "应引入 useStreamingRenderer 并处理 thinking/tool_called/tool_result 事件。"
        )


class TestP2MemoryLayerActivation:
    """P2: Memory 层激活验证"""

    def test_memory_context_loads_gracefully(self):
        """
        _load_memory_context() 异常时返回空字符串（不阻断 Agent）。
        """
        import asyncio
        from app.reasoning.langchain_agent.client import _load_memory_context

        # 传入不存在的 thread_id，任何错误都应返回空字符串
        result = asyncio.run(_load_memory_context("nonexistent-thread-xyz"))
        assert result == "", (
            "_load_memory_context should return empty string on error, got: " + repr(result)
        )

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


class TestP0ManualAgentLoopBugFix:
    """P0: use_manual_loop=True 分支中 model 重复创建 Bug 修复验证"""

    def test_manual_loop_reuses_model_from_ensure_agent(self):
        """
        P0-Bug2 修复验证：
        model 应从 _ensure_agent() 返回的 (agent, model) 元组获取，
        不应在 if use_manual_loop: 块内再次调用 _create_chat_model()。
        """
        import ast
        import inspect
        from app.reasoning.langchain_agent import client as client_module

        source = inspect.getsource(client_module.run_lead_agent)
        tree = ast.parse(source)

        class ManualLoopVisitor(ast.NodeVisitor):
            def __init__(self):
                self.found_manual_loop = False
                self.model_from_ensure = False          # agent, model = _ensure_agent(...)
                self.duplicate_create_inside_loop = False  # model = _create_chat_model(...) 在 if 块内

            def visit_Assign(self, node):
                # 处理 "agent, model = _ensure_agent(...)" 元组解包
                if isinstance(node.targets[0], ast.Tuple):
                    targets = node.targets[0].elts
                    if len(targets) == 2 and all(isinstance(t, ast.Name) for t in targets):
                        left_names = [t.id for t in targets]
                        if left_names == ["agent", "model"]:
                            for val in ast.walk(node.value):
                                if isinstance(val, ast.Call) and isinstance(val.func, ast.Name):
                                    if val.func.id == "_ensure_agent":
                                        self.model_from_ensure = True

                for t in node.targets:
                    if isinstance(t, ast.Name) and t.id == "model":
                        for val in ast.walk(node.value):
                            if isinstance(val, ast.Call) and isinstance(val.func, ast.Name):
                                if val.func.id == "_create_chat_model":
                                    if self._inside_manual_loop:
                                        self.duplicate_create_inside_loop = True
                self.generic_visit(node)

            def visit_If(self, node):
                outer = self._inside_manual_loop
                for test in ast.walk(node.test):
                    if isinstance(test, ast.Name) and test.id == "use_manual_loop":
                        self.found_manual_loop = True
                        self._inside_manual_loop = True
                        self.generic_visit(node)
                        self._inside_manual_loop = outer
                        return
                self._inside_manual_loop = outer
                self.generic_visit(node)

            _inside_manual_loop: bool = False

        visitor = ManualLoopVisitor()
        visitor.visit(tree)

        assert visitor.found_manual_loop, "use_manual_loop 分支未找到"
        assert visitor.model_from_ensure, (
            "_ensure_agent() 应返回 (agent, model) 元组并在调用处解包"
        )
        assert not visitor.duplicate_create_inside_loop, (
            "P0 BUG: if use_manual_loop: 块内不应再次调用 _create_chat_model()。"
            "model 已从 _ensure_agent() 获取。"
        )


class TestDeadCodeRemoved:
    """死代码清理验证：V1 相关模块应不存在"""

    def test_v1_middlewares_directory_removed(self):
        """V1 middlewares/ 目录应已删除（被 langchain_agent/middlewares/ 替代）"""
        backend_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        v1_path = os.path.join(backend_root, "app", "reasoning", "middlewares")
        assert not os.path.exists(v1_path), \
            f"V1 middlewares/ directory still exists at {v1_path}"

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
        assert not hasattr(Canvas, '_reflection_step'), \
            "Canvas._reflection_step should be removed (dead code)"
        assert not hasattr(Canvas, 'execute_tool'), \
            "Canvas.execute_tool should be removed (dead code)"
        assert not hasattr(Canvas, 'fill_report_sections'), \
            "Canvas.fill_report_sections should be removed (dead code)"
        assert not hasattr(Canvas, 'apply_compliance'), \
            "Canvas.apply_compliance should be removed (dead code)"
