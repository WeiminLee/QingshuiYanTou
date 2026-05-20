"""
SubAgent 后台执行器

提供：
- SubagentExecutor：线程池后台执行 + 状态机
- TaskStore：纯内存任务存储
- 轮询 API：/api/v1/subagent/*
"""
from app.reasoning.subagents.config import SubAgentConfig
from app.reasoning.subagents.executor import SubagentExecutor, get_executor
from app.reasoning.subagents.task_store import TaskStore, TaskStatus, get_task_store

__all__ = [
    "SubAgentConfig",
    "SubagentExecutor",
    "get_executor",
    "TaskStore",
    "TaskStatus",
    "get_task_store",
]
