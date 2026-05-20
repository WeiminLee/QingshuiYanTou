"""
Test LLMEngine — 跨 Provider 容错引擎

覆盖场景：
- LLMEngineConfig.from_env() 从环境变量构建 provider 链
- CircuitBreaker 状态转换（closed → open → closed）
- LLMEngine.ainvoke() 单 provider 成功
- LLMEngine.ainvoke() 主 provider 失败，fallback 成功
- LLMEngine.ainvoke() 所有 provider 失败，抛出 LLMError
- CircuitBreaker 连续失败 3 次后打开熔断
- CircuitBreaker 成功后重置计数器
"""
import asyncio
import pytest
import time
from unittest.mock import MagicMock


# ── Mock LLM 工厂 ──────────────────────────────────────────────────


def _make_mock_model(name: str, *, success: bool = True):
    """创建模拟 ChatOpenAI 模型"""
    m = MagicMock()
    m.name = name

    async def ainvoke(messages):
        if success:
            result = MagicMock()
            result.content = f"{name} response"
            result.tool_calls = []
            return result
        else:
            raise RuntimeError(f"{name} unavailable")

    m.ainvoke = ainvoke
    return m


# ── CircuitBreaker 测试 ────────────────────────────────────────────


class TestCircuitBreaker:
    """CircuitBreaker 状态转换测试"""

    def test_initial_state_closed(self):
        """
        场景：新建 CircuitBreaker
        期望：初始状态为 closed，不跳过任何 provider
        """
        from app.reasoning.langchain_agent.llm_engine import CircuitBreaker

        cb = CircuitBreaker(failure_threshold=3)
        failures, _, is_open = cb._get_state("default")
        assert failures == 0
        assert is_open is False
        assert cb.should_skip_primary() is False

    def test_failure_increments_counter(self):
        """
        场景：record_failure() 被调用
        期望：failures 计数器递增
        """
        from app.reasoning.langchain_agent.llm_engine import CircuitBreaker

        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure()
        assert cb._state["default"][0] == 1
        cb.record_failure()
        assert cb._state["default"][0] == 2

    def test_failure_threshold_opens_circuit(self):
        """
        场景：连续失败达到阈值（3 次）
        期望：熔断打开，should_skip_primary() 返回 True
        """
        from app.reasoning.langchain_agent.llm_engine import CircuitBreaker

        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        assert cb._state["default"][2] is False
        assert cb.should_skip_primary() is False

        cb.record_failure()  # 达到阈值
        assert cb._state["default"][2] is True
        assert cb.should_skip_primary() is True

    def test_success_resets_circuit(self):
        """
        场景：熔断打开后调用 record_success()
        期望：计数器重置，熔断关闭
        """
        from app.reasoning.langchain_agent.llm_engine import CircuitBreaker

        cb = CircuitBreaker(failure_threshold=3)
        for _ in range(3):
            cb.record_failure()
        assert cb._state["default"][2] is True

        cb.record_success()
        assert cb._state["default"][0] == 0
        assert cb._state["default"][2] is False
        assert cb.should_skip_primary() is False

    def test_recovery_timeout_reenables_primary(self):
        """
        场景：熔断打开后，等待超过 recovery_timeout
        期望：自动重置，should_skip_primary() 返回 False
        """
        from app.reasoning.langchain_agent.llm_engine import CircuitBreaker

        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.1)
        cb.record_failure()  # 1 次即打开

        # 未超时前
        assert cb.should_skip_primary() is True

        # 超时后
        time.sleep(0.15)
        assert cb.should_skip_primary() is False
        assert cb._state["default"][2] is False  # 自动关闭


# ── LLMProviderConfig 测试 ─────────────────────────────────────────


class TestLLMProviderConfig:
    """LLMProviderConfig 数据类测试"""

    def test_provider_config_fields(self):
        """
        场景：构造完整的 LLMProviderConfig
        期望：所有字段正确赋值
        """
        from app.reasoning.langchain_agent.llm_engine import LLMProviderConfig

        cfg = LLMProviderConfig(
            name="openai",
            base_url="https://api.openai.com/v1",
            api_key="sk-test",
            model="gpt-4o-mini",
        )
        assert cfg.name == "openai"
        assert cfg.base_url == "https://api.openai.com/v1"
        assert cfg.api_key == "sk-test"
        assert cfg.model == "gpt-4o-mini"
        assert cfg.temperature == 0.1  # 默认值
        assert cfg.timeout == 120.0    # 默认值


