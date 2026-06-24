"""
智能多策略分块模块

分块策略（三级融合）:
1. 章节检测：按标题层级分割
2. Token 切分：章节超过 4096 tokens 时按句子边界切分
3. 小章节合并：章节小于 512 tokens 时合并到 ~2048

参考 RAGFlow rag/nlp/__init__.py 的分块模式
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# ── 分块参数常量 ────────────────────────────────────────────────

MAX_CHUNK_TOKENS = 4096      # 单块最大 token 数
MIN_CHUNK_TOKENS = 512       # 小于此值考虑合并
MERGE_TARGET_TOKENS = 2048   # 合并目标大小

# ── Token 计算 ─────────────────────────────────────────────────

try:
    import tiktoken
    _enc = None  # 延迟初始化

    def _get_encoder():
        global _enc
        if _enc is None:
            _enc = tiktoken.get_encoding("cl100k_base")
        return _enc

    def count_tokens(text: str) -> int:
        """使用 tiktoken 计算 token 数"""
        return len(_get_encoder().encode(text))
except ImportError:
    # Fallback: 粗略估算 (中文字符约 1.5 tokens)
    def count_tokens(text: str) -> int:
        chinese = sum(1 for c in text if '一' <= c <= '鿿')
        other = len(text) - chinese
        return int(chinese * 1.5 + other * 0.25)


# ── 章节检测正则 ───────────────────────────────────────────────

# 中文序号标题
# 匹配: "一、公司简介", "一.公司简介", "第一节 业务", "第一章 总则"
# 包括独立存在的 "第一节", "第一章" 等
# 分隔符支持: 、 . 章节条
_CHAPTER_PATTERN_CN = re.compile(
    r'^([一二三四五六七八九十百零]+)\s*([章节条、\.])\s*(.{0,60})',
    re.MULTILINE
)

# 阿拉伯数字编号标题 (1. 1.1 1.1.1)
# 匹配: "1. 公司概况", "1.1 业务", "1.1.1 产品"
_NUMBER_PATTERN = re.compile(
    r'^(\d+(?:\.\d+)*)\s*([\.、])\s*(.{0,60})',
    re.MULTILINE
)

# Markdown 标题 (# ## ###)
_MARKDOWN_PATTERN = re.compile(
    r'^(#{1,6})\s+(.{2,60})',
    re.MULTILINE
)

# 句子边界（用于切分）
_SENTENCE_DELIMITERS = r'[。！？；\n]'


@dataclass
class Chapter:
    """单个章节"""
    heading: str
    body: str
    level: int = 1  # 标题层级
    tokens: int = 0

    def __post_init__(self):
        if self.tokens == 0:
            self.tokens = count_tokens(self.heading + "\n" + self.body)


@dataclass
class Chunk:
    """单个文本块"""
    text: str
    heading: str = ""
    tokens: int = 0
    source: str = "auto"  # "chapter" | "split" | "merge"

    def __post_init__(self):
        if self.tokens == 0:
            self.tokens = count_tokens(self.text)


def split_by_chapters(text: str) -> list[Chapter]:
    """
    策略1: 按标题层级检测并分割章节

    支持的标题格式:
    - 中文序号: "一、公司简介", "第一节 业务概述", "第一条 总则"
    - 阿拉伯数字: "1. 公司概况", "1.1 主要业务", "1.1.1 产品介绍"
    - Markdown: "# 标题", "## 副标题"

    Returns:
        list[Chapter]: 章节列表，包含 heading、body、level、tokens
    """
    if not text or not text.strip():
        return []

    lines = text.split('\n')
    chapters: list[Chapter] = []
    current_body_lines: list[str] = []
    current_heading = ""
    current_level = 1

    def _flush_chapter(heading: str, level: int):
        """将当前内容 flush 为一个章节"""
        nonlocal current_body_lines
        body = "\n".join(current_body_lines).strip()
        if body:
            chapters.append(Chapter(
                heading=heading,
                body=body,
                level=level,
            ))
        current_body_lines = []

    def _match_heading(line: str) -> tuple[Optional[str], int]:
        """尝试匹配标题模式，返回 (heading, level) 或 (None, 0)"""
        line = line.strip()
        if not line or len(line) < 3:
            return None, 0

        # Markdown 标题
        m = _MARKDOWN_PATTERN.match(line)
        if m:
            level = len(m.group(1))  # # 的数量
            return m.group(2).strip(), level

        # 中文序号标题
        m = _CHAPTER_PATTERN_CN.match(line)
        if m:
            prefix = m.group(1)
            separator = m.group(2)
            title = m.group(3) or ""
            # 判断是章还是节
            if '节' in separator:
                level = 2
            else:
                level = 1
            # 如果标题为空，使用 "第X节" 格式
            if not title.strip():
                title = f"第{prefix}{separator}"
            return title.strip(), level

        # 阿拉伯数字标题
        m = _NUMBER_PATTERN.match(line)
        if m:
            prefix = m.group(1)
            separator = m.group(2)
            title = m.group(3) or ""
            level = prefix.count('.') + 1
            # 如果标题为空，使用 "1.1" 格式
            if not title.strip():
                title = prefix
            return title.strip(), level

        return None, 0

    for line in lines:
        heading, level = _match_heading(line)

        if heading:
            # 遇到新标题，先 flush 之前的内容
            if current_heading or current_body_lines:
                _flush_chapter(current_heading, current_level)
            current_heading = heading
            current_level = level
        else:
            current_body_lines.append(line)

    # 处理最后一个章节
    if current_heading or current_body_lines:
        _flush_chapter(current_heading, current_level)

    # 如果没有检测到任何标题，将全文作为一个章节
    if not chapters:
        chapters.append(Chapter(
            heading="",
            body=text.strip(),
            level=0,
        ))

    return chapters


def _split_by_sentences(text: str, max_tokens: int) -> list[str]:
    """
    按句子边界切分文本

    策略: 按句子边界切分，确保不截断完整句子。

    Returns:
        list[str]: 句子块列表
    """
    # 先按换行分割（保留段落结构）
    paragraphs = text.split('\n')

    chunks: list[str] = []
    current_chunk = ""
    current_tokens = 0

    for para in paragraphs:
        para = para.strip()
        if not para:
            # 空行作为分隔符
            if current_chunk:
                chunks.append(current_chunk.strip())
                current_chunk = ""
                current_tokens = 0
            continue

        para_tokens = count_tokens(para)

        if para_tokens > max_tokens:
            # 段落过长，按句子切分
            if current_chunk:
                chunks.append(current_chunk.strip())
                current_chunk = ""
                current_tokens = 0

            # 按句子边界分割
            sentences = re.split(f'({_SENTENCE_DELIMITERS}+)', para)
            for i in range(0, len(sentences), 2):
                sentence = sentences[i]
                delimiter = sentences[i + 1] if i + 1 < len(sentences) else ""
                full_sentence = sentence + delimiter

                sent_tokens = count_tokens(full_sentence)
                if sent_tokens > max_tokens:
                    # 单个句子超过限制，保留原样
                    if full_sentence.strip():
                        chunks.append(full_sentence.strip())
                else:
                    current_chunk += full_sentence
                    current_tokens += sent_tokens
                    if current_tokens >= max_tokens:
                        chunks.append(current_chunk.strip())
                        current_chunk = ""
                        current_tokens = 0
        else:
            # 段落大小合适，累加
            if current_tokens + para_tokens > max_tokens:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                current_chunk = para
                current_tokens = para_tokens
            else:
                if current_chunk:
                    current_chunk += "\n" + para
                else:
                    current_chunk = para
                current_tokens += para_tokens

    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    return chunks


def merge_small_chunks(chapters: list[Chapter], target_tokens: int = MERGE_TARGET_TOKENS) -> list[Chapter]:
    """
    策略3: 合并相邻小章节

    将多个小章节合并，直到达到 target_tokens 大小。
    只合并 level 相同或相邻的章节。
    """
    if not chapters:
        return []

    merged: list[Chapter] = []
    buffer: list[Chapter] = []
    buffer_tokens = 0

    def _flush_buffer():
        """将 buffer 中的章节合并"""
        nonlocal buffer, buffer_tokens
        if not buffer:
            return
        if len(buffer) == 1:
            merged.append(buffer[0])
        else:
            # 合并多个小章节
            combined_body = "\n\n".join(c.body for c in buffer)
            first_heading = buffer[0].heading
            min_level = min(c.level for c in buffer)
            merged.append(Chapter(
                heading=first_heading,
                body=combined_body,
                level=min_level,
            ))
        buffer = []
        buffer_tokens = 0

    for chapter in chapters:
        if chapter.tokens < MIN_CHUNK_TOKENS:
            # 小章节，加入 buffer
            buffer.append(chapter)
            buffer_tokens += chapter.tokens

            # 达到目标大小，flush
            if buffer_tokens >= target_tokens:
                _flush_buffer()
        else:
            # 大章节，先 flush buffer
            _flush_buffer()
            merged.append(chapter)

    # 处理最后剩余的 buffer
    _flush_buffer()

    return merged


def chunk_text(text: str, max_tokens: int = MAX_CHUNK_TOKENS) -> list[Chunk]:
    """
    智能多策略分块主函数

    流程:
    1. 章节检测
    2. 小章节合并（先合并，再切分）
    3. Token 切分（对仍然过大的章节）

    Args:
        text: 输入文本
        max_tokens: 单块最大 token 数

    Returns:
        list[Chunk]: 分块结果列表
    """
    if not text or not text.strip():
        return []

    # 策略1: 章节检测
    chapters = split_by_chapters(text)

    # 策略3: 小章节合并
    chapters = merge_small_chunks(chapters)

    # 策略2: Token 切分（对仍然过大的章节）
    result_chunks: list[Chunk] = []

    for chapter in chapters:
        if chapter.tokens <= max_tokens:
            # 章节大小合适
            result_chunks.append(Chunk(
                text=f"{chapter.heading}\n\n{chapter.body}" if chapter.heading else chapter.body,
                heading=chapter.heading,
                tokens=chapter.tokens,
                source="chapter",
            ))
        else:
            # 章节过长，按句子切分
            full_text = f"{chapter.heading}\n\n{chapter.body}" if chapter.heading else chapter.body
            sub_chunks = _split_by_sentences(full_text, max_tokens)

            for i, sub_text in enumerate(sub_chunks):
                result_chunks.append(Chunk(
                    text=sub_text,
                    heading=f"{chapter.heading} (第{i+1}段)" if chapter.heading else "",
                    tokens=count_tokens(sub_text),
                    source="split",
                ))

    return result_chunks


class SmartChunker:
    """
    智能分块器类

    提供可配置的接口，支持自定义参数。
    """

    def __init__(
        self,
        max_tokens: int = MAX_CHUNK_TOKENS,
        min_tokens: int = MIN_CHUNK_TOKENS,
        merge_target: int = MERGE_TARGET_TOKENS,
    ):
        self.max_tokens = max_tokens
        self.min_tokens = min_tokens
        self.merge_target = merge_target

    def chunk(self, text: str) -> list[Chunk]:
        """对文本进行智能分块"""
        return chunk_text(text, self.max_tokens)

    def chunk_with_metadata(self, text: str, metadata: dict) -> list[dict]:
        """
        返回带元数据的分块结果

        Returns:
            list[dict]: 每个块包含 text, heading, tokens, source, metadata
        """
        chunks = self.chunk(text)
        return [
            {
                "text": c.text,
                "heading": c.heading,
                "tokens": c.tokens,
                "source": c.source,
                **metadata,
            }
            for c in chunks
        ]
