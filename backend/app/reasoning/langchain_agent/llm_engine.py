"""
LLMEngine — 跨 Provider 容错引擎

设计原则（fail fast, fall back fast）：
- 不做重试（LLM 失败大概率是真的失败了，重试无意义）
- 按配置的 provider 链依次尝试，任一成功即返回
- CircuitBreaker 防止连续失败时浪费资源

环境变量配置（用户可配置）：
- LLM_BASE_URL / LLM_API_KEY / LLM_MODEL — 主 provider（从 app.config.settings 读取）
- LLM_FALLBACK_BASE_URL / LLM_FALLBACK_API_KEY / LLM_FALLBACK_MODEL — fallback provider 1
- LLM_FALLBACK2_BASE_URL / LLM_FALLBACK2_API_KEY / LLM_FALLBACK2_MODEL — fallback provider 2
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any

from langchain_openai import ChatOpenAI

# ── 配置模型 ────────────────────────────────────────────────────────


@dataclass
class LLMProviderConfig:
    """单个 LLM Provider 配置"""

    name: str
    base_url: str
    api_key: str
    model: str
    temperature: float = 0.1
    timeout: float = 120.0


@dataclass
class LLMEngineConfig:
    """LLM Engine 配置，包含按优先级排序的 provider 链"""

    providers: list[LLMProviderConfig] = field(default_factory=list)

    @classmethod
    def from_env(cls) -> LLMEngineConfig:
        """
        从 app.config.settings + 环境变量构建 provider 链。

        主 provider：settings.llm_base_url / settings.llm_api_key / settings.llm_model
        Fallback provider：LLM_FALLBACK_BASE_URL / LLM_FALLBACK_API_KEY / LLM_FALLBACK_MODEL（环境变量）
        Fallback2 provider：LLM_FALLBACK2_BASE_URL / LLM_FALLBACK2_API_KEY / LLM_FALLBACK2_MODEL（环境变量）
        """
        from app.config import settings

        base_url = (os.getenv("LLM_BASE_URL") or settings.llm_base_url or "").strip()
        api_key = (os.getenv("LLM_API_KEY") or settings.llm_api_key or "").strip()
        model = (os.getenv("LLM_MODEL") or settings.llm_model or "minimax2.5").strip()

        if not base_url or not api_key:
            raise ValueError(
                "Missing required configuration: LLM_BASE_URL/llm_base_url and LLM_API_KEY/llm_api_key must be set"
            )

        providers = [
            LLMProviderConfig(
                name="primary",
                base_url=base_url,
                api_key=api_key,
                model=model,
            )
        ]

        # Fallback provider 1
        fb1_url = os.getenv("LLM_FALLBACK_BASE_URL", "").strip()
        fb1_key = os.getenv("LLM_FALLBACK_API_KEY", "").strip()
        fb1_model = os.getenv("LLM_FALLBACK_MODEL", "").strip()
        if fb1_url and fb1_key:
            providers.append(
                LLMProviderConfig(
                    name="fallback1",
                    base_url=fb1_url,
                    api_key=fb1_key,
                    model=fb1_model or model,
                )
            )

        # Fallback provider 2
        fb2_url = os.getenv("LLM_FALLBACK2_BASE_URL", "").strip()
        fb2_key = os.getenv("LLM_FALLBACK2_API_KEY", "").strip()
        fb2_model = os.getenv("LLM_FALLBACK2_MODEL", "").strip()
        if fb2_url and fb2_key:
            providers.append(
                LLMProviderConfig(
                    name="fallback2",
                    base_url=fb2_url,
                    api_key=fb2_key,
                    model=fb2_model or model,
                )
            )

        return cls(providers=providers)


# ── CircuitBreaker ─────────────────────────────────────────────────


@dataclass
class CircuitBreaker:
    """
    轻量熔断器（per-tenant 隔离）。

    行为：
    - 连续失败达到阈值 → 打开熔断，下次跳过主 provider
    - 任一 provider 成功 → 重置计数器
    - recovery_timeout 后 → 自动重置，允许重试主 provider

    Bug #1 Fix: 每个 tenant_id 独立计数，彻底隔离多租户之间的熔断影响。
    """

    failure_threshold: int = 3
    recovery_timeout: float = 60.0

    # per-tenant 状态：tenant_id -> (failures, last_failure_time, is_open)
    _state: dict[str, tuple[int, float, bool]] = field(default_factory=dict)

    def _get_state(self, tenant_id: str) -> tuple[int, float, bool]:
        if tenant_id not in self._state:
            self._state[tenant_id] = (0, 0.0, False)
        return self._state[tenant_id]

    def _set_state(self, tenant_id: str, failures: int, last_failure_time: float, is_open: bool) -> None:
        self._state[tenant_id] = (failures, last_failure_time, is_open)

    def record_failure(self, tenant_id: str = "default") -> None:
        """记录一次失败（按 tenant 隔离）"""
        failures, last_failure_time, is_open = self._get_state(tenant_id)
        failures += 1
        last_failure_time = time.monotonic()
        if failures >= self.failure_threshold:
            is_open = True
        self._set_state(tenant_id, failures, last_failure_time, is_open)

    def record_success(self, tenant_id: str = "default") -> None:
        """记录成功，重置熔断器（按 tenant 隔离）"""
        self._set_state(tenant_id, 0, 0.0, False)

    def should_skip_primary(self, tenant_id: str = "default") -> bool:
        """
        判断是否应跳过主 provider（按 tenant 判断）。

        规则：
        - 熔断未打开 → 不跳过
        - 熔断打开但已超 recovery_timeout → 自动重置，不跳过
        - 熔断打开且未超时 → 跳过主 provider
        """
        failures, last_failure_time, is_open = self._get_state(tenant_id)
        if not is_open:
            return False
        elapsed = time.monotonic() - last_failure_time
        if elapsed > self.recovery_timeout:
            self._set_state(tenant_id, failures, last_failure_time, False)
            return False
        return True


# ── LLMEngine ──────────────────────────────────────────────────────


@dataclass
class LLMResult:
    """LLM 调用结果"""

    result: Any
    provider: str
    fallback_used: bool
    error: str | None = None
    usage: dict | None = None  # Phase G: token 使用统计 {prompt_tokens, completion_tokens, total_tokens}


class LLMError(Exception):
    """所有 provider 都失败时的错误"""

    def __init__(self, message: str, *, errors: list[str] | None = None):
        super().__init__(message)
        self.errors = errors or []


class LLMEngine:
    """
    跨 Provider 容错引擎。

    按配置的 provider 链依次尝试，任一成功即返回。
    CircuitBreaker 防止连续失败时反复尝试不可用的主 provider。

    使用方式：
        config = LLMEngineConfig.from_env()
        engine = LLMEngine(config)
        bound = engine.bind_tools(tools)
        result = await bound.ainvoke(messages)
    """

    def __init__(self, config: LLMEngineConfig):
        self.config = config
        self._models: dict[str, ChatOpenAI] = {}
        self._bound_models: dict[str, Any] = {}  # provider.name -> bound model
        # Bug #1 Fix: CircuitBreaker 状态按 tenant_id 隔离，多租户互不影响
        self._breaker = CircuitBreaker()

    def _get_model(self, provider: LLMProviderConfig) -> ChatOpenAI:
        """获取或创建 ChatOpenAI 实例（按 name 缓存）"""
        if provider.name not in self._models:
            self._models[provider.name] = ChatOpenAI(
                model=provider.model,
                api_key=provider.api_key,
                base_url=provider.base_url,
                temperature=provider.temperature,
                timeout=provider.timeout,
            )
        return self._models[provider.name]

    def _get_primary_model(self) -> ChatOpenAI | None:
        """获取当前主 provider 的 ChatOpenAI 实例（供 create_agent 使用）"""
        if not self.config.providers:
            return None
        return self._get_model(self.config.providers[0])

    def bind_tools(self, tools: list) -> LLMEngine:
        """
        为所有 provider 绑定工具。

        使用方式：
            engine = LLMEngine(config)
            bound = engine.bind_tools(tools)
            result = await bound.ainvoke(messages)  # 使用已绑定工具的模型
        """
        for provider in self.config.providers:
            model = self._get_model(provider)
            self._bound_models[provider.name] = model.bind_tools(tools)
        return self

    async def ainvoke(
        self,
        messages: list,
        tenant_id: str = "default",
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResult:
        """
        按 provider 链依次调用，优先使用已 bind_tools 的模型。

        Args:
            messages: LangChain 消息列表
            tenant_id: 租户标识，用于 per-tenant 熔断隔离（Bug #1 Fix）
            temperature: 可选，覆盖模型的 temperature
            max_tokens: 可选，覆盖模型的最大 token 数

        Returns:
            LLMResult(result, provider, fallback_used, error, usage)
        """
        errors: list[str] = []

        # 确定起始索引（熔断打开时跳过主 provider，按 tenant 隔离）
        start_idx = 1 if self._breaker.should_skip_primary(tenant_id) else 0
        if start_idx > 0:
            errors.append(f"primary: circuit_breaker_open (skipped, tenant={tenant_id})")

        for i, provider in enumerate(self.config.providers):
            if i < start_idx:
                continue

            model = self._get_model(provider)
            # 优先使用已 bind_tools 的模型
            callable_model = self._bound_models.get(provider.name, model)

            try:
                invoke_kwargs = {"messages": messages}
                if temperature is not None:
                    invoke_kwargs["temperature"] = temperature
                if max_tokens is not None:
                    invoke_kwargs["max_tokens"] = max_tokens
                result = await callable_model.ainvoke(**invoke_kwargs)
                self._breaker.record_success(tenant_id)

                # Phase G: 捕获 token 使用统计
                usage = None
                if hasattr(result, "usage") and result.usage:
                    u = result.usage
                    usage = {
                        "prompt_tokens": getattr(u, "prompt_tokens", 0),
                        "completion_tokens": getattr(u, "completion_tokens", 0),
                        "total_tokens": getattr(u, "total_tokens", 0),
                    }

                return LLMResult(
                    result=result,
                    provider=provider.name,
                    fallback_used=(i > 0),
                    error=None,
                    usage=usage,
                )
            except Exception as e:
                errors.append(f"{provider.name}: {e}")
                if i == 0:
                    self._breaker.record_failure(tenant_id)
                continue

        # 全部失败
        raise LLMError(
            f"All providers failed. Errors: {'; '.join(errors)}",
            errors=errors,
        )

    async def astream(self, messages: list, tenant_id: str = "default"):
        """
        流式调用 — 按 provider 链依次尝试，yield 每个 token chunk。

        Bug #2 Fix — 防止 fallback 导致重复 token：
        - 第一 provider（i==0）：先将所有 chunk 缓冲，完成后统一 yield；中途失败则 abort（不 fallback）
        - Fallback provider（i>0）：只有在第一 provider 未开始 yielded 时才尝试，避免重复 token

        Args:
            tenant_id: 租户标识，用于 per-tenant 熔断隔离（Bug #1 Fix）

        Yields:
            LLMResult(result=AIMessage chunk, provider, fallback_used, error=None, usage=None)

        注意：usage 只在流结束时才有意义，流式 chunk 不含完整的 usage。
        """
        errors: list[str] = []

        start_idx = 1 if self._breaker.should_skip_primary(tenant_id) else 0
        if start_idx > 0:
            errors.append(f"primary: circuit_breaker_open (skipped, tenant={tenant_id})")

        for i, provider in enumerate(self.config.providers):
            if i < start_idx:
                continue

            model = self._get_model(provider)
            callable_model = self._bound_models.get(provider.name, model)

            try:
                if i == 0:
                    # Bug #2 Fix: 第一 provider 缓冲全部 chunk，失败则 abort（不 fallback）
                    # 避免 Provider A 吐部分 token 后失败、Provider B 从头重试导致重复
                    chunks: list = []
                    async for chunk in callable_model.astream(messages):
                        chunks.append(chunk)
                    for chunk in chunks:
                        yield LLMResult(
                            result=chunk,
                            provider=provider.name,
                            fallback_used=False,
                            error=None,
                            usage=None,
                        )
                    self._breaker.record_success(tenant_id)
                    return
                else:
                    # Fallback provider（只有第一 provider 未吐出任何 token 时才到达此处）
                    async for chunk in callable_model.astream(messages):
                        yield LLMResult(
                            result=chunk,
                            provider=provider.name,
                            fallback_used=True,
                            error=None,
                            usage=None,
                        )
                    self._breaker.record_success(tenant_id)
                    return
            except Exception as e:
                errors.append(f"{provider.name}: {e}")
                if i == 0:
                    self._breaker.record_failure(tenant_id)
                continue

        raise LLMError(
            f"All providers failed. Errors: {'; '.join(errors)}",
            errors=errors,
        )

    async def ainvoke_compat(self, messages: list) -> LLMResult:
        """
        兼容同步调用场景的异步入口。

        在 async 上下文（FastAPI）中直接 await ainvoke；
        在 sync 上下文中通过 asyncio.run 调用此方法。
        """
        return await self.ainvoke(messages)

    def invoke(self, messages: list) -> LLMResult:
        """
        同步包装器，兼容同步调用场景。
        """
        import asyncio

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is not None:
            raise RuntimeError(
                "LLMEngine.invoke() cannot be called from an async context — use await engine.ainvoke(messages) instead"
            )
        return asyncio.run(self.ainvoke(messages))


# ── 全局单例（进程级，多处共享同一 CircuitBreaker 状态）───────────────

_global_engine: LLMEngine | None = None


def get_global_engine() -> LLMEngine:
    """
    获取或创建全局 LLMEngine 单例（进程级）。

    供 client.py 和 context_compressor.py 共用，确保 CircuitBreaker 状态
    在所有调用方之间共享，避免一个模块熔断后另一个仍用已故障的 provider。
    """
    global _global_engine
    if _global_engine is None:
        _global_engine = LLMEngine(LLMEngineConfig.from_env())
    return _global_engine