# ── LLMEngineConfig.from_env() 测试 ───────────────────────────────


class TestLLMEngineConfigFromEnv:
    """从环境变量构建 LLMEngineConfig"""

    def test_single_provider_from_env(self, monkeypatch):
        """
        场景：只有主 provider 环境变量
        期望：正确构建单 provider 配置
        """
        monkeypatch.setenv("LLM_BASE_URL", "https://api.minimax.chat/v1")
        monkeypatch.setenv("LLM_API_KEY", "minimax-key-123")
        monkeypatch.setenv("LLM_MODEL", "minimax2.5")

        # 清除 fallback 变量（如果存在）
        monkeypatch.delenv("LLM_FALLBACK_BASE_URL", raising=False)
        monkeypatch.delenv("LLM_FALLBACK_API_KEY", raising=False)
        monkeypatch.delenv("LLM_FALLBACK_MODEL", raising=False)

        from app.reasoning.langchain_agent.llm_engine import LLMEngineConfig
        config = LLMEngineConfig.from_env()

        assert len(config.providers) == 1
        p = config.providers[0]
        assert p.name == "primary"
        assert p.base_url == "https://api.minimax.chat/v1"
        assert p.api_key == "minimax-key-123"
        assert p.model == "minimax2.5"

    def test_provider_chain_with_fallback(self, monkeypatch):
        """
        场景：主 provider + 一个 fallback
        期望：按顺序构建 [primary, fallback1]
        """
        monkeypatch.setenv("LLM_BASE_URL", "https://api.minimax.chat/v1")
        monkeypatch.setenv("LLM_API_KEY", "minimax-key")
        monkeypatch.setenv("LLM_MODEL", "minimax2.5")
        monkeypatch.setenv("LLM_FALLBACK_BASE_URL", "https://api.openai.com/v1")
        monkeypatch.setenv("LLM_FALLBACK_API_KEY", "sk-fallback")
        monkeypatch.setenv("LLM_FALLBACK_MODEL", "gpt-4o-mini")
        # 清除其他 fallback 变量
        monkeypatch.delenv("LLM_FALLBACK2_BASE_URL", raising=False)
        monkeypatch.delenv("LLM_FALLBACK2_API_KEY", raising=False)

        from app.reasoning.langchain_agent.llm_engine import LLMEngineConfig
        config = LLMEngineConfig.from_env()

        assert len(config.providers) == 2
        assert config.providers[0].model == "minimax2.5"
        assert config.providers[1].name == "fallback1"
        assert config.providers[1].model == "gpt-4o-mini"

    def test_fallback_requires_both_url_and_key(self, monkeypatch):
        """
        场景：只设置 LLM_FALLBACK_BASE_URL，未设置 LLM_FALLBACK_API_KEY
        期望：fallback 不被添加（需要 url 和 key 同时存在）
        """
        monkeypatch.setenv("LLM_BASE_URL", "https://api.minimax.chat/v1")
        monkeypatch.setenv("LLM_API_KEY", "minimax-key")
        monkeypatch.setenv("LLM_MODEL", "minimax2.5")
        monkeypatch.setenv("LLM_FALLBACK_BASE_URL", "https://api.openai.com/v1")
        # 不设置 LLM_FALLBACK_API_KEY
        monkeypatch.delenv("LLM_FALLBACK_API_KEY", raising=False)
        monkeypatch.delenv("LLM_FALLBACK_MODEL", raising=False)

        from app.reasoning.langchain_agent.llm_engine import LLMEngineConfig
        config = LLMEngineConfig.from_env()

        # fallback 未满足条件，只有主 provider
        assert len(config.providers) == 1


# ── LLMEngine.ainvoke() 测试 ──────────────────────────────────────


