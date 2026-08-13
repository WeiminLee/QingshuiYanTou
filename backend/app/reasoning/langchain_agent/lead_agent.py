"""
Lead Agent — DeerFlow 风格 create_agent 工厂

使用 langchain.agents.create_agent() 构建 LangGraph StateGraph agent，
替代旧的 create_react_agent + AgentExecutor。

create_agent 返回 CompiledStateGraph，自动处理 ReAct 循环：
  model → tools → model → ... → END

中间件作为 graph node 注入（before_model / after_model / after_agent）。

工具执行增强：
- 超时控制（asyncio.wait_for）— 每个工具独立超时
- 重试机制（RetryStrategy）— 指数退避重试
- 并发限制（asyncio.Semaphore）— 全局并发上限
- 异常降级（catch-all fallback）— 工具失败不中断 agent
"""

import asyncio
import logging
from dataclasses import dataclass

from langchain.agents import create_agent
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, StructuredTool

from app.reasoning.langchain_agent.middlewares.context_compressor import ContextCompressorMiddleware
from app.reasoning.langchain_agent.middlewares.loop_detection import LoopDetectionMiddleware
from app.reasoning.langchain_agent.middlewares.reasoning_validation import (
    ReasoningValidationMiddleware,
)
from app.reasoning.langchain_agent.retry import NoRetry, RetryStrategy
from app.reasoning.langchain_agent.tool_executor import DEFAULT_TIMEOUT, NEVER_PARALLEL

logger = logging.getLogger(__name__)

# ── 全局并发限制 ──────────────────────────────────────────────────────
# ToolExecutor 使用 asyncio.Semaphore(max_concurrent=8) 控制并发。
# 这里在 lead_agent 级别也使用一个共享信号量，确保 LangGraph 的 ToolNode
# 内部并行调用不会超过上限。
_tool_semaphore = asyncio.Semaphore(8)
# NEVER_PARALLEL 工具专用锁：确保 present_chart / clarify / write_file
# 等工具与其他工具互斥执行，避免并发冲突。
_never_parallel_lock = asyncio.Lock()


def _harden_tool(
    tool: BaseTool,
    timeout: float | None = None,
    retry: RetryStrategy | None = None,
) -> BaseTool:
    """给工具包一层异常保护壳：超时 + 重试 + 异常降级 + 并发限制。

    空库/无外部服务（PostgreSQL/Neo4j/Qdrant/Tavily 未就绪）时，个别工具会抛出
    未捕获异常（如 find_events 连 PG 抛 OSError），冒泡到 LangGraph ToolNode 会
    终止整个 agent 流。包一层后，工具失败降级为一条结果消息，LLM 可继续推理。

    增强：
    - 超时控制：asyncio.wait_for(timeout) 防止工具卡死
    - 重试机制：RetryStrategy.execute() 指数退避重试
    - 并发限制：asyncio.Semaphore 控制全局并发数
    """
    _timeout = timeout if timeout is not None else DEFAULT_TIMEOUT
    _retry = retry or NoRetry()

    def _fallback(exc: Exception) -> str:
        return (
            f"[数据服务暂不可用] 工具 {tool.name} 本次未能返回数据"
            f"（{type(exc).__name__}: {exc}）。当前为空数据/无外部服务环境，"
            f"请基于已有信息继续分析，或在结论中说明该项数据缺失。"
        )

    async def _acall(**kwargs):
        try:
            async def _do_invoke() -> str:
                async with _tool_semaphore:
                    # NEVER_PARALLEL 工具：使用互斥锁确保不与其他工具并发
                    if tool.name in NEVER_PARALLEL:
                        async with _never_parallel_lock:
                            return await asyncio.wait_for(
                                tool.ainvoke(kwargs),
                                timeout=_timeout,
                            )
                    return await asyncio.wait_for(
                        tool.ainvoke(kwargs),
                        timeout=_timeout,
                    )
            return await _retry.execute(_do_invoke)
        except asyncio.TimeoutError:
            logger.warning("[LeadAgent] tool %s timed out after %ss, degraded", tool.name, _timeout)
            return _fallback(TimeoutError(f"tool {tool.name} timed out after {_timeout}s"))
        except Exception as e:  # noqa: BLE001 — 故意兜底，保证 agent 不因工具失败中断
            logger.warning("[LeadAgent] tool %s failed (async), degraded: %s", tool.name, e)
            return _fallback(e)

    def _call(**kwargs):
        try:
            return tool.invoke(kwargs)
        except Exception as e:  # noqa: BLE001
            logger.warning("[LeadAgent] tool %s failed (sync), degraded: %s", tool.name, e)
            return _fallback(e)

    return StructuredTool.from_function(
        func=_call,
        coroutine=_acall,
        name=tool.name,
        description=tool.description,
        args_schema=tool.args_schema,
    )


