"""
SubAgent 状态轮询 API
"""
import asyncio
import logging

from fastapi import APIRouter, Query

from app.reasoning.subagents.executor import get_executor
from app.reasoning.subagents.task_store import TaskStatus

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/subagent", tags=["SubAgent"])


@router.get("/status/{task_id}")
async def get_subagent_status(task_id: str) -> dict:
    """查询 SubAgent 任务状态"""
    executor = get_executor()
    status = executor.get_status(task_id)
    if status is None:
        return {"task_id": task_id, "status": "not_found"}
    return status


@router.get("/running")
async def list_running_subagents() -> dict:
    """列出所有运行中的 SubAgent 任务"""
    executor = get_executor()
    return {"running": executor.list_running()}


@router.post("/cancel/{task_id}")
async def cancel_subagent(task_id: str) -> dict:
    """取消 SubAgent 任务"""
    executor = get_executor()
    cancelled = executor.cancel(task_id)
    return {"task_id": task_id, "cancelled": cancelled}


@router.post("/submit")
async def submit_subagent(
    agent_name: str = Query(..., description="Agent 类型"),
    prompt: str = Query(..., description="分析指令"),
) -> dict:
    """提交 SubAgent 后台任务，返回 task_id"""
    executor = get_executor()
    task_id = executor.submit(agent_name, prompt)
    return {"task_id": task_id, "status": "pending"}