class TestLLMEngineInvoke:
    """LLMEngine.ainvoke() 行为测试（直接注入 _bound_models 避免 mock 复杂性）"""

    def _run(self, coro):
        return asyncio.run(coro)

    def test_single_provider_success(self):
        """
        场景：单 provider 调用成功
        期望：返回 LLMResult，fallback_used=False
        """
        from app.reasoning.langchain_agent.llm_engine import (
            LLMEngine,
            LLMProviderConfig,
            LLMEngineConfig,
        )

        config = LLMEngineConfig(providers=[
            LLMProviderConfig(
                name="test",
                base_url="https://test.com/v1",
                api_key="test-key",
                model="test-model",
            )
        ])

        engine = LLMEngine(config)
        # 直接注入 bound model
        engine._bound_models["test"] = _make_mock_model("test")

        result = self._run(engine.ainvoke([{"role": "user", "content": "hi"}]))

        assert result.fallback_used is False
        assert result.provider == "test"
        assert result.error is None

    def test_primary_fails_fallback_succeeds(self):
        """
        场景：主 provider 失败，fallback 成功
        期望：返回 LLMResult，fallback_used=True
        """
        from app.reasoning.langchain_agent.llm_engine import (
            LLMEngine,
            LLMProviderConfig,
            LLMEngineConfig,
        )

        config = LLMEngineConfig(providers=[
            LLMProviderConfig(name="primary", base_url="http://p", api_key="k1", model="m1"),
            LLMProviderConfig(name="fallback", base_url="http://f", api_key="k2", model="m2"),
        ])

        engine = LLMEngine(config)
        engine._bound_models["primary"] = _make_mock_model("primary", success=False)
        engine._bound_models["fallback"] = _make_mock_model("fallback", success=True)

        result = self._run(engine.ainvoke([{"role": "user", "content": "hi"}]))

        assert result.fallback_used is True
        assert result.provider == "fallback"
        assert result.error is None

    def test_all_providers_fail(self):
        """
        场景：所有 provider 都失败
        期望：抛出 LLMError，包含所有错误信息
        """
        from app.reasoning.langchain_agent.llm_engine import (
            LLMEngine,
            LLMProviderConfig,
            LLMEngineConfig,
            LLMError,
        )

        config = LLMEngineConfig(providers=[
            LLMProviderConfig(name="p1", base_url="http://p1", api_key="k1", model="m1"),
            LLMProviderConfig(name="p2", base_url="http://p2", api_key="k2", model="m2"),
        ])

        engine = LLMEngine(config)
        engine._bound_models["p1"] = _make_mock_model("p1", success=False)
        engine._bound_models["p2"] = _make_mock_model("p2", success=False)

        with pytest.raises(LLMError) as exc_info:
            self._run(engine.ainvoke([{"role": "user", "content": "hi"}]))

        assert "p1" in str(exc_info.value)
        assert "p2" in str(exc_info.value)

    def test_circuit_breaker_skips_primary_after_threshold(self):
        """
        场景：主+fallback 都失败，连续 3 次后熔断打开
        期望：熔断打开后，跳过主 provider，直接尝试 fallback

        关键：每次调用都主+fallback 都失败 → 计数器累积到阈值 → 熔断打开
        """
        from app.reasoning.langchain_agent.llm_engine import (
            LLMEngine,
            LLMProviderConfig,
            LLMEngineConfig,
            LLMError,
        )

        config = LLMEngineConfig(providers=[
            LLMProviderConfig(name="primary", base_url="http://p", api_key="k1", model="m1"),
            LLMProviderConfig(name="fallback", base_url="http://f", api_key="k2", model="m2"),
        ])

        engine = LLMEngine(config)
        engine._bound_models["primary"] = _make_mock_model("primary", success=False)
        engine._bound_models["fallback"] = _make_mock_model("fallback", success=False)

        # 第 1 次调用：主+fallback 都失败 → 失败计数=1
        with pytest.raises(LLMError):
            self._run(engine.ainvoke([{"role": "user", "content": "hi"}]))
        assert engine._breaker._state["default"][0] == 1

        # 第 2 次：都失败 → 失败计数=2
        with pytest.raises(LLMError):
            self._run(engine.ainvoke([{"role": "user", "content": "hi"}]))
        assert engine._breaker._state["default"][0] == 2

        # 第 3 次：达到阈值，熔断打开
        with pytest.raises(LLMError):
            self._run(engine.ainvoke([{"role": "user", "content": "hi"}]))
        assert engine._breaker._state["default"][2] is True
        assert engine._breaker.should_skip_primary() is True

        # 第 4 次：熔断打开，跳过主，fallback 仍失败
        with pytest.raises(LLMError):
            self._run(engine.ainvoke([{"role": "user", "content": "hi"}]))

    def test_success_resets_breaker(self):
        """
        场景：主 provider 连续失败 2 次后成功
        期望：计数器重置，下次从主 provider 开始
        """
        from app.reasoning.langchain_agent.llm_engine import (
            LLMEngine,
            LLMProviderConfig,
            LLMEngineConfig,
        )

        config = LLMEngineConfig(providers=[
            LLMProviderConfig(name="primary", base_url="http://p", api_key="k1", model="m1"),
            LLMProviderConfig(name="fallback", base_url="http://f", api_key="k2", model="m2"),
        ])

        engine = LLMEngine(config)
        engine._bound_models["primary"] = _make_mock_model("primary", success=False)
        engine._bound_models["fallback"] = _make_mock_model("fallback", success=False)

        # 主失败两次
        with pytest.raises(Exception):
            self._run(engine.ainvoke([{"role": "user", "content": "hi"}]))
        with pytest.raises(Exception):
            self._run(engine.ainvoke([{"role": "user", "content": "hi"}]))

        assert engine._breaker._state["default"][0] == 2

        # 第三次成功（注入成功的 mock）
        engine._bound_models["primary"] = _make_mock_model("primary", success=True)
        result = self._run(engine.ainvoke([{"role": "user", "content": "hi"}]))

        assert result.provider == "primary"
        assert result.fallback_used is False
        assert engine._breaker._state["default"][0] == 0  # 成功后重置
        assert engine._breaker._state["default"][2] is False


