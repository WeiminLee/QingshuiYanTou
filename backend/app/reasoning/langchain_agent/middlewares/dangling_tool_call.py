"""
DanglingToolCallMiddleware — 修复断开的工具调用消息

检测消息历史中 AI 工具调用但缺少对应 ToolMessage 的情况，
在 before_model 钩子中注入修复的 ToolMessage。

LangChain 的 ReAct 循环依赖 tool_calls 和 ToolMessage 的配对：
  AI (tool_calls=[...]) → ToolMessage → AI (response) → ...

如果 ToolMessage 缺失，LangChain 会报错：
  "AIMessage does not have tool call id ... ToolMessage must have ..."

作为 create_agent 的 before_model 钩子注入，在 LLM 调用前修复消息历史。
"""
from __future__ import annotations

import logging
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, ToolMessage

logger = logging.getLogger(__name__)


class DanglingToolCallMiddleware(AgentMiddleware):
    """
    修复消息历史中的断开工具调用。

    场景：
    - Agent 执行中途被中断（如超时、用户取消）
    - 部分 tool_calls 没有收到 ToolMessage 响应
    - 导致 LangChain ReAct 循环报错

    修复策略：
    - 在 before_model 钩子中检查最后一条 AIMessage 的 tool_calls
    - 如果有 tool_calls 但没有对应 ToolMessage，注入 error ToolMessage
    - 让 LLM 继续执行而不是报错
    """

    name: str = "dangling_tool_call"

    def before_model_hook(self, state: dict) -> dict | None:
        """
        before_model 钩子：检查并修复断开的工具调用。

        Returns:
            dict with "messages" key if fix applied, else None.
        """
        messages = state.get("messages", [])
        if not messages:
            return None

        # 找到 AIMessage（通常在消息列表末尾）和它之后是否有 ToolMessage
        dangling_tool_calls = self._find_dangling_tool_calls(messages)

        if not dangling_tool_calls:
            return None

        logger.warning(
            "[DanglingToolCall] 发现 %d 个断开工具调用: thread=%s",
            len(dangling_tool_calls),
            state.get("configurable", {}).get("thread_id", "default"),
        )

        # 构建修复的 ToolMessage
        fixed_messages: list[Any] = []
        for tc in dangling_tool_calls:
            tool_call_id = tc.get("id", "")
            tool_name = tc.get("name", "unknown")

            if not tool_call_id:
                tool_call_id = tc.get("name", "unknown") + "_auto"

            fixed_msg = ToolMessage(
                content=(
                    f"[执行中断] 工具 '{tool_name}' 执行中断，未收到响应。"
                    "系统已自动注入此消息以便继续执行。"
                ),
                tool_call_id=str(tool_call_id),
                name=str(tool_name),
            )
            fixed_messages.append(fixed_msg)

            logger.info(
                "[DanglingToolCall] 注入修复 ToolMessage: tool=%s id=%s",
                tool_name,
                tool_call_id,
            )

        # 返回更新后的消息列表
        return {"messages": list(messages) + fixed_messages}

    @staticmethod
    def _find_dangling_tool_calls(messages: list) -> list[dict]:
        """
        在消息列表中查找没有对应 ToolMessage 的 tool_calls。

        算法：
        1. 遍历消息，找到所有 AIMessage 的 tool_calls
        2. 收集所有已知的 tool_call_id
        3. 检查每个 tool_calls 是否有对应的 ToolMessage
        4. 返回缺少 ToolMessage 的 tool_calls
        """
        if not messages:
            return []

        # 已知的所有 tool_call_id（在 ToolMessage 中）
        known_tool_ids: set[str] = set()
        for msg in messages:
            if isinstance(msg, ToolMessage):
                tid = getattr(msg, "tool_call_id", "")
                if tid:
                    known_tool_ids.add(str(tid))

        # 检查最后一条 AIMessage 的 tool_calls
        last_ai = None
        for msg in reversed(messages):
            if isinstance(msg, AIMessage):
                last_ai = msg
                break
            # 如果遇到更早的 ToolMessage，说明最后一条 AIMessage 已有响应
            if isinstance(msg, ToolMessage):
                break

        if not last_ai:
            return []

        tool_calls = getattr(last_ai, "tool_calls", None)
        if not tool_calls:
            return []

        # 找出缺少 ToolMessage 的 tool_calls
        dangling: list[dict] = []
        for tc in tool_calls:
            tc_id = str(tc.get("id", ""))
            if tc_id and tc_id not in known_tool_ids:
                dangling.append(tc)

        return dangling