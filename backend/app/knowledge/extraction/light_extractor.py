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

from app.core.llm_client import chat
from app.knowledge.extraction.chunker import num_tokens
from app.knowledge.extraction.rag_prompts import (
    EXTRACTION_PROMPT,
)

logger = logging.getLogger(__name__)

# 复用 rag_extractor 的 JSON 解析器
from app.knowledge.extraction.rag_extractor import (
    _parse_json_output,
)


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
        return text[: int(len(text) * char_ratio)]

    def _build_messages(self, text: str) -> list[dict]:
        """
        构建 user/assistant 交替的消息格式。

        参考 RAGFlow pack_user_ass_to_openai_messages。
        """
        prompt = EXTRACTION_PROMPT.format(input_text=text)
        return [
            {
                "role": "user",
                "content": prompt,
            }
        ]

    def _parse_output(self, raw_text: str) -> tuple[list[dict], list[dict]]:
        """
        解析 LLM 输出（JSON 格式，复用 rag_extractor 的 JSON 解析器）。
        """
        if not raw_text or not raw_text.strip():
            return [], []

        if raw_text.strip().startswith("NO_EXTRACTABLE"):
            reason = raw_text.strip().split(":", 1)[-1].strip() if ":" in raw_text else ""
            logger.debug("LightExtractor: 文本不可抽取, reason=%s", reason)
            return [], []

        result = _parse_json_output(raw_text)
        if result is None:
            return [], []

        entities_raw, relations_raw = result

        # 转换为 LightExtractor 的 list 格式
        entities = []
        for e in entities_raw:
            entity_type = e.get("entity_type", "")
            if entity_type not in ("Company", "Product", "Metric"):
                continue
            entities.append({
                "name": e["entity_name"],
                "type": entity_type,
                "description": e.get("description", ""),
                "source": e.get("source_id", ""),
            })

        relations = []
        for r in relations_raw:
            relations.append({
                "source": r["src_id"],
                "relation": r.get("description", ""),
                "target": r["tgt_id"],
                "weight": r.get("weight", 1.0),
                "description": r.get("description", ""),
                "source_ref": r.get("source_ids", [""])[0] if r.get("source_ids") else "",
            })

        return entities, relations


# ── 便捷函数 ────────────────────────────────────────────────────────────────

_light_extractor: LightExtractor | None = None


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
