"""
Agent 分析 API

清水 Layer 3 的 HTTP 接口（LangChain V2 引擎）：

POST /api/v1/agent/chat
  Body: {"question": "分析中际旭创的投资价值"}
  返回: {"content": "...", "thread_id": "...", "task_id": "..."}

POST /api/v1/agent/invoke
  Body: {"question": "..."}
  返回: {"task_id": "uuid", "thread_id": "uuid"}

GET /api/v1/agent/invoke/{task_id}/result
  返回: {"status": "done"/"running", "content": "..."}

POST /api/v1/agent/report
  Body: {"question": "..."}
  返回: {"report_json": {...}, "markdown": "...", ...}

POST /api/v1/agent/stream/report
  Body: {"question": "..."}
  返回: {"task_id": "uuid"}

GET /api/v1/agent/stream/{task_id}
  SSE 事件流
"""

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sse_starlette import EventSourceResponse

from app.reasoning.api.agent_events import ReasoningEvent, _task_manager, emit_error
from app.reasoning.langchain_agent.hitl_store import get_hitl_store
from app.utils.auth import verify_api_key, verify_api_key_query
from langchain_core.messages import BaseMessage, HumanMessage

_RESUME_TIMEOUT_SECONDS = 600  # 10 min — matching hermes-agent; closes SSE if user doesn't respond

router = APIRouter(tags=["Agent分析"])
logger = logging.getLogger(__name__)

# 任务清理节拍器：每创建 N 个任务触发一次过期任务清理（由 _task_manager._cleanup() 处理 TTL）
_cleanup_counter: int = 0
_CLEANUP_THRESHOLD: int = 10

# ── SSE 事件过滤（前端映射）────────────────────────────────────────

# Phase A 事件映射规则：
# - thinking_delta → thinking         （前端可见，LLM 思考过程）
# - ai_message     → thinking         （向后兼容旧路径）
# - tool_called    → tool_called     （Phase A 新事件，前端可见）
# - tool_call      → tool_called     （向后兼容旧路径）
# - tool_result    → tool_result     （Phase A 新事件，含 truncated 元信息，前端可见）
# - reasoning_end  → stream_end      （最终输出，前端可见）
# - reasoning_completed → stream_end （同上）
# - 其他事件       → 原样透传

_VISIBLE_MAP = {
    "thinking_delta": "thinking",  # DeerFlow 单消息流：统一 → thinking
    "ai_message": "thinking",  # 向后兼容
    "tool_called": "tool_called",  # Phase A: 新增
    "tool_call": "tool_called",  # 向后兼容
    "tool_result": "tool_result",  # Phase A: 新增（从过滤移入）
    "reasoning_start": "reasoning_start",
    "reasoning_started": "reasoning_start",
    "reasoning_end": "stream_end",
    "reasoning_completed": "stream_end",
}

_FILTERED: set[str] = set()  # Phase A: 不再过滤任何事件，全部透传给前端


def _filter_sse_event(event_type: str, data: dict) -> tuple[bool, str]:
    """
    Phase A: 判断 SSE 事件是否对前端可见，并做事件名映射。

    事件映射表（Phase A）：
    - thinking_delta → thinking     （前端可见，LLM 思考过程）
    - tool_called   → tool_called （前端可见，工具调用）
    - tool_result   → tool_result （前端可见，含 truncated 元信息）
    - stream_end    → stream_end （前端可见，结束）

    Returns:
        (is_visible, mapped_event_type)
    """
    if event_type in _FILTERED:
        return False, event_type
    if event_type in _VISIBLE_MAP:
        return True, _VISIBLE_MAP[event_type]
    return True, event_type


# ── 请求/响应模型 ──────────────────────────────────────


class ChatRequest(BaseModel):
    question: str
    thread_id: str | None = None
    max_turns: int = 5


class ChatResponse(BaseModel):
    content: str
    thread_id: str
    task_id: str
    reasoning: str | None = None  # Bug M3 修复：添加 reasoning 字段


