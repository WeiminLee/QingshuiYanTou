"""
Context Compressor Middleware — Phase 4: 结构感知注入

使用 tiktoken 精确计数，必要时调用 LLM 增量总结中间消息。
支持 3 级回退：primary LLM → fallback LLM → truncation（截断）。

压缩策略：
1. 修剪旧工具结果（替换为摘要占位符）
2. 保留头部消息（system prompt + 首轮交换）
3. Token 尾部保护（保留最近 tail_budget_pct 的预算）
4. 中间部分超阈值时，调用 LLM 增量总结（Phase 2）
5. 无 LLM 或 LLM 失败时回退截断（Phase 1 行为）
6. Anti-thrashing：节省率 < 10% 或上次压缩 < 30s 时跳过
7. 结构感知：保护带有结构标记的消息（历史记忆、背景知识等），
   并传递给 LLM 摘要保留关键上下文
"""

from __future__ import annotations

import logging
import time

from langchain.agents.middleware import AgentMiddleware, Runtime
from langchain_core.messages import BaseMessage, SystemMessage, ToolMessage

from app.reasoning.harness.token_counter import count_messages_tokens

logger = logging.getLogger(__name__)

# 结构标记：消息内容中包含这些标记时会被保护不被修剪
# 同时也传递给 LLM 摘要以保留关键上下文
_STRUCTURAL_MARKERS = frozenset({
    "[历史记忆]",
    "<memory>",
    "<memory-context>",
    "<background_context>",
    "<graph_context>",
    "<kg_anchors>",
    "[K线数据]",
})

_SUMMARY_PROMPT = """你是一个对话摘要助手。请对以下 Agent 的中间思考过程进行精简压缩，
保留关键决策、已获取的信息和当前待办事项。

要求：
1. 保留所有关键事实和数据
2. 保留工具调用意图和结果
3. 保留当前的待办和未完成事项
4. 保留用户已确认的约束、偏好和投资假设
5. 保留知识图谱锚点（反复提及的实体）
6. 格式简洁，使用结构化分段
7. 如之前已有摘要，请结合更新

以下为需要保留的已有上下文（历史记忆/背景知识/约束）：
{structural_context}

已有摘要：
{previous_summary}

本次新增的中间消息：
{new_messages}

请生成更新后的完整摘要（不是仅增量）："""


class SummaryMessage(BaseMessage):
    """压缩摘要消息，兼容 LangChain 序列化。

    type="summary" 供前端按类型过滤隐藏。
    """

    type: str = "summary"

    @property
    def content_string(self) -> str:
        if isinstance(self.content, str):
            return self.content
        return ""


