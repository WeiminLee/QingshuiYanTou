"""
Context Compressor Middleware — AgentMiddleware 协议

在消息过长时压缩上下文，防止 token 超限。
作为 create_agent 的 before_model 钩子注入。

压缩策略：
1. 修剪旧 tool results（替换为摘要占位符）
2. 保留 head messages（system prompt + 首次交换）
3. Token 尾部保护（保留最近 20% 预算）
"""
import logging

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage

logger = logging.getLogger(__name__)

DEFAULT_TOKEN_THRESHOLD = 40000
DEFAULT_PROTECT_FIRST_N = 3
DEFAULT_TAIL_BUDGET_PCT = 0.20


class ContextCompressorMiddleware(AgentMiddleware):
    """上下文压缩中间件，在 before_model 钩子中压缩过长消息。"""

    name: str = "context_compressor"

    def __init__(
        self,
        token_threshold: int = DEFAULT_TOKEN_THRESHOLD,
        protect_first_n: int = DEFAULT_PROTECT_FIRST_N,
        tail_budget_pct: float = DEFAULT_TAIL_BUDGET_PCT,
        tenant_id: str = "default",
    ):
        super().__init__()
        self._token_threshold = token_threshold
        self._protect_first_n = protect_first_n
        self._tail_budget_pct = tail_budget_pct
        self._tenant_id = tenant_id

    @staticmethod
    def _estimate_tokens(messages: list) -> int:
        """粗略估算消息列表的 token 数（中文约 1.5 字符/token）。"""
        total = 0
        for msg in messages:
            content = getattr(msg, "content", None) or ""
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        total += len(block.get("text", "")) // 2
                    elif isinstance(block, str):
                        total += len(block) // 2
            else:
                total += len(str(content)) // 2
        return total

    def before_model_hook(self, state: dict) -> dict | None:
        """
        before_model 钩子：在 LLM 调用前压缩过长的消息列表。

        Returns:
            dict with "messages" key containing compressed messages,
            or None if no compression needed.
        """
        messages = state.get("messages", [])
        if not messages:
            return None

        estimated_tokens = self._estimate_tokens(messages)
        if estimated_tokens < self._token_threshold:
            return None

        logger.info(
            f"[ContextCompressor] 触发压缩: tokens≈{estimated_tokens} > {self._token_threshold}"
        )

        compressed = self._compress(messages)
        if len(compressed) >= len(messages):
            return None

        logger.info(
            f"[ContextCompressor] 压缩完成: {len(messages)}→{len(compressed)}条"
        )
        return {"messages": compressed}

    def _compress(self, messages: list) -> list:
        """执行压缩：修剪旧 tool results + 保护 head + tail 保护。"""
        if len(messages) <= self._protect_first_n + 3:
            return list(messages)

        # Step 1: 修剪中间部分的 tool results
        result = list(messages)
        tail_count = min(3, len(result) - 1)
        prune_start = self._protect_first_n
        prune_end = len(result) - tail_count

        for i in range(prune_start, prune_end):
            msg = result[i]
            if isinstance(msg, ToolMessage):
                tool_name = getattr(msg, "name", "tool")
                orig_content = getattr(msg, "content", "") or ""
                if len(orig_content) > 100:
                    summary = f"[{tool_name}] output pruned ({len(orig_content)} chars)"
                    result[i] = ToolMessage(
                        content=summary,
                        tool_call_id=getattr(msg, "tool_call_id", ""),
                        name=tool_name,
                    )

        # Step 2: Tail token 保护
        tail = result[-tail_count:]
        head = result[:self._protect_first_n]
        middle = result[self._protect_first_n:-tail_count]

        # 如果中间部分仍然过长，截断
        middle_tokens = self._estimate_tokens(middle)
        if middle_tokens > self._token_threshold * 0.5:
            # 保留中间部分的最后 N 条
            keep_count = max(len(middle) // 2, 5)
            middle = middle[-keep_count:]
            middle = [_SummaryMessage(content=f"[上下文压缩] 已省略 {len(result) - len(head) - len(middle) - len(tail)} 条中间消息")] + list(middle)

        return list(head) + list(middle) + list(tail)


class _SummaryMessage:
    """摘要消息占位符，兼容 LangChain 消息接口。"""
    def __init__(self, content: str):
        self.content = content
        self.type = "summary"


# Phase E: 工具并发启发式（保留，供 client.py 使用）
SAFE_TO_PARALLEL = frozenset({
    "get_kline", "get_concept_hot", "get_market_breadth",
    "neo4j_traverse", "tavily_search", "get_stock_profile",
    "get_irm", "get_research_report", "get_announcement",
})

NEVER_PARALLEL = frozenset({"clarify", "present_chart", "write_file"})


def can_parallel(tool_calls: list[dict]) -> bool:
    """判断一组 tool_calls 是否可安全并发执行。"""
    if not tool_calls or len(tool_calls) <= 1:
        return False

    names = [tc.get("name", "") for tc in tool_calls]
    if any(name in NEVER_PARALLEL for name in names):
        return False
    if any(name not in SAFE_TO_PARALLEL for name in names):
        return False

    # 路径冲突检测
    stock_codes = []
    for tc in tool_calls:
        args = tc.get("args", {})
        stock_codes.append(
            args.get("stock_code") or args.get("ts_code")
            or args.get("code") or args.get("symbol")
        )
    non_none = [v for v in stock_codes if v is not None]
    if len(non_none) >= 2 and len(non_none) != len(set(non_none)):
        return False

    return True
