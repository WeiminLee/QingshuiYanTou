"""SubAgent task tool for bounded investment research delegation."""

from __future__ import annotations

import time
from typing import Annotated

from langchain_core.tools import tool

from app.reasoning.langchain_agent.task_events import (
    TaskEvent,
    TaskEventType,
    enqueue_task_event,
)
from app.reasoning.subagents.executor import get_executor
from app.reasoning.tools.guardrails import validate_research_only


def _poll_task(task_id: str, timeout_seconds: float = 120.0, interval: float = 0.5) -> dict:
    executor = get_executor()
    deadline = time.monotonic() + timeout_seconds
    last_status = None
    while time.monotonic() < deadline:
        status = executor.get_status(task_id)
        if not status:
            raise RuntimeError(f"SubAgent task not found: {task_id}")
        current_status = status.get("status")
        if current_status != last_status:
            enqueue_task_event(
                TaskEvent(
                    type=TaskEventType.TASK_RUNNING,
                    task_id=task_id,
                    data={"status": current_status, "agent_name": status.get("agent_name")},
                )
            )
            last_status = current_status
        if current_status in {"completed", "failed", "timed_out", "cancelled"}:
            return status
        time.sleep(interval)
    return {"task_id": task_id, "status": "timed_out", "error": "task tool polling timeout"}


@tool("task")
def task_tool(
    task: Annotated[str, "Bounded investment research task for a SubAgent."],
    agent_name: Annotated[str, "SubAgent role/name. Use research-focused roles only."] = "researcher",
    context: Annotated[str, "Optional supporting context for the research task."] = "",
) -> str:
    """
    Delegate a bounded investment research task to a SubAgent.

    This tool is intentionally research-only and only supports evidence
    gathering, comparison, risk review, catalyst tracking, and hypothesis checks.
    """
    validate_research_only(task, field="task")
    validate_research_only(context, field="context")
    validate_research_only(agent_name, field="agent_name")

    prompt = task if not context else f"{task}\n\n上下文：\n{context}"
    executor = get_executor()
    task_id = executor.submit(agent_name=agent_name, prompt=prompt)
    enqueue_task_event(
        TaskEvent(
            type=TaskEventType.TASK_STARTED,
            task_id=task_id,
            data={"agent_name": agent_name, "title": task[:80]},
        )
    )

    status = _poll_task(task_id)
    final_status = status.get("status")
    if final_status == "completed":
        enqueue_task_event(
            TaskEvent(
                type=TaskEventType.TASK_COMPLETED,
                task_id=task_id,
                data={"agent_name": agent_name},
            )
        )
        return str(status.get("result") or "")

    enqueue_task_event(
        TaskEvent(
            type=TaskEventType.TASK_FAILED,
            task_id=task_id,
            data={"agent_name": agent_name, "status": final_status, "error": status.get("error")},
        )
    )
    return f"SubAgent task {task_id} {final_status}: {status.get('error') or 'no result'}"