class ContextCompressorMiddleware(AgentMiddleware):
    """上下文压缩中间件，在 before_model / abefore_model 钩子中压缩过长消息。"""

    name: str = "context_compressor"

    def __init__(
        self,
        token_threshold: int | None = None,
        protect_first_n: int | None = None,
        tail_budget_pct: float | None = None,
        tenant_id: str = "default",
        model_name: str | None = None,
        llm=None,
        fallback_llm=None,
        min_savings_ratio: float | None = None,
        min_interval_seconds: float | None = None,
    ):
        super().__init__()
        from app.config import settings

        self._token_threshold = token_threshold or settings.compression_token_threshold
        self._protect_first_n = protect_first_n or settings.compression_protect_first_n
        self._tail_budget_pct = tail_budget_pct if tail_budget_pct is not None else settings.compression_tail_budget_pct
        self._enabled = settings.compression_enabled
        self._tenant_id = tenant_id
        self._model_name = model_name
        self._llm = llm
        self._fallback_llm = fallback_llm
        self._min_savings_ratio = min_savings_ratio if min_savings_ratio is not None else 0.10
        self._min_interval_seconds = min_interval_seconds if min_interval_seconds is not None else 30.0

        # Anti-thrashing 状态追踪
        self._last_compression_time: float | None = None
        self._last_savings_pct: float | None = None

    def _should_skip_compression(self, estimated_tokens: int) -> str | None:
        """检查是否应跳过压缩。返回 None 或跳过原因。"""
        if not self._enabled:
            return "disabled"

        # Anti-thrashing：节省率过低时跳过
        if self._last_savings_pct is not None and self._last_savings_pct < self._min_savings_ratio * 100:
            return f"last savings ({self._last_savings_pct:.1f}%) below min ({self._min_savings_ratio*100:.0f}%)"

        # Anti-thrashing：上次压缩间隔过短
        if self._last_compression_time is not None:
            elapsed = time.time() - self._last_compression_time
            if elapsed < self._min_interval_seconds:
                return f"last compression {elapsed:.0f}s ago, min interval {self._min_interval_seconds:.0f}s"

        return None

    def _record_compression(self, before_tokens: int, after_tokens: int) -> None:
        """记录压缩效果用于 anti-thrashing。"""
        self._last_compression_time = time.time()
        self._last_savings_pct = (1 - after_tokens / max(before_tokens, 1)) * 100

    def before_model(self, state: dict, runtime: Runtime) -> dict | None:
        """同步钩子：无 LLM 时走截断回退。"""
        return self._compress_state(state)

    async def abefore_model(self, state: dict, runtime: Runtime) -> dict | None:
        """异步钩子：优先使用 LLM 增量总结。"""
        if self._llm is not None:
            return await self._acompress_state(state)
        return self._compress_state(state)

    def _compress_state(self, state: dict) -> dict | None:
        """同步压缩入口。"""
        messages = state.get("messages", [])
        if not messages:
            return None

        estimated_tokens = count_messages_tokens(messages, self._model_name)
        if estimated_tokens < self._token_threshold:
            return None

        skip_reason = self._should_skip_compression(estimated_tokens)
        if skip_reason:
            logger.debug("[ContextCompressor] skipped: %s", skip_reason)
            return None

        logger.info(
            "[ContextCompressor] compression triggered: tokens≈%d > %d",
            estimated_tokens,
            self._token_threshold,
        )

        compressed = self._compress(messages)
        if len(compressed) >= len(messages):
            return None

        compressed_tokens = count_messages_tokens(compressed, self._model_name)
        self._record_compression(estimated_tokens, compressed_tokens)
        logger.info(
            "[ContextCompressor] done: %d→%d msgs, tokens %d→%d (saved %d%%)",
            len(messages),
            len(compressed),
            estimated_tokens,
            compressed_tokens,
            self._last_savings_pct,
        )
        return {"messages": compressed}

    async def _acompress_state(self, state: dict) -> dict | None:
        """异步压缩入口（使用 LLM 总结）。"""
        messages = state.get("messages", [])
        if not messages:
            return None

        estimated_tokens = count_messages_tokens(messages, self._model_name)
        if estimated_tokens < self._token_threshold:
            return None

        skip_reason = self._should_skip_compression(estimated_tokens)
        if skip_reason:
            logger.debug("[ContextCompressor] async skipped: %s", skip_reason)
            return None

        logger.info(
            "[ContextCompressor] async compression triggered: tokens≈%d > %d",
            estimated_tokens,
            self._token_threshold,
        )

        compressed = await self._acompress(messages)
        if len(compressed) >= len(messages):
            return None

        compressed_tokens = count_messages_tokens(compressed, self._model_name)
        self._record_compression(estimated_tokens, compressed_tokens)
        logger.info(
            "[ContextCompressor] async done: %d→%d msgs, tokens %d→%d (saved %d%%)",
            len(messages),
            len(compressed),
            estimated_tokens,
            compressed_tokens,
            self._last_savings_pct,
        )
        return {"messages": compressed}

    def _compress(self, messages: list) -> list:
        """执行同步压缩：修剪 + 截断回退。"""
        original_count = len(messages)
        if original_count <= self._protect_first_n + 3:
            return list(messages)

        result = self._prune_tool_results(messages)

        if count_messages_tokens(result, self._model_name) < self._token_threshold:
            return result

        head, middle, tail = self._split(result)
        compressed_middle = self._summarize_section(middle)
        return list(head) + list(compressed_middle) + list(tail)

    async def _acompress(self, messages: list) -> list:
        """执行异步压缩：修剪 + LLM 增量总结。"""
        original_count = len(messages)
        if original_count <= self._protect_first_n + 3:
            return list(messages)

        result = self._prune_tool_results(messages)

        if count_messages_tokens(result, self._model_name) < self._token_threshold:
            return result

        head, middle, tail = self._split(result)
        compressed_middle = await self._asummarize_section(middle)
        return list(head) + list(compressed_middle) + list(tail)

    def _has_structural_marker(self, content: str) -> bool:
        """检查消息内容是否包含结构标记，需要被保护。"""
        if not content:
            return False
        return any(marker in content for marker in _STRUCTURAL_MARKERS)

    def _extract_structural_context(self, messages: list) -> str:
        """从消息列表中提取需要保留的结构化上下文。"""
        parts = []
        for msg in messages:
            content = getattr(msg, "content", None) or ""
            if isinstance(content, str) and self._has_structural_marker(content):
                parts.append(f"[{getattr(msg, 'type', 'unknown')}]: {content[:800]}")
        return "\n---\n".join(parts)

    def _prune_tool_results(self, messages: list) -> list:
        """Step 1: 修剪中间部分的长工具结果。

        结构感知：带有结构标记的消息不受修剪。
        """
        result = list(messages)
        tail_count = min(3, len(result) - 1)
        prune_start = self._protect_first_n
        prune_end = len(result) - tail_count

        for i in range(prune_start, prune_end):
            msg = result[i]
            if isinstance(msg, ToolMessage):
                orig = getattr(msg, "content", None) or ""
                if not isinstance(orig, str) or len(orig) <= 100:
                    continue
                # 结构感知：带有标记的工具结果不受修剪
                if self._has_structural_marker(orig):
                    continue
                tool_name = getattr(msg, "name", "tool")
                result[i] = ToolMessage(
                    content=f"[{tool_name}] output pruned ({len(orig)} chars)",
                    tool_call_id=getattr(msg, "tool_call_id", ""),
                    name=tool_name,
                )
        return result

    def _split(self, messages: list) -> tuple[list, list, list]:
        """Step 2: 拆分为 head / middle / tail。"""
        tail_count = min(3, len(messages) - 1)
        return (
            messages[: self._protect_first_n],
            messages[self._protect_first_n : -tail_count],
            messages[-tail_count:],
        )

    def _compute_mid_budget(self, head: list, tail: list) -> int:
        """计算中间部分可用 token 预算。"""
        head_tokens = count_messages_tokens(head, self._model_name)
        tail_tokens = count_messages_tokens(tail, self._model_name)
        tail_budget = int(self._token_threshold * self._tail_budget_pct)
        used_budget = head_tokens + min(tail_tokens, tail_budget)
        return max(1, self._token_threshold - used_budget)

    def _summarize_section(self, middle: list) -> list:
        """同步：截断回退（Phase 1 行为）。

        结构感知：带有结构标记的消息从末尾保留，确保不被丢弃。
        """
        mid_tokens = count_messages_tokens(middle, self._model_name)
        mid_budget = self._compute_mid_budget([], [])
        if mid_tokens <= mid_budget:
            return middle

        # 分离结构消息和普通消息
        structural = [m for m in middle if self._has_structural_marker(getattr(m, "content", "") or "")]
        normal = [m for m in middle if m not in structural]

        if not normal:
            return middle

        keep = 1
        while keep <= len(normal):
            keep_tokens = count_messages_tokens(normal[-keep:], self._model_name)
            if keep_tokens > mid_budget:
                keep = max(keep - 1, 1)
                break
            keep += 1

        truncated = list(normal[-keep:]) + list(structural)
        truncated.insert(
            0,
            SummaryMessage(
                content=f"[上下文压缩] 已略过 {len(normal) - keep} 条中间消息"
            ),
        )
        return truncated

    async def _asummarize_section(self, middle: list) -> list:
        """异步：LLM 增量总结。

        优先使用 LLM 对中间消息做总结。如已有 SummaryMessage，
        将其作为已有摘要并只总结后续新增消息。LLM 调用失败时回退截断。

        结构感知：提取带结构标记的消息并传递给 LLM 摘要，
        确保关键上下文（历史记忆、背景知识、KG 锚点）被保留。
        """
        mid_tokens = count_messages_tokens(middle, self._model_name)
        mid_budget = self._compute_mid_budget([], [])

        if mid_tokens <= mid_budget:
            return middle

        # 增量：提取已有摘要 + 仅总结新增消息
        previous_summary = ""
        new_messages = middle
        if middle and isinstance(middle[0], SummaryMessage):
            previous_summary = middle[0].content_string
            new_messages = middle[1:]

        if not new_messages:
            return middle

        # 结构感知：提取结构化上下文
        structural_context = self._extract_structural_context(middle)

        try:
            summary_text = await self._call_summary_llm(
                previous_summary=previous_summary,
                new_messages_text=self._messages_to_text(new_messages),
                structural_context=structural_context,
            )
            return [SummaryMessage(content=summary_text)]
        except Exception as e:
            logger.warning("[ContextCompressor] LLM summary failed, falling back to truncation: %s", e)
            return self._summarize_section(middle)

    async def _call_summary_llm(
        self,
        previous_summary: str,
        new_messages_text: str,
        structural_context: str = "",
    ) -> str:
        """调用 LLM 生成摘要（3 级回退：primary → fallback → 异常）。

        Args:
            previous_summary: 上次摘要文本
            new_messages_text: 本次新增的中间消息文本
            structural_context: 需要保留的结构化上下文（历史记忆、KG 锚点等）
        """
        prompt = _SUMMARY_PROMPT.format(
            structural_context=structural_context or "无",
            previous_summary=previous_summary or "无",
            new_messages=new_messages_text,
        )
        messages = [SystemMessage(content=prompt)]

        errors: list[Exception] = []
        candidates = [("primary", self._llm)]
        if self._fallback_llm is not None:
            candidates.append(("fallback", self._fallback_llm))

        for label, llm in candidates:
            if llm is None:
                continue
            try:
                response = await llm.ainvoke(messages)
                return response.content if hasattr(response, "content") else str(response)
            except Exception as e:
                logger.warning("[ContextCompressor] %s LLM summary failed: %s", label, e)
                errors.append(e)

        if errors:
            raise RuntimeError(f"all LLM summary attempts failed ({len(errors)} errors)") from errors[-1]

    @staticmethod
    def _messages_to_text(messages: list) -> str:
        """将消息列表转为摘要用的文本表示。"""
        parts = []
        for msg in messages:
            role = getattr(msg, "type", "unknown")
            content = getattr(msg, "content", "") or ""
            if isinstance(content, str):
                parts.append(f"[{role}]: {content[:500]}")
            else:
                parts.append(f"[{role}]: {str(content)[:500]}")
        return "\n".join(parts)


