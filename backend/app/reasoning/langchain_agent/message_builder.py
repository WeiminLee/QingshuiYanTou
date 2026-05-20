"""
MessageBuilder — 统一消息组装器

职责：
- 构建初始消息列表（System / Background / Memory / KG / User）
- 追加工具结果（ToolMessage）
- 确保消息顺序正确

消息顺序：
  1. SystemMessage（如果提供了 system_prompt）
  2. HumanMessage（Background Knowledge）
  3. HumanMessage（Memory Context）
  4. HumanMessage（User Message，永远最后）
  5. ToolMessage（追加，不改变顺序）
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Annotated

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, ToolMessage


@dataclass
class MessageContext:
    """
    消息构建的上下文数据。

    Attributes:
        thread_id: 会话线程 ID（用于追踪）
        user_message: 用户输入（永远放在最后）
        memory_context: 历史记忆（来自 MongoDB）
        kg_anchors: 知识图谱锚点（格式化文本）
        background_knowledge: 背景知识（Qdrant 检索结果）
        system_vars: 可注入模板变量（如当前日期等）
    """

    thread_id: Annotated[str, "会话线程 ID"]
    user_message: Annotated[str, "用户输入"]
    memory_context: Annotated[str, "历史记忆"] = ""
    kg_anchors: Annotated[str, "KG 锚点"] = ""
    background_knowledge: Annotated[str, "背景知识"] = ""
    system_vars: Annotated[dict, "模板变量"] = field(default_factory=dict)

    @property
    def has_any_context(self) -> bool:
        return bool(self.memory_context or self.kg_anchors or self.background_knowledge)


@dataclass
class MessageBuilder:
    """
    统一消息组装器。

    构建顺序：
      1. SystemMessage（包含 KG Anchors，如果提供）
      2. HumanMessage（Background Knowledge）
      3. HumanMessage（Memory Context）
      4. HumanMessage（User Message，永远最后）

    工具结果通过 append_tool_result() 追加到列表末尾。
    """

    system_prompt_template: str = ""

    def build_initial_messages(
        self,
        ctx: MessageContext,
    ) -> list[BaseMessage]:
        """
        构建初始消息列表。

        Args:
            ctx: 消息上下文

        Returns:
            按正确顺序排列的 BaseMessage 列表
        """
        messages: list[BaseMessage] = []

        # 1. SystemMessage（含 KG Anchors）
        system_content = self._build_system_content(ctx)
        if system_content:
            messages.append(SystemMessage(content=system_content))

        # 2. Background Knowledge
        if ctx.background_knowledge:
            bg = ctx.background_knowledge.strip()
            messages.append(
                HumanMessage(
                    content=(
                        f"{bg}\n\n"
                        f"请基于以上背景知识回答。如果背景不足，结合你的分析能力补充。\n"
                    )
                )
            )

        # 3. Memory Context（如果有）
        if ctx.memory_context:
            messages.append(
                HumanMessage(content=f"[历史记忆]\n{ctx.memory_context}")
            )

        # 4. User Message（永远最后）
        messages.append(HumanMessage(content=ctx.user_message))

        return messages

    def _build_system_content(self, ctx: MessageContext) -> str:
        """构建 System Message 内容（包含 KG Anchors）"""
        if not self.system_prompt_template:
            # 无模板时，KG Anchors 直接作为 system 内容
            if ctx.kg_anchors:
                return f"<kg_anchors>\n{ctx.kg_anchors}\n</kg_anchors>"
            return ""

        # 有模板时，替换占位符
        try:
            return self.system_prompt_template.format(
                memory_content=ctx.memory_context,
                kg_anchors=ctx.kg_anchors,
                **ctx.system_vars,
            )
        except (KeyError, ValueError):
            # 占位符不匹配时回退到简单拼接
            parts = []
            if ctx.kg_anchors:
                parts.append(f"<kg_anchors>\n{ctx.kg_anchors}\n</kg_anchors>")
            return "\n".join(parts)

    # ── 工具结果追加 ────────────────────────────────────────────────

    def append_tool_result(
        self,
        messages: list[BaseMessage],
        tool_name: str,
        result: str,
        tool_call_id: str,
    ) -> None:
        """
        追加 ToolMessage 到消息列表（就地修改列表）。

        Args:
            messages: 目标消息列表（由 build_initial_messages 构建）
            tool_name: 工具名称
            result: 工具执行结果
            tool_call_id: tool_call ID（来自 LLM 响应）
        """
        messages.append(
            ToolMessage(
                content=result,
                tool_call_id=tool_call_id,
                name=tool_name,
            )
        )
