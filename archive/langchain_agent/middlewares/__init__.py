"""
LangChain Agent Middlewares — DeerFlow 风格 AgentMiddleware

中间件作为 create_agent 的 middleware 参数注入，
通过 before_model / after_model / after_agent 钩子自动执行。

当前注册的中间件（由 lead_agent._build_middlewares 构建）：
1. ContextCompressorMiddleware — before_model: 上下文压缩
2. LoopDetectionMiddleware — after_model: 循环检测
3. ReasoningValidationMiddleware — after_model: 推理质量检测

已弃用/移出的中间件：
- ClarificationMiddleware — 已在 client.py 外层预检中处理，不再通过 agent 中间件链执行
- GraphContextMiddleware — 已在 client.py 预处理阶段异步执行，不再阻塞 LangGraph 事件循环
"""

from app.reasoning.langchain_agent.middlewares.clarification import (
    ClarificationMiddleware,
)
from app.reasoning.langchain_agent.middlewares.context_compressor import (
    ContextCompressorMiddleware,
)
from app.reasoning.langchain_agent.middlewares.loop_detection import (
    LoopDetectionMiddleware,
)
from app.reasoning.langchain_agent.middlewares.reasoning_validation import (
    ReasoningValidationMiddleware,
)
from app.reasoning.langchain_agent.middlewares.subagent_limit import (
    SubagentLimitMiddleware,
)
from app.reasoning.langchain_agent.middlewares.title import (
    TitleMiddleware,
)
from app.reasoning.langchain_agent.middlewares.todo_list import (
    TodoListMiddleware,
)

__all__ = [
    "ClarificationMiddleware",
    "ContextCompressorMiddleware",
    "LoopDetectionMiddleware",
    "ReasoningValidationMiddleware",
    "SubagentLimitMiddleware",
    "TitleMiddleware",
    "TodoListMiddleware",
]
