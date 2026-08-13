"""
Clarification Middleware — AgentMiddleware 协议

当用户输入模糊或缺少关键信息时，拦截并请求澄清。
作为 create_agent 的 after_model 钩子注入。

收紧策略（Phase 2）：
- 问候语（你好/hello/hi）放行，不触发澄清
- 极短的非问候输入（< 5 字符）直接触发澄清
- 无股票标的 + 模糊动词组合触发澄清
- 保留原有模糊度评分逻辑
"""

import logging
import re

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, HumanMessage

logger = logging.getLogger(__name__)

# 问候语模式：放行，不触发澄清
GREETING_PATTERNS = [
    r"^你好$",
    r"^您好$",
    r"^hi$",
    r"^hello$",
    r"^早上好$",
    r"^下午好$",
    r"^晚上好$",
    r"^你好啊$",
    r"^你好呀$",
    r"^嗨$",
    r"^hey$",
    r"^hi\b",
    r"^hello\b",
]

# 模糊关键词检测（增强版）
# 注意：避免冗余模式导致双倍计分（如"怎么样"和"怎么样$"同时匹配）
AMBIGUITY_PATTERNS = [
    r"帮我看一下",
    r"怎么样$",       # 句尾的"怎么样"——"XXX怎么样"
    r"好不好$",       # 句尾的"好不好"
    r"^分析",         # 以"分析"开头
    r"^帮我分析",     # 以"帮我分析"开头
    r"^查一下",
    r"^查查",
    r"^评估",
    r"这个",
    r"那个",
    r"^推荐",
    r"^看看",
    r"有什么",
    r"^评价",
    r"^预测",
    r"^涨了",
    r"^跌了",
    r"^行情",
    r"^走势",
    r"^看法",
    r"^观点",
    r"^判断",
    r"^研究",
    r"^说一下",
    r"^讲讲",
]

# 缺少具体标的的信号
MISSING_TARGET_PATTERNS = [
    r"这只",
    r"那个",
    r"最近",
    r"现在",
    r"^这个\b",
    r"^那个\b",
    r"^那支",
    r"^这支",
    r"^这只",
    r"^那个",
    r"最近",
    r"现在",
    r"当前",
    r"目前",
]


class ClarificationMiddleware(AgentMiddleware):
    """当用户输入模糊时，拦截并请求澄清。"""

    name: str = "clarification"

    def __init__(self, clarification_threshold: float = 0.6):
        super().__init__()
        self._threshold = clarification_threshold

    @staticmethod
    def _is_greeting(text: str) -> bool:
        """判断是否为问候语（放行，不触发澄清）。"""
        t = text.strip().lower()
        for pattern in GREETING_PATTERNS:
            if re.search(pattern, t):
                return True
        return False

    @staticmethod
    def _has_stock_ref(text: str) -> bool:
        """判断文本是否包含明确标的（股票代码、英文名、中文公司名）。

        中文公司名启发式：去掉模糊词后仍有 >= 4 个连续汉字 → 大概率是公司名。
        """
        # 股票代码（6位数字）
        if re.search(r"\d{6}", text):
            return True
        # 英文/数字组合（如 GPU, AI, 300308）
        if re.search(r"[A-Za-z]{2,}", text):
            return True
        # 中文公司名：去掉模糊词后检查剩余汉字长度
        clean = re.sub(
            r"这个|那个|这只|那只|怎么样|好不好|分析一下|看看|查查|查一下|"
            r"帮我看一下|最近|现在|当前|目前|推荐一下|讲一下|"
            r"有什么|推荐|评价一下|评价|预测|看法|观点|"
            r"判断|研究|说一下|讲讲|走势|行情|涨了|跌了|"
            r"帮我看|帮我分析|帮我查|帮我看看|分析一下",
            "", text
        ).strip()
        cn_chars = re.findall(r"[一-鿿]+", clean)
        for word in cn_chars:
            if len(word) >= 4:
                return True
        return False

    @staticmethod
    def _needs_clarification(user_content: str) -> bool:
        """判断用户输入是否需要澄清。

        策略：
        1. 空输入 → 强制澄清
        2. 问候语 → 放行
        3. 极短非问候输入（< 5 字符）→ 强制澄清
        4. 无股票标的 + 模糊动词 → 按模糊度评分决定
        """
        text = user_content.strip() if user_content else ""
        if not text:
            return True

        # 问候语放行
        if ClarificationMiddleware._is_greeting(text):
            return False

        # 极短的非问候输入 → 直接澄清
        if len(text) < 5:
            return True

        ambiguity_score = 0.0
        for pattern in AMBIGUITY_PATTERNS:
            if re.search(pattern, text):
                ambiguity_score += 0.3

        # 没有具体股票代码/名称
        has_stock_ref = ClarificationMiddleware._has_stock_ref(text)
        if not has_stock_ref:
            for pattern in MISSING_TARGET_PATTERNS:
                if re.search(pattern, text):
                    ambiguity_score += 0.4
            # 无标的 + 有模糊词 = 需要澄清
            # 即使不匹配 MISSING_TARGET_PATTERNS（如"帮我看一下"），
            # 仅凭模糊词不足以说明意图，沉底加成确保触发澄清
            if ambiguity_score > 0 and ambiguity_score < 0.6:
                ambiguity_score += 0.3

        return ambiguity_score >= 0.6

    @staticmethod
    def _build_suggestions(user_content: str) -> list[str]:
        """根据用户输入生成澄清建议。"""
        suggestions = []

        text = user_content.strip() if user_content else ""

        if not text or len(text) < 5:
            suggestions.append("请提供具体的股票代码或名称")
            suggestions.append("请描述您想了解的方面（基本面、技术面、催化剂等）")
            return suggestions

        has_stock_ref = ClarificationMiddleware._has_stock_ref(text)
        if not has_stock_ref:
            suggestions.append("提供具体的股票代码（如 000001）或名称（如 平安银行）")

        if re.search(r"怎么样|好不好", text):
            suggestions.append("明确关注点：估值、行业对比、催化剂、风险等")

        if re.search(r"帮我看一下|^分析|^帮我分析|^查看|^看看", text):
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
