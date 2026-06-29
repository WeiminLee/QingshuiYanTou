"""
summarize — Agent 分层摘要工具

实体锚定 + 按需生成 + 缓存优先。
Agent 用此工具获取 L1/L2/L3 摘要，替代逐边遍历。

!!! Anti-pattern 警告
    不要使用 `@tool` + `asyncio.run()` 模式（会在已有事件循环中崩溃）。
    必须继承 `StructuredTool` 并同时实现 `_run`(sync fallback) + `_arun`(async)。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from langchain_core.tools import StructuredTool

from app.knowledge.summary_aggregator import aggregate_l1, aggregate_l2, aggregate_l3

logger = logging.getLogger(__name__)


class SummarizeTool(StructuredTool):
    """获取知识图谱实体的分层摘要。

    使用场景：
    - 宏观问题（"光模块行业现状"）→ level=2 查产品生态，需要全局视角时 level=3
    - 中观问题（"800G光模块竞争格局"）→ level=2 查产品生态
    - 微观问题（"中际旭创的客户"）→ level=1 查公司画像，需要细节时用 expand

    缓存优先：命中则直接返回，未命中则 LLM 生成并缓存。
    """

    name: str = "summarize"
    description: str = (
        "获取知识图谱实体的分层摘要（L1=公司画像, L2=产品生态, L3=产业链视图）。"
        "缓存优先，按需生成。宏观问题用L2/L3，微观问题用L1。"
    )
    args_schema: type | None = None

    def _validate(self, entity_id: str, level: int, depth: int = 3) -> str | None:
        """参数校验，返回 None 表示通过，否则返回错误消息。"""
        if not entity_id:
            return "请先用 resolve 工具获取实体 ID。"
        if level not in (1, 2, 3):
            return f"无效的层级: {level}。有效值: 1（公司画像）, 2（产品生态）, 3（产业链视图）"
        return None

    async def _arun(
        self,
        entity_id: str,
        level: int,
        depth: int = 3,
    ) -> str:
        """异步入口 — LangChain + FastAPI 兼容。"""
        error = self._validate(entity_id, level, depth)
        if error:
            return error
        try:
            if level == 1:
                return await aggregate_l1(entity_id)
            elif level == 2:
                return await aggregate_l2(entity_id)
            else:
                return await aggregate_l3(entity_id, depth=min(depth, 3))
        except Exception as e:
            logger.error("summarize failed [%s L%d]: %s", entity_id, level, e, exc_info=True)
            return f"摘要生成失败: {e}"

    def _run(
        self,
        entity_id: str,
        level: int,
        depth: int = 3,
    ) -> str:
        """同步 fallback — 仅在无事件循环时可用。"""
        error = self._validate(entity_id, level, depth)
        if error:
            return error
        try:
            return asyncio.run(self._arun(entity_id, level, depth))
        except RuntimeError as e:
            # 如果已有事件循环（如 FastAPI 环境），_run 不应被调用
            logger.error("summarize sync fallback 失败（已有事件循环）: %s", e)
            return "摘要生成失败：当前环境不支持同步调用，请使用异步调用。"
        except Exception as e:
            logger.error("summarize failed [%s L%d]: %s", entity_id, level, e, exc_info=True)
            return f"摘要生成失败: {e}"


# ── 导出单例 ──────────────────────────────────────────────────
summarize = SummarizeTool()
