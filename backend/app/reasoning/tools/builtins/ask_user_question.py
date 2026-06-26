"""
builtins/ask_user_question — 统一用户提问工具

符合 Claude Code 内置 AskUserQuestion 工具格式：
- questions: 问题列表（1-4个）
- 每个问题有: question, header, options, multiSelect

前端拦截此工具调用，展示选项卡片，等待用户选择后继续。
"""

from __future__ import annotations

import logging
from typing import Annotated, Literal

from langchain_core.tools import tool

logger = logging.getLogger(__name__)


class AskUserQuestion:
    """AskUserQuestion 工具的参数结构"""

    def __init__(
        self,
        questions: list[dict],  # 符合前端格式
    ):
        self.questions = questions


@tool("AskUserQuestion", return_direct=True)
def ask_user_question(
    questions: Annotated[
        list[dict],
        "问题列表，每个问题包含 question(问题文本), header(短标签), options(选项列表), multiSelect(是否多选)。",
    ],
) -> str:
    """
    向用户提问以澄清需求或获取必要信息。

    调用此工具后，Agent 执行会暂停，等待用户回复。
    前端显示选项卡片，用户选择后 Agent 继续执行。

    【重要】questions 格式：
    - questions: 数组，每个元素包含:
      - question: 问题文本（必填）
      - header: 短标签，如"认证方式"（最多12字符）
      - options: 选项列表，每个选项:
        - label: 显示文本（1-5字）
        - description: 选项说明
        - preview: 可选预览内容
      - multiSelect: 是否允许多选，默认 false

    示例调用：
    {
        "questions": [
            {
                "question": "您想分析哪只股票？",
                "header": "股票选择",
                "options": [
                    {"label": "中际旭创", "description": "光模块龙头"},
                    {"label": "宁德时代", "description": "锂电龙头"}
                ],
                "multiSelect": false
            }
        ]
    }
    """
    # 返回 JSON 字符串，前端解析并展示选项
    import json

    result = json.dumps({"questions": questions}, ensure_ascii=False)
    logger.info(f"[AskUserQuestion] 发起提问，问题数: {len(questions)}")
    return result


# 兼容旧的 ask_clarification（保留一段时间）
@tool("ask_clarification", return_direct=True)
def ask_clarification(
    question: Annotated[str, "要向用户提问的澄清问题"],
    clarification_type: Annotated[
        Literal["missing_info", "ambiguous", "approach_choice", "risk_confirmation"],
        "澄清类型",
    ] = "ambiguous",
    options: Annotated[
        list[dict] | None,
        "选项列表（仅 approach_choice 类型）",
    ] = None,
    context: Annotated[str | None, "补充上下文"] = None,
) -> str:
    """
    [已废弃] 请使用 AskUserQuestion 工具。
    此工具保留用于兼容。
    """
    # 将旧格式转换为新格式
    import json

    header_map = {
        "missing_info": "缺失信息",
        "ambiguous": "需求澄清",
        "approach_choice": "方案选择",
        "risk_confirmation": "风险确认",
    }

    options_list = []
    if options:
        for opt in options[:4]:
            if isinstance(opt, dict):
                options_list.append(
                    {
                        "label": opt.get("title", opt.get("label", "")),
                        "description": opt.get("prompt", opt.get("description", "")),
                    }
                )
            else:
                options_list.append({"label": str(opt), "description": ""})

    questions = [
        {
            "question": question,
            "header": header_map.get(clarification_type, "澄清"),
            "options": options_list,
            "multiSelect": False,
        }
    ]

    if context:
        questions[0]["question"] = f"{question}\n\n背景: {context}"

    logger.warning("[ask_clarification] 使用已废弃的工具，建议迁移到 AskUserQuestion")
    return json.dumps({"questions": questions}, ensure_ascii=False)