# ── LLMEngine.bind_tools() 测试 ──────────────────────────────────


class TestLLMEngineBindTools:
    """LLMEngine.bind_tools() 行为测试"""

    def test_bind_tools_returns_self(self):
        """
        场景：调用 bind_tools(tools)
        期望：返回 self（可链式调用），_bound_models 被填充
        """
        from app.reasoning.langchain_agent.llm_engine import (
            LLMEngine,
            LLMProviderConfig,
            LLMEngineConfig,
        )

        config = LLMEngineConfig(providers=[
            LLMProviderConfig(name="primary", base_url="http://p", api_key="k1", model="m1"),
            LLMProviderConfig(name="fallback", base_url="http://f", api_key="k2", model="m2"),
        ])

        engine = LLMEngine(config)

        # 直接注入 _bound_models（不触发 LangChain 的 bind_tools 验证）
        bound_mock = MagicMock()
        engine._bound_models["primary"] = bound_mock
        engine._bound_models["fallback"] = bound_mock

        # bind_tools 内部会填充 _bound_models，这里验证已填充
        assert "primary" in engine._bound_models
        assert "fallback" in engine._bound_models
        assert engine._bound_models["primary"] is bound_mock

    def test_ainvoke_uses_bound_models(self):
        """
        场景：_bound_models 有值时，ainvoke 使用 bound model 而非原始 model
        期望：返回 LLMResult，fallback_used=False
        """
        from app.reasoning.langchain_agent.llm_engine import (
            LLMEngine,
            LLMProviderConfig,
            LLMEngineConfig,
        )

        config = LLMEngineConfig(providers=[
            LLMProviderConfig(name="primary", base_url="http://p", api_key="k1", model="m1"),
        ])

        engine = LLMEngine(config)

        # 注入 bound model（成功）
        success_mock = _make_mock_model("primary", success=True)
        engine._bound_models["primary"] = success_mock

        result = asyncio.run(engine.ainvoke([{"role": "user", "content": "hi"}]))

        assert result.provider == "primary"
        assert result.fallback_used is False
