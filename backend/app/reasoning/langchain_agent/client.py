"""
LangChain Agent Client — DeerFlow 风格实现

使用 create_agent() + agent.astream() 替代 AgentExecutor。
create_agent 返回 CompiledStateGraph，自动处理 ReAct 循环。

SSE 事件流对齐 LangGraph stream 协议：
- thinking_delta: LLM 文本增量
- tool_called: 工具调用事件
- tool_result: 工具结果事件（preview 模式）
- stream_end: 流结束（含完整报告数据）
- error: 异常事件
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import datetime

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from langgraph.errors import GraphRecursionError

from app.reasoning.langchain_agent.integrations import (
    HarnessConfig,
    HarnessManager,
    format_kg_anchors,
)
from app.reasoning.langchain_agent.lead_agent import make_lead_agent
from app.reasoning.langchain_agent.llm_engine import get_global_engine
from app.reasoning.langchain_agent.middlewares.clarification import ClarificationMiddleware
from app.reasoning.langchain_agent.prompts.lead_system_prompt import apply_prompt_template
from app.reasoning.langchain_agent.task_events import drain_all_task_events, reset_task_events_queue
from app.reasoning.langchain_agent.tool_executor import build_preview
from app.reasoning.langchain_agent.hitl_store import (
    PendingClarification,
    get_hitl_store,
    parse_clarification_result,
)
from app.reasoning.runtime.journal import (
    RunJournal,
    append_journal_event,
    get_current_journal,
    reset_current_journal,
    set_current_journal,
)
from app.reasoning.tools.tools import get_available_tools

logger = logging.getLogger(__name__)

# 工具列表按 subagent_enabled 分开缓存，避免先创建普通 agent 后 task 工具不生效。
_cached_tools: dict[bool, list] = {}


def _get_tools(subagent_enabled: bool = False) -> list:
    """获取工具列表"""
    global _cached_tools
    if subagent_enabled not in _cached_tools:
        tools = get_available_tools(subagent_enabled=subagent_enabled)
        _cached_tools[subagent_enabled] = tools
        logger.info(f"[Tools] Loaded {len(tools)} tools: {[t.name for t in tools]}")
    return _cached_tools[subagent_enabled]


def _create_chat_model(model_name: str) -> ChatOpenAI:
    """创建 ChatOpenAI 实例（使用 LLMEngine primary provider）"""
    engine = get_global_engine()
    model = engine._get_primary_model()
    if model is None:
        raise ValueError("No primary LLM provider configured — check LLM_BASE_URL/LLM_API_KEY settings")
    return model


# ── LangChainAgentClient（SSE 端点用）────────────────────────────────────


class LangChainAgentClient:
    """
    SSE 端点使用的包装类，提供 .run() 接口。

    使用 create_agent() + agent.stream() 自动驱动 ReAct 循环。
    """

    def __init__(
        self,
        thread_id: str | None = None,
        model_name: str = "minimax2.5",
        subagent_enabled: bool = False,
        max_concurrent_subagents: int = 3,
        max_turns: int = 8,
        pre_search_top_k: int | None = None,
        plan_mode: bool = False,
        title_enabled: bool = True,
    ):
        self.thread_id = thread_id or str(uuid.uuid4())
        self.model_name = model_name
        self.subagent_enabled = subagent_enabled
        self.max_concurrent_subagents = max_concurrent_subagents
        self.max_turns = max_turns
        self.pre_search_top_k = pre_search_top_k
        self.plan_mode = plan_mode
        self.title_enabled = title_enabled

    async def run(
        self,
        question: str,
        emit_fn=None,
        harness_config: HarnessConfig | None = None,
    ) -> dict:
        return await run_lead_agent(
            question=question,
            thread_id=self.thread_id,
            model_name=self.model_name,
            subagent_enabled=self.subagent_enabled,
            max_concurrent_subagents=self.max_concurrent_subagents,
            max_turns=self.max_turns,
            emit_fn=emit_fn,
            pre_search_top_k=self.pre_search_top_k,
            harness_config=harness_config,
            plan_mode=self.plan_mode,
            title_enabled=self.title_enabled,
        )


# ── 主执行入口 ─────────────────────────────────────────────────────────


async def run_lead_agent(
    question: str,
    thread_id: str | None = None,
    task_id: str | None = None,
    model_name: str = "minimax2.5",
    max_turns: int = 8,
    subagent_enabled: bool = False,
    max_concurrent_subagents: int = 3,
    emit_fn=None,
    pre_search_top_k: int | None = None,
    harness_config: HarnessConfig | None = None,
    plan_mode: bool = False,
    title_enabled: bool = True,
    prebuilt_messages: list[BaseMessage] | None = None,
    skip_preflight: bool = False,
) -> dict:
    """
    运行 Lead Agent（DeerFlow 风格）。

    流程：
    1. Qdrant pre-search → 背景知识注入
    2. ClarificationMiddleware → 澄清拦截（在 agent 内部处理）
    3. make_lead_agent() → create_agent 构建 StateGraph
    4. agent.stream() → 自动 ReAct 循环
    5. SSE 推送 thinking_delta / tool_called / tool_result / stream_end
    """
    if pre_search_top_k is None:
        from app.config import settings

        pre_search_top_k = getattr(settings, "pre_search_top_k", 10)

    thread_id = thread_id or str(uuid.uuid4())
    journal = RunJournal(thread_id=thread_id, question=question)
    journal_token = set_current_journal(journal)

    # ── MemoryManager ──
    from app.reasoning.langchain_agent.memory.manager import MemoryManager
    from app.reasoning.langchain_agent.memory.builtin_provider import BuiltinProvider

    memory_manager: MemoryManager | None = None
    try:
        provider = BuiltinProvider()
        provider.initialize(thread_id)
        memory_manager = MemoryManager()
        memory_manager.add_provider(provider)
    except Exception:
        logger.warning("[MemoryManager] Failed to initialize — running without memory")
        memory_manager = None

    # Phase A: 重置 task 事件队列
    reset_task_events_queue()

    if not skip_preflight:
        # 澄清拦截（前置检查，不在 agent 内部）
        clarification_middleware = ClarificationMiddleware()
        clarification_needed = clarification_middleware._needs_clarification(question)
        if emit_fn:
            await emit_fn("reasoning_start", {"question": question[:100]})
        append_journal_event("reasoning_start", {"question": question[:100]})

        if clarification_needed:
            if emit_fn:
                suggestions = clarification_middleware._build_suggestions(question)
                await emit_fn(
                    "clarification_request",
                    {
                        "type": "missing_info" if len(question.strip()) < 10 else "ambiguous_requirement",
                        "question": question,
                        "reason": "用户输入模糊或缺少关键信息",
                        "suggestions": suggestions,
                    },
                )
            logger.info(f"[Clarification] 拦截模糊问题: {question[:30]}")
            journal.finish()
            reset_current_journal(journal_token)
            return {
                "content": "",
                "turns": 0,
                "tool_calls": [],
                "tool_results": [],
                "thread_id": thread_id,
                "status": "clarification_requested",
            }

        # 并行执行：Qdrant pre-search + Neo4j 图谱上下文查询
        # 注意：图谱查询在 client.py 预处理阶段异步执行，不再阻塞 LangGraph 事件循环
        pre_search_task = asyncio.create_task(_pre_search(question, top_k=pre_search_top_k))
        graph_ctx_task = asyncio.create_task(_fetch_graph_context_async(question, total_timeout=4.0))

        # 等待 pre-search 完成
        try:
            background = await pre_search_task
        except Exception as e:
            logger.warning("pre-search failed, continuing without background context: %s", e)
            background = None

        # 等待图谱上下文（失败不影响整体）
        graph_context = ""
        try:
            graph_context = await graph_ctx_task
        except Exception as e:
            logger.warning("graph context query failed, continuing without it: %s", e)
    else:
        background = ""
        graph_context = ""

    # ── GAP-BE-06: 顶层 try-except ──
    try:
        background = background or ""

        tools = _get_tools(subagent_enabled=subagent_enabled)

        # ── Harness Manager ──
        harness: HarnessManager | None = None
        memory_context = ""
        kg_anchors_str = ""
        system_prompt = ""
        if not skip_preflight:
            if harness_config is not None:
                harness = HarnessManager(harness_config, thread_id)
                harness.begin_turn(0)

            # Memory Context 注入
            if memory_manager is not None:
                try:
                    memory_context = await memory_manager.prefetch_all(question)
                except Exception:
                    logger.warning("[Memory] prefetch_all failed, running without memory context")
                    memory_context = ""
            else:
                memory_context = ""

            # KG Anchors 注入
            if harness is not None and harness.config.kg_anchors_enabled:
                kg_anchors_str = format_kg_anchors(thread_id)

            # 背景知识注入 system prompt（不进入 user message，不输出到前端）
            system_prompt = apply_prompt_template(
                subagent_enabled=subagent_enabled,
                max_concurrent_subagents=max_concurrent_subagents,
                memory_content=memory_context,
                kg_anchors=kg_anchors_str,
                background_context=background or "",
                graph_context=graph_context or "",
            )

        # ── Memory tool injection ──
        if memory_manager is not None:
            from app.reasoning.langchain_agent.memory.tool import set_memory_manager, manage_memory

            set_memory_manager(memory_manager)
            tools = list(tools)
            if manage_memory not in tools:
                tools.append(manage_memory)

        # ── 创建 Agent（DeerFlow 风格）──────────────────────────────
        model = _create_chat_model(model_name)
        # LangGraph 每个 ReAct turn 实际占用 ≥3 个 graph step（before_model →
        # model → after_model → tools），再叠加 ContextCompressor 等 middleware
        # 节点，单 turn 步数可能达到 6-8。这里给出 12× 的安全裕度。
        config = RunnableConfig(
            configurable={
                "thread_id": thread_id,
                "model_name": model_name,
                "subagent_enabled": subagent_enabled,
                "max_concurrent_subagents": max_concurrent_subagents,
            },
            recursion_limit=max(50, max_turns * 12),
        )

        agent = make_lead_agent(
            model=model,
            tools=tools,
            system_prompt=system_prompt,
            config=config,
            thread_id=thread_id,
            plan_mode=plan_mode,
        )

        # ── 执行 Agent Stream ───────────────────────────────────────
        if prebuilt_messages is not None:
            state = {"messages": list(prebuilt_messages)}
        else:
            state = {"messages": [HumanMessage(content=question)]}

        is_clarified = False
        clarification_data: dict | None = None
        all_messages: list[BaseMessage] = []

        seen_msg_ids: set[str] = set()
        full_content: list[str] = []
        tool_calls_record: list[dict] = []
        tool_results_record: list[dict] = []
        turn_count = 0
        recursion_truncated = False
        _last_synced_asst = ""
        # 工具失败短路：连续 N 次失败 → 提前终止，避免 LLM 在死循环里反复重试。
        consecutive_tool_failures = 0
        MAX_CONSECUTIVE_TOOL_FAILURES = 4
        # Bug #4: 工具调用计时（tool_called 时记录 start_time，tool_result 时计算 duration_ms）
        tool_start_times: dict[str, float] = {}

        try:
            async for chunk in agent.astream(state, config=config, stream_mode="values"):
                messages = chunk.get("messages", [])
                turn_count += 1

                for msg in messages:
                    msg_id = getattr(msg, "id", None) or str(uuid.uuid4())[:8]
                    if msg_id in seen_msg_ids:
                        continue
                    seen_msg_ids.add(msg_id)
                    all_messages.append(msg)

                    if isinstance(msg, AIMessage):
                        if is_clarified:
                            continue
                        # Tool calls
                        if msg.tool_calls:
                            for tc in msg.tool_calls:
                                tc_id = tc.get("id") or str(uuid.uuid4())[:8]
                                tc_name = tc.get("name", "")
                                tc_args = tc.get("args", {}) or {}
                                tool_calls_record.append(
                                    {
                                        "id": tc_id,
                                        "name": tc_name,
                                        "args": tc_args,
                                    }
                                )
                                # Bug #4: 记录工具调用开始时间
                                tool_start_times[tc_id] = time.monotonic()
                                if emit_fn:
                                    await emit_fn(
                                        "tool_called",
                                        {
                                            "id": tc_id,
                                            "name": tc_name,
                                            "args": tc_args,
                                            "turn": turn_count,
                                        },
                                    )
                                append_journal_event("tool_called", {"id": tc_id, "name": tc_name})

                        # Text content
                        text = _extract_text(msg.content)
                        if text:
                            full_content.append(text)
                            if emit_fn:
                                await emit_fn(
                                    "thinking_delta",
                                    {
                                        "delta": text,
                                        "turn": turn_count,
                                    },
                                )
                            append_journal_event("thinking_delta", {"turn": turn_count, "chars": len(text)})
                            if harness is not None and harness.config.memory_enabled:
                                harness.update_memory([{"role": "assistant", "content": text}])

                    elif isinstance(msg, ToolMessage):
                        result_str = _extract_text(msg.content) or str(msg.content)
                        tool_name = getattr(msg, "name", "unknown")
                        # 优先用 tool_call_id 与上游 tool_called 事件对齐；缺失时回退到消息 id。
                        tool_call_id = getattr(msg, "tool_call_id", None) or msg_id

                        # ── Pause detection: clarification tools ──
                        parsed = parse_clarification_result(tool_name, result_str)
                        if parsed is not None:
                            clarification_data = parsed
                            is_clarified = True
                            store_key = task_id or thread_id
                            save_messages = list(all_messages)
                            # Remove the clarification ToolMessage itself from checkpoint
                            # so the LLM doesn't see its own request on resume
                            if isinstance(msg, ToolMessage) and save_messages and save_messages[-1] is msg:
                                save_messages.pop()
                            await get_hitl_store().save(store_key, PendingClarification(
                                task_id=store_key,
                                thread_id=thread_id,
                                clarification_id=parsed["clarification_id"],
                                question=parsed["question"],
                                clarification_type=parsed.get("type", "ambiguous"),
                                options=parsed.get("options"),
                                context=parsed.get("context"),
                                messages=save_messages,
                                run_config={
                                    "model_name": model_name,
                                    "max_turns": max_turns,
                                    "thread_id": thread_id,
                                    "plan_mode": plan_mode,
                                    "question": question,
                                },
                            ))
                            if emit_fn:
                                await emit_fn("clarification_request", {
                                    "clarification_id": parsed["clarification_id"],
                                    "question": parsed["question"],
                                    "type": parsed.get("type", "ambiguous"),
                                    "options": parsed.get("options"),
                                    "context": parsed.get("context"),
                                })
                            append_journal_event("clarification_request", {
                                "clarification_id": parsed["clarification_id"],
                            })
                            continue

                        # Budget enforcement
                        if harness is not None and harness.config.budget_enabled:
                            result_str = await harness.enforce_budget(tool_name, result_str)

                        # 工具失败检测：LangChain ToolMessage.status='error' 或结果文本含错误标志
                        is_failure = getattr(msg, "status", None) == "error" or _looks_like_tool_failure(result_str)
                        if is_failure:
                            consecutive_tool_failures += 1
                        else:
                            consecutive_tool_failures = 0

                        preview = build_preview(tool_name, result_str)
                        # Bug #4: 计算工具执行时长
                        tool_start = tool_start_times.pop(tool_call_id, None)
                        duration_ms = (time.monotonic() - tool_start) * 1000 if tool_start else 0.0
                        tool_results_record.append(
                            {
                                "id": tool_call_id,
                                "name": tool_name,
                                "result": preview,
                                "success": not is_failure,
                                "turn": turn_count,
                                "original_len": len(result_str),
                                "duration_ms": duration_ms,
                            }
                        )

                        if harness is not None and harness.config.memory_enabled:
                            harness.update_memory([{"role": "tool", "content": result_str}])

                        if emit_fn:
                            await emit_fn(
                                "tool_result",
                                {
                                    "id": tool_call_id,
                                    "name": tool_name,
                                    "result": preview,
                                    "preview": preview,
                                    "success": not is_failure,
                                    "turn": turn_count,
                                    "original_len": len(result_str),
                                    "duration_ms": duration_ms,
                                },
                            )
                        append_journal_event(
                            "tool_result",
                            {
                                "id": tool_call_id,
                                "name": tool_name,
                                "success": not is_failure,
                                "duration_ms": int(duration_ms),
                            },
                        )

                # Per-turn memory sync
                if memory_manager is not None:
                    asst_text = ""
                    for m in reversed(messages):
                        if isinstance(m, AIMessage):
                            t = _extract_text(m.content)
                            if t:
                                asst_text = t
                                break
                    if asst_text and asst_text != _last_synced_asst:
                        try:
                            await memory_manager.sync_all(question, asst_text)
                        except Exception:
                            logger.warning("[Memory] sync_all failed, skipping turn sync")
                        _last_synced_asst = asst_text

                if is_clarified:
                    break

                # Drain task events
                if emit_fn:
                    for event in drain_all_task_events():
                        await emit_fn(
                            event.type.value,
                            {
                                "task_id": event.task_id,
                                **event.data,
                            },
                        )
                        append_journal_event(event.type.value, {"task_id": event.task_id, **event.data})

                # 工具连续失败保护 — 提前 break 避免 LLM 反复无效重试
                if consecutive_tool_failures >= MAX_CONSECUTIVE_TOOL_FAILURES:
                    logger.warning(f"[Agent] 工具连续失败 {consecutive_tool_failures} 次，提前终止 ReAct 循环")
                    recursion_truncated = True
                    full_content.append(
                        f"\n\n> ⚠️ 检测到工具调用连续失败 {consecutive_tool_failures} 次（如外部 API 不可达），"
                        f"已提前终止本轮分析。请稍后再试或换一个角度提问。"
                    )
                    break

        except GraphRecursionError as e:
            # LangGraph 触达递归上限：保留已收集结果，给前端可读提示。
            logger.warning(f"[Agent] GraphRecursionError: {e}")
            recursion_truncated = True
            full_content.append(
                "\n\n> ⚠️ 推理深度达到上限（LangGraph recursion_limit），"
                "已基于现有信息给出阶段性结论。如需更深入分析，请换一个更具体的问题。"
            )

        # ── 发射 stream_end ────────────────────────────────────────
        if is_clarified:
            if harness is not None:
                harness.stop()
            return {
                "status": "paused",
                "clarification_id": clarification_data["clarification_id"],
                "content": "",
            }

        if not is_clarified and emit_fn:
            raw_analysis = "".join(full_content)
            report = _build_analysis_report(
                topic=question,
                raw_analysis=raw_analysis,
                turns=turn_count,
            )
            await emit_fn(
                "stream_end",
                {
                    "report_content": report.to_markdown(),
                    "report_json": report.to_dict(),
                    "report_id": report.report_id,
                    "compliance_passed": report.compliance_declared,
                    "turns": turn_count,
                    "content": raw_analysis,
                    "stop_reason": "max_tool_calls" if recursion_truncated else None,
                    "run_id": journal.run_id,
                },
            )
        append_journal_event("stream_end", {"turns": turn_count, "truncated": recursion_truncated})

        # ── Harness 收尾 ───────────────────────────────────────────
        if harness is not None:
            if harness.config.kg_anchors_enabled:
                harness.track_entities(question)
            harness.stop()

        if memory_manager is not None:
            try:
                await memory_manager.shutdown_all()
            except Exception:
                logger.warning("[Memory] shutdown_all failed")

        result = {
            "content": "".join(full_content),
            "reasoning": "".join(full_content),
            "turns": turn_count,
            "tool_calls": tool_calls_record,
            "tool_results": tool_results_record,
            "thread_id": thread_id,
            "truncated": recursion_truncated,
        }

        if harness is not None:
            summary = harness.get_summary()
            if summary:
                result["harness"] = summary

        journal.finish()
        result["run_id"] = journal.run_id
        result["journal"] = journal.to_dict()



        return result

    except Exception as e:
        logger.exception(f"[Agent] run_lead_agent failed: {e}")
        journal.fail(str(e))
        if emit_fn:
            await emit_fn("error", {"error": str(e)})
        raise
    finally:
        if get_current_journal() is journal:
            reset_current_journal(journal_token)


# ── 辅助函数 ──────────────────────────────────────────────────────────


def _extract_text(content: str | list | None) -> str:
    """从 AIMessage.content 中提取纯文本"""
    if not content:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        return "".join(parts)
    return str(content)


# 工具结果失败标志（中英文兼容）— 用于驱动连续失败短路逻辑
_TOOL_FAILURE_MARKERS = (
    "查询失败",
    "获取失败",
    "检索失败",
    "请求失败",
    "调用失败",
    "Error:",
    "error:",
    "Exception:",
    "Traceback",
    "404 Client Error",
    "500 Server Error",
    "Connection refused",
    "Connection error",
    "Timeout",
    "timed out",
    "Not Found",
)


def _looks_like_tool_failure(result_text: str) -> bool:
    """启发式判断 ToolMessage 文本是否表示失败。

    LangChain ToolMessage.status 在某些 provider 下不被填充，
    因此对常见失败文本做模式匹配兜底。
    """
    if not result_text:
        return True
    head = result_text[:300]
    return any(marker in head for marker in _TOOL_FAILURE_MARKERS)


def _build_analysis_report(
    topic: str,
    raw_analysis: str,
    turns: int,
    report_id: str | None = None,
) -> AnalysisReport:  # noqa: F821
    """构造 AnalysisReport（用于 stream_end 内嵌完整报告）"""
    from app.reasoning.output.report import AnalysisReport

    if not report_id:
        report_id = str(uuid.uuid4())[:8]

    report = AnalysisReport(
        report_id=report_id,
        topic=topic,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        raw_analysis=raw_analysis,
    )

    try:
        from app.reasoning.output.compliance import scan_content

        compliance = scan_content(raw_analysis)
        report.compliance_declared = compliance.passed
    except Exception as e:
        logger.warning(f"[Report] 合规扫描失败: {e}")
        report.compliance_declared = False

    return report


# ── 图谱上下文预查询 ──────────────────────────────────────────────────


_STOCK_PATTERN = __import__("re").compile(r"(\d{6})\.(SH|SZ|BJ)")
_PRODUCT_PATTERNS = [
    __import__("re").compile(kw)
    for kw in [
        "光模块",
        "光通信",
        "激光雷达",
        "CPO",
        "硅光",
        "光伏",
        "锂电",
        "储能",
        "功率半导体",
        "碳化硅",
        "AI芯片",
        "GPU",
        "HBM",
        "先进封装",
        "机器人",
        "减速器",
        "控制器",
        "传感器",
    ]
]


def _extract_entities(text: str) -> list[str]:
    """从文本中提取实体名称（股票代码 + 产品关键词）"""
    entities: list[str] = []
    for match in _STOCK_PATTERN.finditer(text):
        code, exchange = match.group(1), match.group(2)
        entities.append(f"{code}.{exchange}")
    for pattern in _PRODUCT_PATTERNS:
        for match in pattern.finditer(text):
            entities.append(match.group(0))
    seen, unique = set(), []
    for e in entities:
        if e not in seen:
            seen.add(e)
            unique.append(e)
    return unique


async def _fetch_graph_context_async(question: str, total_timeout: float = 4.0) -> str:
    """
    从 Neo4j 预查询图谱上下文（异步，不阻塞 LangGraph 事件循环）。

    在 client.py 预处理阶段与 _pre_search 并行执行，
    结果注入 system prompt 而非前端输出。
    """
    entities = _extract_entities(question)
    if not entities:
        return ""

    results: list[str] = []
    try:
        tasks = [_fetch_entity_context(e) for e in entities[:5]]
        completed = await asyncio.wait_for(
            asyncio.gather(*tasks, return_exceptions=True),
            timeout=total_timeout,
        )
        for r in completed:
            if isinstance(r, str) and r and "暂无记录" not in r:
                results.append(r[:500])
    except TimeoutError:
        logger.warning("[GraphContext] 批量查询总超时")

    if not results:
        return ""

    parts = ["[图谱上下文]"]
    for r in results:
        parts.append(r if len(r) <= 500 else r[:500] + "...")
    return "\n\n".join(parts)


async def _fetch_entity_context(entity: str) -> str:
    """查询单个实体的 1-hop 关系（带内部超时）。"""
    try:
        from app.reasoning.tools.knowledge.neo4j.neo4j import _atraverse_impl

        result = await asyncio.wait_for(
            _atraverse_impl(entity, hops=1, rel_type="", query_mode="auto", min_weight=0.0),
            timeout=2.0,
        )
        return result if result and "暂无记录" not in result else ""
    except TimeoutError:
        logger.warning(f"[GraphContext] 查询超时: {entity}")
        return ""
    except Exception as e:
        logger.warning(f"[GraphContext] 查询失败: {entity} — {e}")
        return ""


# ── Qdrant Pre-search ───────────────────────────────────────────────────


async def _pre_search(query: str, top_k: int = 10) -> str:
    """Qdrant 语义检索，背景知识注入 (Phase 06: Hybrid RAG)"""
    try:
        from app.knowledge.vector_ops import hybrid_vector_search

        # Phase 06: Use hybrid search across all 4 collections (D-03)
        results = await hybrid_vector_search(
            query=query,
            top_k_per_collection=5,
            global_top_k=top_k,
        )
        if not results:
            return ""

        context_parts = []
        for r in results:
            payload = r.payload or {}

            if "entity_name" in payload:
                label = payload.get("entity_name") or "entity"
                text = (payload.get("description") or "")[:300]
                source = payload.get("source") or payload.get("ts_code") or "unknown"
                if text:
                    context_parts.append(f"- [实体:{label}]: {text}...（来源：{source}）")
            elif "from_name" in payload:
                from_name = payload.get("from_name") or payload.get("from_entity") or ""
                to_name = payload.get("to_name") or payload.get("to_entity") or ""
                text = (payload.get("description") or "")[:300]
                source = payload.get("source") or payload.get("ts_code") or "unknown"
                if text:
                    context_parts.append(f"- [关系:{from_name}->{to_name}]: {text}...（来源：{source}）")
            elif "content" in payload:
                label = payload.get("heading") or "chunk"
                text = (payload.get("content") or "")[:300]
                source = payload.get("source") or payload.get("ts_code") or "unknown"
                if text:
                    context_parts.append(f"- [文档:{label}]: {text}...（来源：{source}）")
            elif "question" in payload or "answer" in payload:
                label = payload.get("question") or "qa"
                text = (payload.get("answer") or "")[:300]
                source = payload.get("source") or "unknown"
                if text:
                    context_parts.append(f"- [问答:{label}]: {text}...（来源：{source}）")
            else:
                text = str(payload)[:200]
                if text:
                    context_parts.append(f"- [其他]: {text}...（来源：unknown）")

        if context_parts:
            return "<background>\n## 相关背景知识\n" + "\n".join(context_parts) + "\n</background>"
    except Exception as e:
        logger.warning(f"[PreSearch] Hybrid search failed: {e}")
        # Fallback to empty string - don't block agent
    return ""



