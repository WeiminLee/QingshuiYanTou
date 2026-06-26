"""
builtins/clarification — DeerFlow 风格显式澄清工具

参考 DeerFlow deerflow/tools/builtins/clarification_tool.py:

Agent 通过调用 ask_clarification 工具向用户提问以澄清：
- 缺失的必要信息（missing_info）
- 模糊的需求（ambiguous）
- 执行方案选择（approach_choice）
- 风险确认（risk_confirmation）

关键设计：
- return_direct=True：工具调用后直接返回，不继续 Agent 循环
- ClarificationMiddleware 拦截工具调用，格式化后发送给前端
- 前端显示澄清选项，用户回复后继续对话

TDesign SuggestionItem 格式要求：
- title: 显示给用户的选项文本（简短、清晰）
- prompt: 用户点击后发送给 AI 的内容（可选，默认使用 title）
"""

from __future__ import annotations

import logging
import uuid
from typing import Annotated, Literal

from langchain_core.tools import tool

logger = logging.getLogger(__name__)
_PENDING_CLARIFICATIONS: dict[str, dict] = {}

ClarificationType = Literal[
    "missing_info",  # 缺少必要信息
    "ambiguous",  # 需求模糊
    "approach_choice",  # 需要选择方案
    "risk_confirmation",  # 需要确认风险
]


def push_clarification(
    question: str,
    clarification_type: str,
    options: list | None = None,
    context: str | None = None,
) -> str:
    clarification_id = uuid.uuid4().hex
    _PENDING_CLARIFICATIONS[clarification_id] = {
        "id": clarification_id,
        "question": question,
        "clarification_type": clarification_type,
        "options": options,
        "context": context,
    }
    return clarification_id


def pop_clarification(clarification_id: str) -> dict | None:
    return _PENDING_CLARIFICATIONS.pop(clarification_id, None)


def has_pending_clarification() -> bool:
    return bool(_PENDING_CLARIFICATIONS)


def clear_clarifications() -> None:
    _PENDING_CLARIFICATIONS.clear()


@tool("ask_clarification", return_direct=True)
def ask_clarification(
    question: Annotated[str, "要向用户提问的澄清问题，清晰具体，不超过50字"],
    clarification_type: Annotated[
        ClarificationType,
        "澄清类型：missing_info（缺信息）/ ambiguous（模糊）/ approach_choice（选方案）/ risk_confirmation（确认风险）",
    ],
    options: Annotated[
        list[dict] | None,
        '选项列表，每个选项为 {"title": "显示文本", "prompt": "点击后发送内容"}。'
        "仅用于 approach_choice 类型，提供2-4个选项。title 不超过15字。",
    ] = None,
    context: Annotated[
        str | None,
        "补充上下文，说明为什么需要澄清（可选，不超过100字）",
    ] = None,
) -> str:
    """
    向用户提问以澄清需求或获取必要信息。

    调用此工具后，Agent 执行会暂停，等待用户回复。
    前端显示澄清问题，用户回答后 Agent 继续执行。

    【重要】选项格式要求：
    - 每个选项必须是 {"title": "显示文本", "prompt": "点击后发送内容"}
    - title: 简短清晰，不超过15字，用户看到的选项文字
    - prompt: 用户点击后发送给 AI 的完整内容（可选，默认使用 title）

    适用场景：
    - missing_info: 用户说"分析这家公司"但没有指明是哪家
    - ambiguous: 用户需求模糊，需要进一步明确
    - approach_choice: 多个可行方案，需要用户选择
    - risk_confirmation: 可能产生重大影响的操作，需要用户确认

    示例调用：
    {
        "question": "您希望用哪种方式呈现分析结果？",
        "clarification_type": "approach_choice",
        "options": [
            {"title": "详细研报", "prompt": "请生成详细的研究报告"},
            {"title": "摘要快报", "prompt": "请生成简要的分析摘要"},
            {"title": "对比分析", "prompt": "请进行对比分析"}
        ]
    }
    """
    # 格式化澄清消息（中间件会拦截并格式化，这里返回原始数据）
    options_str = ""
    if options and clarification_type == "approach_choice":
        options_str = "\\n".join([f"  {i + 1}. {opt.get('title', opt)}" for i, opt in enumerate(options[:4])])

    clarification_id = push_clarification(
        question=question,
        clarification_type=clarification_type,
        options=options,
        context=context,
    )
    result = f"**澄清请求** ({clarification_type})\\n\\n{question}"
    result += f"\\n\\nclarification_id: {clarification_id}"
    if context:
        result += f"\\n\\n**背景：** {context}"
    if options_str:
        result += f"\\n\\n**选项：**\\n{options_str}"

    logger.info(f"[ask_clarification] type={clarification_type}, question={question[:50]}")

    return result