def _filter_langchain_tools(
    tools: list,
    tool_configs: dict | None = None,
) -> list:
    """Keep tools that LangChain can safely pass to ToolNode, with timeout/retry wrapping.

    Args:
        tools: 原始工具列表
        tool_configs: {tool_name: {"timeout": float, "retry": RetryStrategy}, ...}
    """
    configs = tool_configs or {}
    valid = []
    for item in tools:
        if isinstance(item, BaseTool):
            cfg = configs.get(item.name, {})
            timeout = cfg.get("timeout")
            retry = cfg.get("retry")
            valid.append(_harden_tool(item, timeout=timeout, retry=retry))
            continue
        if callable(item) and hasattr(item, "__name__"):
            valid.append(item)
            continue
        logger.warning(
            "[LeadAgent] skipping invalid tool object: %r (%s)",
            getattr(item, "name", item),
            type(item).__name__,
        )
    return valid


@dataclass
class LeadAgentConfig:
    """Lead Agent 配置（保持向后兼容，API 端点使用）"""

    model_name: str = "minimax2.5"
    subagent_enabled: bool = False
    max_concurrent_subagents: int = 3
    max_turns: int = 8
    pre_search_top_k: int = 10
    plan_mode: bool = False
    title_enabled: bool = True


def _build_middlewares(
    config: RunnableConfig,
    thread_id: str = "default",
    plan_mode: bool = False,
    model=None,
) -> list:
    """
    构建 middleware 链（DeerFlow _build_middlewares 风格）。

    顺序：
    1. ContextCompressorMiddleware — before_model: 上下文压缩
    2. LoopDetectionMiddleware — after_model: 循环检测
    3. ReasoningValidationMiddleware — after_model: 推理质量检测

    注意：
    - ClarificationMiddleware 不在此链中注册，澄清拦截在 client.py 外层预检中处理（提前退出）。
    - GraphContextMiddleware 已移除，图谱上下文在 client.py 预处理阶段异步查询并注入 system prompt，
      避免在 before_model 同步钩子中阻塞 LangGraph 事件循环。
    """
    middlewares = []

    # ContextCompressor — before_model 钩子
    # 传入 model 用于 LLM 增量总结（Phase 2+），无 model 时回退截断
    middlewares.append(ContextCompressorMiddleware(
        tenant_id=thread_id,
        llm=model,
    ))

    # LoopDetection — after_model 钩子
    middlewares.append(LoopDetectionMiddleware())

    # ReasoningValidation — after_model 钩子：推理质量检测
    middlewares.append(ReasoningValidationMiddleware(enabled=True))

    return middlewares


def make_lead_agent(
    model,
    tools: list,
    system_prompt: str = "",
    config: RunnableConfig | None = None,
    thread_id: str = "default",
    plan_mode: bool = False,
    tool_configs: dict | None = None,
):
    """
    创建 Lead Agent（DeerFlow 风格）。

    Args:
        model: ChatOpenAI 实例（或 LLMEngine 包装的模型）
        tools: 工具列表
        system_prompt: 系统提示词
        config: RunnableConfig（传递给 middleware）
        thread_id: 会话 ID（用于 per-thread 隔离）
        plan_mode: 是否启用 plan mode
        tool_configs: {tool_name: {"timeout": float, "retry": RetryStrategy}, ...}

    Returns:
        CompiledStateGraph — 可调用 .stream() / .ainvoke()
    """
    if config is None:
        config = RunnableConfig(
            configurable={"thread_id": thread_id},
            recursion_limit=200,
        )

    middlewares = _build_middlewares(
        config,
        thread_id=thread_id,
        plan_mode=plan_mode,
        model=model,
    )

    safe_tools = _filter_langchain_tools(tools, tool_configs=tool_configs)

    agent = create_agent(
        model=model,
        tools=safe_tools,
        middleware=middlewares,
        system_prompt=system_prompt,
    )

    logger.info(
        f"[LeadAgent] created: model={getattr(model, 'model_name', model)}, "
        f"tools={len(safe_tools)}, middlewares={len(middlewares)}, "
        f"tool_configs={len(tool_configs) if tool_configs else 0}"
    )
    return agent
