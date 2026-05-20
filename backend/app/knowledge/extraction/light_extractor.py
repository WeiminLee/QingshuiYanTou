"""
LightExtractor - 轻量级实体关系抽取引擎

为短文本（公告、互动易 Q&A、新闻快讯等）设计的轻量版抽取器。

与 RAGExtractor 的差异：
1. 不做 gleaning 循环（max_gleanings=0）
2. 不带 examples
3. 简单 user/assistant 消息格式

参考 RAGFlow graphrag/light/graph_extractor.py 设计。
"""
from __future__ import annotations

import logging
from typing import Optional

from app.core.llm_client import chat
from app.knowledge.extraction.rag_prompts import (
    ANNOUNCEMENT_EXTRACTION_PROMPT,
    TUPLE_DELIMITER,
    RECORD_DELIMITER,
)
from app.knowledge.extraction.chunker import num_tokens

logger = logging.getLogger(__name__)


class LightExtractor:
    """
    轻量级抽取引擎。

    适用于：
    - 公告（标题 + 一段正文）
    - 互动易 Q&A（一问一答）
    - 新闻快讯
    - 研报摘要/关键信息
    """

    def __init__(
        self,
        language: str = "Chinese",
        max_tokens: int = 2048,
    ):
        self.language = language
        self.max_tokens = max_tokens

    async def extract(
        self,
        text: str,
        source_type: str = "announcement",
    ) -> tuple[list[dict], list[dict]]:
        """
        对短文本执行抽取流程。

        Args:
            text: 原始文本
            source_type: 数据来源类型

        Returns:
            (entities, relations)
        """
        if not text or not text.strip():
            return [], []

        # 截断超长文本
        text = self._truncate_text(text)

        # 构建消息
        messages = self._build_messages(text)

        # 调用 LLM
        try:
            response = await chat(messages)
            raw_text = response.content if hasattr(response, "content") else str(response)
        except Exception as e:
            logger.warning("LightExtractor LLM 调用失败: %s", e)
            return [], []

        # 解析输出
        return self._parse_output(raw_text)

    def _truncate_text(self, text: str) -> str:
        """截断超长文本到 max_tokens"""
        tokens = num_tokens(text)
        if tokens <= self.max_tokens:
            return text
        # 按字符比例截断
        char_ratio = self.max_tokens / tokens
        return text[:int(len(text) * char_ratio)]

    def _build_messages(self, text: str) -> list[dict]:
        """
        构建 user/assistant 交替的消息格式。

        参考 RAGFlow pack_user_ass_to_openai_messages。
        """
        prompt = ANNOUNCEMENT_EXTRACTION_PROMPT.format(input_text=text)
        return [
            {
                "role": "user",
                "content": prompt,
            }
        ]

    def _parse_output(self, raw_text: str) -> tuple[list[dict], list[dict]]:
        """
        解析 LLM 输出。

        输出格式：
        实体列表：
        (name)<|>(type)<|>(description)<|>(source)
        关系列表：
        (source)<|>(relation)<|>(target)<|>(weight)<|>(description)<|>(source)
        """
        entities = []
        relations = []

        lines = raw_text.strip().split("\n")
        current_section = None

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # 检测 section 切换
            if "实体" in line or "Entity" in line.title():
                current_section = "entity"
                continue
            elif "关系" in line or "Relation" in line.title():
                current_section = "relation"
                continue

            # 跳过分隔符
            if RECORD_DELIMITER in line:
                continue

            # 解析记录
            if current_section == "entity":
                parts = line.split(TUPLE_DELIMITER)
                if len(parts) >= 2:
                    entities.append({
                        "name": parts[0].strip(),
                        "type": parts[1].strip(),
                        "description": parts[2].strip() if len(parts) > 2 else "",
                        "source": parts[3].strip() if len(parts) > 3 else "",
                    })
            elif current_section == "relation":
                parts = line.split(TUPLE_DELIMITER)
                if len(parts) >= 3:
                    relations.append({
                        "source": parts[0].strip(),
                        "relation": parts[1].strip(),
                        "target": parts[2].strip(),
                        "weight": float(parts[3].strip()) if len(parts) > 3 and parts[3].strip() else 1.0,
                        "description": parts[4].strip() if len(parts) > 4 else "",
                        "source_ref": parts[5].strip() if len(parts) > 5 else "",
                    })

        return entities, relations


# ── 便捷函数 ────────────────────────────────────────────────────────────────

_light_extractor: Optional[LightExtractor] = None


def get_light_extractor() -> LightExtractor:
    """获取 LightExtractor 单例"""
    global _light_extractor
    if _light_extractor is None:
        _light_extractor = LightExtractor()
    return _light_extractor


async def extract_light(
    text: str,
    source_type: str = "announcement",
) -> tuple[list[dict], list[dict]]:
    """便捷函数：使用 LightExtractor 抽取实体关系"""
    extractor = get_light_extractor()
    return await extractor.extract(text, source_type)
