"""
Clarification Middleware — AgentMiddleware 协议

当用户输入模糊或缺少关键信息时，拦截并请求澄清。
作为 create_agent 的 after_model 钩子注入。
"""

import logging
import re

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, HumanMessage

logger = logging.getLogger(__name__)

# 模糊关键词检测
AMBIGUITY_PATTERNS = [
    r"帮我看一下",
    r"怎么样",
    r"好不好",
    r"分析一下$",
    r"看看$",
]

# 缺少具体标的的信号
MISSING_TARGET_PATTERNS = [
    r"这只",
    r"那个",
    r"最近",
    r"现在",
]


class ClarificationMiddleware(AgentMiddleware):
    """当用户输入模糊时，拦截并请求澄清。"""

    name: str = "clarification"

    def __init__(self, clarification_threshold: float = 0.6):
        super().__init__()
        self._threshold = clarification_threshold

    @staticmethod
    def _needs_clarification(user_content: str) -> bool:
        """判断用户输入是否需要澄清。"""
        if not user_content or len(user_content.strip()) < 5:
            return True

        ambiguity_score = 0.0
        for pattern in AMBIGUITY_PATTERNS:
            if re.search(pattern, user_content):
                ambiguity_score += 0.3

        # 没有具体股票代码/名称
        has_stock_ref = bool(re.search(r"\d{6}|[A-Za-z]{2,4}", user_content))
        if not has_stock_ref:
            for pattern in MISSING_TARGET_PATTERNS:
                if re.search(pattern, user_content):
                    ambiguity_score += 0.4

        return ambiguity_score >= 0.6

    @staticmethod
    def _build_suggestions(user_content: str) -> list[str]:
        """根据用户输入生成澄清建议。"""
        suggestions = []

        if not user_content or len(user_content.strip()) < 5:
            suggestions.append("请提供具体的股票代码或名称")
            suggestions.append("请描述您想了解的方面")
            return suggestions

        has_stock_ref = bool(re.search(r"\d{6}|[A-Za-z]{2,4}", user_content))
        if not has_stock_ref:
            suggestions.append("提供具体的股票代码（如 000001）或名称（如 平安银行）")

        if re.search(r"怎么样|好不好", user_content):
            suggestions.append("明确关注点：估值、行业对比、催化剂、风险等")

        if re.search(r"帮我看一下|分析一下$", user_content):
            suggestions.append("指定时间范围：近一周、近一个月等")
            suggestions.append("指定分析维度：基本面、技术面、资金面等")

        if not suggestions:
            suggestions.append("请补充更多细节以便精准分析")

        return suggestions

    def after_model_hook(self, state: dict, response: AIMessage) -> AIMessage:
        """
        after_model 钩子：检查用户消息是否模糊。

        如果需要澄清且 LLM 没有主动请求澄清，
        替换响应为澄清请求。
        """
        messages = state.get("messages", [])
        if not messages:
            return response

        # 找到最后一条 HumanMessage
        last_human = None
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage):
                last_human = msg.content
                break

        if not last_human or not self._needs_clarification(last_human):
            return response

        # LLM 已经在请求澄清（tool_calls 为空且有提问语气）
        content = getattr(response, "content", "") or ""
        if any(kw in content for kw in ["请问", "能否提供", "具体是", "请明确"]):
            return response

        # LLM 没有请求澄清，但用户输入模糊 → 注入澄清提示
        logger.info("[Clarification] 用户输入模糊，注入澄清请求")

        clarification_text = (
            "您的需求比较模糊，能否提供更具体的信息？例如：\n"
            "- 具体的股票代码或名称\n"
            "- 关注的时间范围\n"
            "- 想了解的方面（估值、行业对比、催化剂等）\n\n"
            f"您刚才说的是：{last_human}"
        )

        return AIMessage(
            content=clarification_text,
            tool_calls=[],
            id=getattr(response, "id", None),
        )
