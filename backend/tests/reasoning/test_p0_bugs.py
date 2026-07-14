"""
tests/reasoning/test_p0_bugs.py

P0 Bug TDD — Bug #2, Bug #4

验收标准：
- Bug #2: LLMEngine 初始化使用正确方法（LLMEngineConfig.from_env）
- Bug #4: get_result 死代码（重复 get_task 调用）已移除

Run: uv run --directory backend python -m pytest tests/reasoning/test_p0_bugs.py -v
"""

from unittest.mock import MagicMock, patch

# ── Bug #2: LLMEngine.from_settings() 不存在 ─────────────────────────


class TestLLMEngineInitialization:
    """
    Bug #2: context_compressor.py 第157行调用 LLMEngine.from_settings(app_settings)
    但 LLMEngine 没有 from_settings() 方法，正确用法是 LLMEngine(LLMEngineConfig.from_env())
    """

    def test_llm_engine_has_no_from_settings_method(self):
        """LLMEngine 不应暴露 from_settings 工厂方法"""
        from app.reasoning.langchain_agent.llm_engine import LLMEngine

        assert not hasattr(LLMEngine, "from_settings"), (
            "LLMEngine 不应有 from_settings 方法（应通过 LLMEngineConfig.from_env 构建）"
        )

    def test_llm_engine_config_has_from_env(self):
        """LLMEngineConfig 暴露 from_env 工厂方法"""
        from app.reasoning.langchain_agent.llm_engine import LLMEngineConfig

        assert hasattr(LLMEngineConfig, "from_env"), "LLMEngineConfig 应有 from_env 工厂方法"
        assert callable(LLMEngineConfig.from_env)

    def test_llm_engine_initialized_via_config(self):
        """LLMEngine 应通过 LLMEngineConfig 实例化，而非 from_settings"""
        from app.reasoning.langchain_agent.llm_engine import LLMEngine, LLMEngineConfig

        # 正确用法：用 config 构建 engine
        config = LLMEngineConfig(providers=[])
        engine = LLMEngine(config)
        assert hasattr(engine, "ainvoke")
        assert hasattr(engine, "bind_tools")

    # 注：test_get_llm_engine_uses_correct_init_method / test_source_uses_correct_factory
    # 已删除——它们验证 context_compressor 的模块级单例 _get_llm_engine()，但该架构已重写为
    # ContextCompressorMiddleware 持有 self._llm/_fallback_llm 实例（见 _call_summary_llm），
    # _get_llm_engine 不再存在。LLMEngine 的正确构建方式仍由上面 3 个测试覆盖。


# ── Bug #4: get_result 死代码 ────────────────────────────────────────


class TestGetResultDeadCode:
    """
    Bug #4: agent.py get_result() 在第257行已查到 task 后，
    第273行再次调用 _task_manager.get_task(task_id) 是永远执行不到的死代码。
    """

    def test_get_result_returns_after_first_get_task(self):
        """
        验证 get_result 逻辑：
        - 首次 get_task 命中则直接返回（不应继续执行到第二个 get_task）
        - 第二个 get_task 调用在逻辑上冗余（死代码）
        """
        import inspect

        from app.reasoning.api.agent import get_result

        src = inspect.getsource(get_result)

        # 统计 get_task 调用次数
        call_count = src.count("_task_manager.get_task(task_id)")

        # Bug #4: 修复前有 2 次调用，修复后应为 1 次
        assert call_count == 1, (
            f"get_result 中 _task_manager.get_task(task_id) 应仅调用 1 次（首次命中即返回），"
            f"当前有 {call_count} 次，说明存在死代码"
        )

    def test_get_result_returns_early_on_task_hit(self):
        """
        验证 get_result 流程：
        1. 查 _task_manager.get_task(id) -> 命中则返回 ResultResponse
        2. 不再继续执行其他分支（无冗余 get_task）
        """

        from app.reasoning.api.agent import ResultResponse, get_result

        # Mock 任务存在
        mock_task = {
            "status": "completed",
            "result": {"content": "ok", "reasoning": "test"},
            "thread_id": "thread-1",
        }
        mock_manager = MagicMock()
        mock_manager.get_task.return_value = mock_task

        import asyncio

        @patch("app.reasoning.api.agent._task_manager", mock_manager)
        async def run():
            result = await get_result(task_id="task-123")
            return result

        result = asyncio.run(run())

        assert isinstance(result, ResultResponse)
        assert result.content == "ok"
        assert result.reasoning == "test"
        # 验证 get_task 仅被调用 1 次
        assert mock_manager.get_task.call_count == 1, f"get_task 应仅调用 1 次，实际 {mock_manager.get_task.call_count}"
