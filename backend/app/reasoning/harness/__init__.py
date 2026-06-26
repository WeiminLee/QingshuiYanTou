"""
Harness — 执行控制层（V2 精简版）

保留：
  - BudgetEnforcer：三层预算防御（V2 引用）
  - MemoryManager：防抖队列 + LLM 摘要（V2 引用）

已删除（V1 死代码）：
  - AgentLoop, AgentLoopConfig, AgentResult（harness/loop.py）
  - DelegateAgentLoop, DelegateConfig（harness/delegate.py）
  - ContextEngine, DefaultContextEngine（harness/context_engine.py）
  - MiddlewareChain（harness/middleware_chain.py）

参考：
  - Hermes-Agent: environments/agent_loop.py（Budget + Loop）
  - DeerFlow: agents/middlewares/
"""

from app.reasoning.harness.budget import (
    BudgetConfig,
    BudgetEnforcer,
    ToolResultBudget,
    TurnBudget,
)
from app.reasoning.harness.memory import (
    DEFAULT_DEBOUNCE_SECONDS,
    MemoryManager,
    MemoryUpdateQueue,
    MemoryUpdater,
    format_kg_anchors_for_prompt,
    get_kg_anchors,
    increment_kg_anchor,
)

__all__ = [
    # Budget
    "BudgetConfig",
    "BudgetEnforcer",
    "TurnBudget",
    "ToolResultBudget",
    # Memory
    "MemoryManager",
    "MemoryUpdater",
    "MemoryUpdateQueue",
    "DEFAULT_DEBOUNCE_SECONDS",
    "get_kg_anchors",
    "increment_kg_anchor",
    "format_kg_anchors_for_prompt",
]
