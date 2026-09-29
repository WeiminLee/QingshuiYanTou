"""
Agent 分析 API — DEPRECATED (dsh cutover, archived LangChain)

LangChain / Vue chat UX is retired. Package moved to archive/langchain_agent/.
Use dsh web / headless + plugins/qingshui. Knowledge HTTP under
/api/v1/knowledge/* is unaffected.

All historical /api/v1/agent/* surfaces return 410 Gone.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.utils.auth import verify_api_key

router = APIRouter(tags=["Agent分析"])

_AGENT_GONE = {
    "error": "langchain_agent_retired",
    "message": (
        "Vue/LangChain agent UX is deprecated. "
        "Use dsh (web or headless) with plugins/qingshui for 投研对话."
    ),
    "entry": "pnpm dsh --profile web  # or: pnpm dsh --profile headless \"…\"",
    "docs": "docs/superpowers/specs/2026-09-29-dsh-agent-runtime-cutover-design.md",
    "archive": "archive/langchain_agent/",
}


def _langchain_agent_retired() -> None:
    """FastAPI dependency: hard-stop default LangChain agent UX (cutover)."""
    raise HTTPException(status_code=410, detail=_AGENT_GONE)


class _GoneBody(BaseModel):
    """Minimal body so OpenAPI still accepts historical JSON shapes."""

    question: str | None = Field(None, description="ignored")
    user_id: str | None = None


# ── Historical surfaces → 410 ──────────────────────────────────────────────


@router.post("/chat")
async def chat(
    _body: _GoneBody | None = None,
    _auth=Depends(verify_api_key),
    _retired=Depends(_langchain_agent_retired),
) -> None:
    return None


@router.post("/invoke")
async def invoke(
    _body: _GoneBody | None = None,
    _auth=Depends(verify_api_key),
    _retired=Depends(_langchain_agent_retired),
) -> None:
    return None


@router.get("/invoke/{task_id}/result")
async def get_result(
    task_id: str,
    _auth=Depends(verify_api_key),
    _retired=Depends(_langchain_agent_retired),
) -> None:
    return None


@router.get("/invoke")
async def list_tasks(
    _auth=Depends(verify_api_key),
    _retired=Depends(_langchain_agent_retired),
) -> None:
    return None


@router.post("/feedback")
async def submit_agent_feedback(
    _body: _GoneBody | None = None,
    _auth=Depends(verify_api_key),
    _retired=Depends(_langchain_agent_retired),
) -> None:
    return None


@router.post("/report")
async def generate_report(
    _body: _GoneBody | None = None,
    _auth=Depends(verify_api_key),
    _retired=Depends(_langchain_agent_retired),
) -> None:
    return None


@router.get("/stream/{task_id}")
async def stream_events(
    task_id: str,
    _auth=Depends(verify_api_key),
    _retired=Depends(_langchain_agent_retired),
) -> None:
    return None


@router.post("/stream/report")
async def stream_report(
    _body: _GoneBody | None = None,
    _auth=Depends(verify_api_key),
    _retired=Depends(_langchain_agent_retired),
) -> None:
    return None


@router.post("/resolve/{task_id}")
async def resolve_clarification(
    task_id: str,
    _body: _GoneBody | None = None,
    _auth=Depends(verify_api_key),
    _retired=Depends(_langchain_agent_retired),
) -> None:
    return None


@router.post("/v2/chat")
async def v2_chat(
    _body: _GoneBody | None = None,
    _auth=Depends(verify_api_key),
    _retired=Depends(_langchain_agent_retired),
) -> None:
    return None


@router.post("/v2/stream")
async def v2_stream(
    _body: _GoneBody | None = None,
    _auth=Depends(verify_api_key),
    _retired=Depends(_langchain_agent_retired),
) -> None:
    return None
