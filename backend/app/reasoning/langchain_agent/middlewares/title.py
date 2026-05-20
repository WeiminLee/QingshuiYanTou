"""
TitleMiddleware — 自动生成报告标题（DeerFlow plan mode）

参考 DeerFlow agents/middlewares/title_middleware.py：
- 首轮 Agent 执行完成后（reasoning_end 前）调用 LLM 生成标题
- 通过 SSE title_generated 事件推送给前端
- 可通过 config 禁用（title_enabled=False）

SSE 事件格式：
    type: "title_generated"
    data: {
        "title": "2026年光伏行业投资机会分析"
    }
"""
from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)

# 默认标题（降级用）
_DEFAULT_TITLE_TEMPLATE = "投研分析报告"


def _build_title_prompt(question: str, first_response: str) -> str:
    """构建标题生成 prompt"""
    user_q = question.strip()[:200]
    assistant_q = first_response.strip()[:300]
    return (
        "你是一个投研报告标题生成助手。请根据以下对话生成一个简洁的报告标题。\n\n"
        f"用户问题：{user_q}\n"
        f"助手回答：{assistant_q}\n\n"
        "要求：\n"
        "1. 最多 8 个词，简洁明了\n"
        "2. 包含标的公司/行业名称\n"
        "3. 包含核心分析主题\n"
        "4. 直接返回标题，不要引号，不要解释\n\n"
        "示例：\n"
        "• 中际旭创光模块业务竞争力分析\n"
        "• 光伏行业2026年供需格局展望\n"
        "• 宁德时代储能业务对比分析\n\n"
        "标题："
    )


class TitleMiddleware:
    """
    自动生成报告标题。

    策略：
    - 仅首轮对话生成（`generate_title` 仅首次调用生效）
    - 调用 LLM 生成短标题（max 8 词）
    - 生成失败时降级到默认标题
    """

    def __init__(
        self,
        enabled: bool = True,
        max_words: int = 8,
        max_chars: int = 60,
        generation_timeout: float = 10.0,
    ):
        self.enabled = enabled
        self.max_words = max_words
        self.max_chars = max_chars
        self.generation_timeout = generation_timeout
        # 仅首轮生成
        self._generated: dict[str, bool] = {}

    def should_generate(self, thread_id: str) -> bool:
        """判断是否需要生成标题（仅首次）"""
        if not self.enabled:
            return False
        return not self._generated.get(thread_id, False)

    async def generate_title(
        self,
        question: str,
        first_response: str,
        model,
        config: dict,
        thread_id: str,
    ) -> str:
        """
        调用 LLM 生成标题。

        Args:
            question: 用户问题
            first_response: 助手首轮回答
            model: ChatOpenAI 实例（bind_tools 后的 bound_model）
            config: RunnableConfig
            thread_id: 会话 ID

        Returns:
            生成的标题字符串
        """
        if not self.should_generate(thread_id):
            return ""

        start = time.monotonic()
        try:
            from langchain_core.messages import HumanMessage

            prompt = _build_title_prompt(question, first_response)
            result = await model.ainvoke(
                [HumanMessage(content=prompt)],
                config=config,
            )

            # 提取文本
            content = getattr(result, "content", None) or ""
            if isinstance(content, list):
                content = "".join(
                    b.get("text", "") for b in content if isinstance(b, dict)
                )

            title = str(content).strip()

            # 截断到 max_chars
            if len(title) > self.max_chars:
                title = title[: self.max_chars - 3] + "..."

            # 清理引号和多余空白
            title = title.strip().strip('"\'')
            if not title:
                title = _DEFAULT_TITLE_TEMPLATE

            self._generated[thread_id] = True
            elapsed = time.monotonic() - start
            logger.info(
                f"[TitleMiddleware] 生成标题成功: '{title}' (thread={thread_id}, {elapsed:.1f}s)"
            )
            return title

        except Exception as e:
            elapsed = time.monotonic() - start
            logger.warning(
                f"[TitleMiddleware] 生成标题失败: {e} (thread={thread_id}, {elapsed:.1f}s)"
            )
            self._generated[thread_id] = True
            return _DEFAULT_TITLE_TEMPLATE

    def get_title(self, question: str) -> str:
        """同步降级标题（当异步生成不可用时）"""
        if not self.enabled:
            return ""
        q = question.strip()[:30]
        return f"投研分析：{q}"