class InvokeRequest(BaseModel):
    question: str
    thread_id: str | None = None
    max_turns: int = 5
    model_name: str = "minimax2.5"


class InvokeResponse(BaseModel):
    task_id: str
    thread_id: str
    status: str


class ResultResponse(BaseModel):
    task_id: str
    status: str
    content: str | None = None
    report_json: dict | None = None
    report_content: str | None = None
    report_id: str | None = None
    compliance_passed: bool | None = None
    reasoning: str | None = None  # Bug M3 修复：添加 reasoning 字段
    error: str | None = None
    thread_id: str | None = None


class ResolveClarificationRequest(BaseModel):
    answer: str
    clarification_id: str


async def _run_invoke_task(task_id: str, thread_id: str, question: str, max_turns: int, model_name: str):
    """后台执行分析（V2 引擎）"""
    _task_manager.create_task(task_id, thread_id, question)
    _task_manager.update_status(task_id, "running")
    try:
        from app.reasoning.langchain_agent.client import run_lead_agent

        result = await run_lead_agent(
            question=question,
            thread_id=thread_id,
            model_name=model_name,
            max_turns=max_turns,
        )
        _task_manager.update_status(task_id, "done")
        _task_manager.set_result(task_id, result)
        logger.info(f"[Agent] Task {task_id} completed")
    except Exception as e:
        logger.exception(f"[Agent] Task {task_id} failed: {e}")
        _task_manager.update_status(task_id, "failed")
        _task_manager.set_result(task_id, {"error": str(e)})


# ── API 端点 ──────────────────────────────────────


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, _=Depends(verify_api_key)):
    """
    直接返回分析结果（同步，V2 引擎）。

    LangGraph agent.stream() 内部自动驱动多轮 tool loop（Agent loop），
    真正实现 DeerFlow 式的反复调用工具直到完成。
    """
    from app.reasoning.langchain_agent.client import run_lead_agent

    thread_id = request.thread_id or str(uuid.uuid4())
    try:
        result = await run_lead_agent(
            question=request.question,
            thread_id=thread_id,
            max_turns=request.max_turns,
        )
        return ChatResponse(
            content=result.get("content", ""),
            reasoning=result.get("reasoning", ""),  # Bug M3 修复：传递 reasoning
            thread_id=thread_id,
            task_id="v2-" + str(uuid.uuid4())[:8],
        )
    except Exception as e:
        logger.exception(f"[Agent] chat failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/invoke", response_model=InvokeResponse)
async def invoke(
    request: InvokeRequest,
    background_tasks: BackgroundTasks,
    _=Depends(verify_api_key),
):
    """
    发起分析任务（后台执行，V2 引擎）。

    适合复杂问题，返回 task_id 供后续查询结果。
    """
    global _cleanup_counter

    task_id = str(uuid.uuid4())
    thread_id = request.thread_id or str(uuid.uuid4())

    # Bug #6 修复：统一使用 _task_manager，移除冗余的 _task_store 写入
    _task_manager.create_task(task_id, thread_id, request.question)

    _cleanup_counter += 1
    if _cleanup_counter >= _CLEANUP_THRESHOLD:
        _cleanup_counter = 0
        background_tasks.add_task(lambda: _task_manager._cleanup())

    background_tasks.add_task(
        _run_invoke_task,
        task_id,
        thread_id,
        request.question,
        request.max_turns,
        request.model_name,
    )

    return InvokeResponse(
        task_id=task_id,
        thread_id=thread_id,
        status="pending",
    )


@router.get("/invoke/{task_id}/result", response_model=ResultResponse)
async def get_result(task_id: str, _=Depends(verify_api_key)):
    """查询任务执行结果"""
    # 优先查 _task_manager（stream/report 使用）
    task = _task_manager.get_task(task_id)
    if task is not None:
        result = task.get("result", {})
        return ResultResponse(
            task_id=task_id,
            status=task["status"],
            content=result.get("content"),
            report_json=result.get("report_json"),
            report_content=result.get("report_content"),
            report_id=result.get("report_id"),
            compliance_passed=result.get("compliance_passed"),
            reasoning=result.get("reasoning", ""),  # Bug M3 修复：传递 reasoning
            error=task.get("error"),
            thread_id=task.get("thread_id"),
        )
    raise HTTPException(status_code=404, detail=f"Task {task_id} not found")


