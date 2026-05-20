"""
knowledge.extraction - 知识抽取模块

子模块：
- chunker: 文本分块（按 token 数量）
- chunk_dedup: chunk 去重
- announcement_filter: 公告过滤
- light_extractor: 轻量抽取（互动易Q&A）
- rag_extractor: RAG 抽取（研报、公告全文）
- signal_extractor: 信号抽取（基于规则/LLM）
"""

from app.knowledge.extraction.light_extractor import (
    LightExtractor,
    extract_light,
    get_light_extractor,
)

__all__ = [
    "LightExtractor",
    "extract_light",
    "get_light_extractor",
]