# ── 向后兼容导出 ──────────────────────────────────────────────
# can_parallel / SAFE_TO_PARALLEL / NEVER_PARALLEL 已移至
# app.reasoning.langchain_agent.tool_executor.ToolExecutor。
# 以下定义保留供测试使用，后续将被移除。

SAFE_TO_PARALLEL = frozenset(
    {
        "get_kline",
        "get_concept_hot",
        "get_market_breadth",
        "neo4j_traverse",
        "tavily_search",
        "get_stock_profile",
        "get_irm",
        "get_research_report",
        "get_announcement",
        "present_chart",
    }
)

NEVER_PARALLEL = frozenset({"clarify", "present_chart", "write_file"})


def can_parallel(tool_calls: list[dict]) -> bool:
    """判断一组 tool_calls 是否可安全并发。

    Deprecated: 请使用 tool_executor.ToolExecutor._should_parallel。
    """
    if len(tool_calls) <= 1:
        return False

    names = [tc.get("name", "") for tc in tool_calls]
    if any(name in NEVER_PARALLEL for name in names):
        return False
    if any(name not in SAFE_TO_PARALLEL for name in names):
        return False

    path_keys = ("code", "ts_code", "symbol", "stock_code")
    for tc in tool_calls:
        args = tc.get("args") or {}
        tc["_stock_codes"] = [v for k, v in args.items() if k in path_keys]

    stock_codes = [tc.get("_stock_codes", []) for tc in tool_calls]
    for codes in zip(*stock_codes):
        non_none = [c for c in codes if c is not None]
        if len(non_none) >= 2 and len(non_none) != len(set(non_none)):
            return False

    return True