@router.get("/invoke")
async def list_tasks(limit: int = 20, _=Depends(verify_api_key)):
    """列出最近的任务"""
    safe_limit = max(1, min(int(limit or 20), 100))
    recent = _task_manager.list_recent_tasks(limit=safe_limit)
    items = []
    for t in recent:
        items.append(
            {
                "task_id": t.get("task_id", ""),
                "status": t.get("status", "unknown"),
                "thread_id": t.get("thread_id", ""),
                "created_at": t.get("created_at"),
                "completed_at": t.get("completed_at"),
            }
        )
    return {"items": items}


# ── Layer 4 报告端点 ──────────────────────────────────────


class ReportRequest(BaseModel):
    question: str
    thread_id: str | None = None
    max_turns: int = 4


class ReportResponse(BaseModel):
    report_json: dict
    markdown: str
    report_id: str
    thread_id: str
    compliance_passed: bool
    violations: list


@router.post("/report", response_model=ReportResponse)
async def generate_report(request: ReportRequest, _=Depends(verify_api_key)):
    """
    Layer 4 报告接口（V2 引擎）：生成完整的结构化分析报告。

    输出：
    - JSON：完整结构化报告（含置信度/催化剂/风险矩阵/跟踪指标）
    - Markdown：人类可读格式
    - 合规扫描结果
    """
    from app.reasoning.langchain_agent.client import run_lead_agent
    from app.reasoning.output import (
        AnalysisReport,
        log_report_audit,
        scan_content,
    )

    task_id = str(uuid.uuid4())
    thread_id = request.thread_id or str(uuid.uuid4())

    try:
        result = await run_lead_agent(
            question=request.question,
            thread_id=thread_id,
            max_turns=request.max_turns,
        )
        raw_analysis = result.get("content", "")

        report = AnalysisReport(
            report_id=task_id[:8],
            topic=request.question,
            generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            raw_analysis=raw_analysis,
        )

        # 合规扫描
        compliance = scan_content(raw_analysis)
        report.compliance_declared = compliance.passed
        markdown = report.to_markdown()

        # 审计日志
        log_report_audit(
            report_id=report.report_id,
            topic=request.question,
            ts_code="",
            result=markdown,
        )

        return ReportResponse(
            report_json=report.to_dict(),
            markdown=markdown,
            report_id=report.report_id,
            thread_id=thread_id,
            compliance_passed=compliance.passed,
            violations=[v["description"] for v in compliance.violations],
        )

    except Exception as e:
        logger.exception(f"[Agent] Report generation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── SSE 流式报告端点 ──────────────────────────────────────


@router.get("/stream/{task_id}")
async def stream_events(task_id: str, _api_key: str = Depends(verify_api_key_query)):
    """
    SSE 事件流端点。

    EventSource 不支持自定义 Header，因此通过 query 参数校验 API Key。
    """
    task_state = _task_manager.get_task(task_id)
    if task_state is None:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    from app.reasoning.api.agent_events import event_generator

    return EventSourceResponse(event_generator(task_id))


class StreamReportRequest(BaseModel):
    question: str
    thread_id: str | None = None
    max_turns: int = 4
    model_name: str = "minimax2.5"


@router.post("/stream/report")
async def stream_report(request: StreamReportRequest, _=Depends(verify_api_key)):
    """
    流式报告接口（V2 引擎）：后台执行分析，通过 SSE 推送推理进度。

    返回 task_id，前端连接 /stream/{task_id} 接收事件流，
    分析完成后在 SSE 中推送最终报告。
    """
    task_id = str(uuid.uuid4())
    thread_id = request.thread_id or str(uuid.uuid4())

    _task_manager.create_task(task_id, thread_id, request.question)
    asyncio.create_task(
        _run_stream_report(
            task_id,
            thread_id,
            request.question,
            request.max_turns,
            request.model_name,
        )
    )

    return {"task_id": task_id, "thread_id": thread_id}


@router.post("/resolve/{task_id}")
async def resolve_clarification(
    task_id: str,
    body: ResolveClarificationRequest,
    _=Depends(verify_api_key),
):
    """Resume a paused agent run with user's clarification answer."""
    store = get_hitl_store()
    pending = await store.pop(task_id)
    if not pending:
        raise HTTPException(404, "No pending clarification found for this task")

    await _task_manager.emit(
        task_id,
        ReasoningEvent(
            type="clarification_resolved",
            task_id=task_id,
            stage="clarification_resolved",
            data={"clarification_id": body.clarification_id, "task_id": task_id},
        ),
    )

    messages = list(pending.messages)
    messages.append(HumanMessage(content=body.answer))

    asyncio.create_task(_resume_stream_report(
        task_id=task_id,
        thread_id=pending.thread_id,
        messages=messages,
        run_config=pending.run_config,
    ))

    return {"status": "resumed", "task_id": task_id}


async def _run_stream_report(task_id: str, thread_id: str, question: str, max_turns: int, model_name: str):
    """后台执行报告生成（V2 引擎），并推送 SSE 事件"""
    from app.reasoning.api.agent_events import ReasoningEvent

    async def _emit_to_manager(ev_type: str, data: dict):
        """
        Phase A: 统一映射 client.py emit_fn 事件到 ReasoningEvent。
        使用全局 _VISIBLE_MAP 避免重复定义。

        事件映射（Phase A）：
        - thinking_delta  → thinking        （前端可见）
        - tool_called    → tool_called     （前端可见）
        - tool_result    → tool_result     （前端可见，含 truncated 元信息）
        - stream_end     → stream_end      （结束）
        - error          → error           （错误）
        - reasoning_start → reasoning_started
        - reasoning_end   → stream_end     （统一使用 _VISIBLE_MAP）
        """
        # 使用全局映射表，确保一致性
        mapped = ev_type if ev_type not in _VISIBLE_MAP else _VISIBLE_MAP[ev_type]
        turn = data.get("turn", 0) if isinstance(data, dict) else 0

        # DeerFlow 单消息流：thinking_delta 统一 → thinking
        # 前端用 <think>...</think> 标签自行分离（thinking 面板 vs 主内容区）
        if ev_type in ("thinking_delta", "ai_message"):
            delta = data.get("delta") or data.get("content", "")
            if delta:
                _task_manager.update_last_content(task_id, delta)
                await _task_manager.emit(
                    task_id,
                    ReasoningEvent(
                        type="thinking",
                        task_id=task_id,
                        stage="思考中",
                        data={"delta": delta, "turn": turn},
                        turn=turn,
                    ),
                )
        else:
            await _task_manager.emit(
                task_id,
                ReasoningEvent(
                    type=mapped,
                    task_id=task_id,
                    stage=data.get("stage", mapped),
                    data=data,
                    turn=turn,
                ),
            )

    async def emit_fn(ev_type: str, data: dict):
        """async 回调（client.py 里用 await emit_fn() 调用）"""
        await _emit_to_manager(ev_type, data)

    try:
        _task_manager.update_status(task_id, "running")
        await _task_manager.emit(
            task_id,
            ReasoningEvent(
                type="reasoning_started",
                task_id=task_id,
                stage="开始分析",
                data={"question": question, "max_turns": max_turns},
            ),
        )

        from app.reasoning.langchain_agent.client import run_lead_agent
        from app.reasoning.output import AnalysisReport, log_report_audit

        logger.info(f"[Agent] run_lead_agent 开始，task_id={task_id}, question={question[:30]}")
        try:
            logger.info(f"[Agent] pre_search 开始，task_id={task_id}")
            # 主 agent loop 不设外层超时；超时只发生在工具层（tool_executor 内置 per-tool timeout）。
            # 多轮研究/SubAgent 任务可能合理耗时数分钟，外层硬超时会误杀有效推理。
            result = await run_lead_agent(
                question=question,
                thread_id=thread_id,
                task_id=task_id,
                model_name=model_name,
                max_turns=max_turns,
                emit_fn=emit_fn,
            )
            if result and result.get("status") == "paused":
                _task_manager.mark_paused(task_id)
                asyncio.create_task(_schedule_resume_timeout(task_id))
                return
            logger.info(f"[Agent] run_lead_agent 完成，task_id={task_id}")
        except Exception as e:
            logger.exception(f"[Agent] run_lead_agent 异常，task_id={task_id}: {e}")
            await emit_error(task_id, str(e))
            _task_manager.update_status(task_id, "failed")
            return
        raw_analysis = result.get("content", "") if result else ""

        report = AnalysisReport(
            report_id=task_id[:8],
            topic=question,
            generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            raw_analysis=raw_analysis,
        )

        markdown = report.to_markdown()
        log_report_audit(
            report_id=report.report_id,
            topic=question,
            ts_code="",
            result=markdown,
        )

        _task_manager.set_result(
            task_id,
            {
                "content": raw_analysis,
                "report_json": report.to_dict(),
                "report_content": markdown,
                "report_id": report.report_id,
                "compliance_passed": report.compliance_declared,
            },
        )
        _task_manager.update_status(task_id, "done")
        # 注意：stream_end 已经由 run_lead_agent() 在 agent.stream() 循环中发射
        # 此处不再重复发射，避免前端收到重复的 stream_end 事件

    except Exception as e:
        logger.exception(f"[Agent] Stream report failed: {e}")
        await emit_error(task_id, str(e))
        _task_manager.update_status(task_id, "failed")


async def _resume_stream_report(
    task_id: str,
    thread_id: str,
    messages: list[BaseMessage],
    run_config: dict,
):
    """Resume a paused agent run from checkpoint — pushes events to same task_id stream."""
    from app.reasoning.api.agent_events import ReasoningEvent

    async def _emit_to_manager(ev_type: str, data: dict):
        mapped = ev_type if ev_type not in _VISIBLE_MAP else _VISIBLE_MAP[ev_type]
        turn = data.get("turn", 0) if isinstance(data, dict) else 0
        if ev_type in ("thinking_delta", "ai_message"):
            delta = data.get("delta") or data.get("content", "")
            if delta:
                _task_manager.update_last_content(task_id, delta)
                await _task_manager.emit(
                    task_id,
                    ReasoningEvent(
                        type="thinking",
                        task_id=task_id,
                        stage="思考中",
                        data={"delta": delta, "turn": turn},
                        turn=turn,
                    ),
                )
        else:
            await _task_manager.emit(
                task_id,
                ReasoningEvent(
                    type=mapped,
                    task_id=task_id,
                    stage=data.get("stage", mapped),
                    data=data,
                    turn=turn,
                ),
            )

    async def emit_fn(ev_type: str, data: dict):
        await _emit_to_manager(ev_type, data)

    try:
        _task_manager.update_status(task_id, "running")

        from app.reasoning.langchain_agent.client import run_lead_agent
        from app.reasoning.output import AnalysisReport

        result = await run_lead_agent(
            question="",
            thread_id=thread_id,
            task_id=task_id,
            model_name=run_config.get("model_name"),
            max_turns=run_config.get("max_turns", 8),
            emit_fn=emit_fn,
            prebuilt_messages=messages,
            skip_preflight=True,
            plan_mode=run_config.get("plan_mode", False),
        )

        raw_analysis = result.get("content", "") if result else ""
        report = AnalysisReport(
            report_id=task_id[:8],
            topic=run_config.get("question", "继续分析"),
            generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            raw_analysis=raw_analysis,
        )
        await emit_fn("stream_end", {
            "report_content": report.to_markdown(),
            "report_json": report.to_dict(),
            "report_id": report.report_id,
            "compliance_passed": report.compliance_declared,
            "turns": result.get("turns", 0),
            "content": raw_analysis,
        })
        _task_manager.update_status(task_id, "completed")

    except Exception as e:
        logger.exception(f"[Resume] resume agent exception: {e}")
        await emit_fn("error", {"error": str(e)})
        _task_manager.update_status(task_id, "failed")


async def _schedule_resume_timeout(task_id: str, timeout: int = _RESUME_TIMEOUT_SECONDS):
    """Emit timeout stream_end if user doesn't resume within the timeout window."""
    try:
        await asyncio.sleep(timeout)
        if _task_manager.is_paused(task_id):
            logger.info(f"[ResumeTimeout] Resume timeout for task {task_id}, cleaning up")
            store = get_hitl_store()
            await store.pop(task_id)
            await _task_manager.emit_timeout_end(task_id)
    except asyncio.CancelledError:
        pass


# ── V2 LangChain Agent 端点（显式 V2 前缀） ─────────────────────────────────


class V2ChatRequest(BaseModel):
    """V2 引擎聊天请求

    BUG-5 修复：添加输入字段验证，防止 DoS 和异常数据。
    """

    question: str = Field(..., min_length=1, max_length=5000, description="用户问题")
    thread_id: str | None = Field(default=None, max_length=100)
    max_turns: int = Field(default=8, ge=1, le=50)
    model_name: str = Field(default="minimax2.5", max_length=50)
    subagent_enabled: bool = Field(default=False)
    max_concurrent_subagents: int = Field(default=3, ge=1, le=10)


@router.post("/v2/chat", response_model=ChatResponse)
async def v2_chat(request: V2ChatRequest, _=Depends(verify_api_key)):
    """
    V2 LangChain Agent 聊天接口（显式 V2 前缀，与 /chat 等价）。

    BUG-2 修复：强制 API 认证，保护敏感的投研分析端点。

    支持：
    - Qdrant pre-search 背景知识注入
    - 完整中间件链（clarification / loop_detection / summarization / memory）
    - 工具：neo4j_traverse / get_kline / get_financial / tavily_search / present_chart
    """
    from app.reasoning.langchain_agent.client import run_lead_agent

    thread_id = request.thread_id or str(uuid.uuid4())

    try:
        result = await run_lead_agent(
            question=request.question,
            thread_id=thread_id,
            model_name=request.model_name,
            max_turns=request.max_turns,
            subagent_enabled=request.subagent_enabled,
            max_concurrent_subagents=request.max_concurrent_subagents,
        )
        return ChatResponse(
            content=result.get("content", ""),
            reasoning=result.get("reasoning", ""),  # Bug M3 修复：传递 reasoning
            thread_id=thread_id,
            task_id="v2-" + str(uuid.uuid4())[:8],
        )
    except Exception as e:
        logger.exception(f"[Agent V2] chat failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class V2StreamRequest(BaseModel):
    """V2 流式推理请求

    BUG-5 修复：添加输入字段验证，防止 DoS 和异常数据。
    """

    question: str = Field(..., min_length=1, max_length=5000, description="用户问题")
    thread_id: str | None = Field(default=None, max_length=100)
    max_turns: int = Field(default=8, ge=1, le=50)
    model_name: str = Field(default="minimax2.5", max_length=50)
    subagent_enabled: bool = Field(default=False)
    max_concurrent_subagents: int = Field(default=3, ge=1, le=10)


@router.post("/v2/stream")
async def v2_stream(request: V2StreamRequest, api_key: str = Depends(verify_api_key_query)):
    """
    V2 SSE 流式推理端点。

    BUG-2 修复：强制 API 认证（使用 query 参数，因为 SSE/POST 请求需要）。
    调用方式：POST /v2/stream?api_key=YOUR_API_KEY

    通过 SSE 推送推理进度事件：
    - reasoning_start: 推理开始
    - ai_message: AI 文本响应
    - tool_call: 工具调用
    - tool_result: 工具结果
    - reasoning_end: 推理结束
    """
    from app.reasoning.langchain_agent.client import LangChainAgentClient

    thread_id = request.thread_id or str(uuid.uuid4())

    async def event_generator():
        task_id = str(uuid.uuid4())
        _task_manager.create_task(task_id, thread_id, request.question)
        _task_manager.update_status(task_id, "running")

        client = LangChainAgentClient(
            thread_id=thread_id,
            model_name=request.model_name,
            subagent_enabled=request.subagent_enabled,
            max_concurrent_subagents=request.max_concurrent_subagents,
            max_turns=request.max_turns,
        )

        emitter_queue: asyncio.Queue = asyncio.Queue()

        async def emit(event_type: str, data: dict):
            await emitter_queue.put(json.dumps({"type": event_type, "data": data}, ensure_ascii=False))

        async def run_and_stream():
            try:
                result = await client.run(request.question, emit_fn=emit)
                _task_manager.set_result(task_id, result)
                _task_manager.update_status(task_id, "done")
            except Exception as e:
                logger.exception(f"[V2Stream] agent failed: {e}")
                _task_manager.update_status(task_id, "failed")

        stream_task = asyncio.create_task(run_and_stream())

        # SSE 总超时 — 主 loop 不设外层超时，仅工具层有超时
        from app.config import settings

        SSE_TOTAL_TIMEOUT = settings.agent_sse_timeout
        SSE_MAX_CONSECUTIVE_PINGS = 10
        ping_count = 0
        start_time = time.monotonic()

        while not stream_task.done() or not emitter_queue.empty():
            # 检查总超时
            elapsed = time.monotonic() - start_time
            if elapsed > SSE_TOTAL_TIMEOUT:
                logger.warning(f"[V2Stream] SSE stream timeout after {elapsed:.1f}s")
                _task_manager.update_status(task_id, "timeout")
                yield f"data: {json.dumps({'type': 'error', 'data': {'error': 'stream timeout'}})}\n\n"
                break

            try:
                raw = await asyncio.wait_for(emitter_queue.get(), timeout=30.0)
                ping_count = 0  # 收到数据，重置 ping 计数
                parsed = json.loads(raw)
                event_type = parsed.get("type", "")
                data = parsed.get("data", {})
                visible, mapped_type = _filter_sse_event(event_type, data)
                if visible:
                    yield f"data: {json.dumps({'type': mapped_type, 'data': data})}\n\n"
            except TimeoutError:
                ping_count += 1
                if ping_count > SSE_MAX_CONSECUTIVE_PINGS:
                    logger.warning(f"[V2Stream] Too many consecutive pings ({ping_count}), stream may be stuck")
                    _task_manager.update_status(task_id, "stuck")
                    yield f"data: {json.dumps({'type': 'error', 'data': {'error': 'stream stuck, too many pings'}})}\n\n"
                    break
                yield f"data: {json.dumps({'type': 'ping'})}\n\n"

        while not emitter_queue.empty():
            try:
                item = emitter_queue.get_nowait()
                yield f"data: {item}\n\n"
            except asyncio.QueueEmpty:
                break

        # client.run() owns stream_end emission. The API layer only forwards
        # pending queued events and surfaces terminal errors.
        if stream_task.done():
            try:
                exc = stream_task.exception()
                if exc:
                    yield f"data: {json.dumps({'type': 'error', 'data': {'error': str(exc)}})}\n\n"
            except asyncio.CancelledError:
                yield f"data: {json.dumps({'type': 'error', 'data': {'error': 'task cancelled'}})}\n\n"

    return EventSourceResponse(event_generator())


async def _periodic_hitl_cleanup():
    """Periodically clean up expired HITL checkpoints."""
    while True:
        await asyncio.sleep(300)  # 5 min
        try:
            from app.reasoning.langchain_agent.hitl_store import get_hitl_store
            store = get_hitl_store()
            count = await store.cleanup_expired()
            if count:
                logger.info(f"[HITL] Cleaned up {count} expired paused tasks")
        except Exception as e:
            logger.warning(f"[HITL] Cleanup error: {e}")
