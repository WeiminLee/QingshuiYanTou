"""
Lead Agent — DeerFlow 风格 create_agent 工厂

使用 langchain.agents.create_agent() 构建 LangGraph StateGraph agent，
替代旧的 create_react_agent + AgentExecutor。

create_agent 返回 CompiledStateGraph，自动处理 ReAct 循环：
  model → tools → model → ... → END

中间件作为 graph node 注入（before_model / after_model / after_agent）。
"""

import logging
from dataclasses import dataclass

from langchain.agents import create_agent
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool

from app.reasoning.langchain_agent.middlewares.context_compressor import ContextCompressorMiddleware
from app.reasoning.langchain_agent.middlewares.loop_detection import LoopDetectionMiddleware
from app.reasoning.langchain_agent.middlewares.reasoning_validation import (
    ReasoningValidationMiddleware,
)

logger = logging.getLogger(__name__)


def _filter_langchain_tools(tools: list) -> list:
    """Keep tools that LangChain can safely pass to ToolNode."""
    valid = []
    for item in tools:
        if isinstance(item, BaseTool):
            valid.append(item)
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

    safe_tools = _filter_langchain_tools(tools)

    agent = create_agent(
        model=model,
        tools=safe_tools,
        middleware=middlewares,
        system_prompt=system_prompt,
    )

    logger.info(
        f"[LeadAgent] created: model={getattr(model, 'model_name', model)}, "
        f"tools={len(safe_tools)}, middlewares={len(middlewares)}"
    )
    return agent
