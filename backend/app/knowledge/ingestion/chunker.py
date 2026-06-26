"""
智能多策略分块模块 v2

分块策略:
1. 段落分组：按段落（连续非空行）组织文本
2. 章节检测：按标题层级识别章节
3. 智能合并：小章节合并到 ~2000 tokens
4. 无效过滤：过滤无效章节和过短内容

关键改进:
- 按段落累加而非逐行
- 过滤无效章节（表格行、纯数字标题）
- 增大 token 限制，减少强制切分
- 合并相邻同类型内容
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# ── 分块参数常量 ────────────────────────────────────────────────

MAX_CHUNK_TOKENS = 6000  # 单块最大 token 数（增大减少强制切分）
MIN_CHUNK_TOKENS = 200  # 小于此值考虑合并
MERGE_TARGET_TOKENS = 2000  # 合并目标大小

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
        chinese = sum(1 for c in text if "一" <= c <= "鿿")
        other = len(text) - chinese
        return int(chinese * 1.5 + other * 0.25)


# ── 辅助函数 ───────────────────────────────────────────────────


def _is_table_line(line: str) -> bool:
    """判断是否表格行"""
    if "|" in line:
        return True
    # 包含大量数字或百分比的行（表格单元格）
    if len(line) > 20 and len(re.findall(r"[\d%,]", line)) > len(line) * 0.3:
        return True
    return False


def _is_prose_line(line: str) -> bool:
    """判断是否正文段落（不应作为标题）"""
    stripped = line.strip()
    if not stripped:
        return False
    # 如果包含句号、逗号等正文特征，可能是正文
    if "，" in stripped or "。" in stripped:
        return True
    # 如果不是以标题特征开头，且有正文特征，可能是正文
    if not re.match(r"^[第#一二三四五六七八九十\d]+", stripped):
        if len(stripped) > 15:
            return True
    return False


def _is_truncated_paragraph(para: str, prev_body: str) -> bool:
    """
    判断当前段落是否是被截断的文本（应该合并到上一段）

    特征：
    1. 段落很短（<50 字符）
    2. 上一段的最后一行以中文字符结尾（没有句号）
    3. 当前段落不以标题特征开头
    """
    if not para.strip() or len(para) > 100:
        return False

    # 如果上一段以句号/逗号结尾，不是截断
    if prev_body:
        last_chars = prev_body.strip()[-3:] if len(prev_body) >= 3 else prev_body.strip()
        if any(c in last_chars for c in "。！？，；"):
            return False

    # 当前段落不以标题特征开头
    first_line = para.split("\n")[0].strip()
    if re.match(r"^[第#一二三四五六七八九十\d]", first_line):
        return False
    if re.match(r"^\d+[\.、]\s", first_line):
        return False

    return True


def _is_valid_heading(heading: str) -> bool:
    """判断标题是否有效"""
    if not heading:
        return False
    if _is_table_line(heading):
        return False
    # 纯数字/百分比
    if re.match(r"^[\d\s%\.%,]+$", heading):
        return False
    # 过短
    if len(heading) < 3:
        return False
    # 投资者关系表格
    if "投资者关系活动" in heading:
        return False
    return True


def _is_valid_chunk(text: str, heading: str) -> bool:
    """判断 chunk 是否有效"""
    if not text.strip():
        return False
    # 纯表格（无标题时）
    if not heading:
        first_line = text.strip().split("\n")[0] if text else ""
        if first_line.startswith("|"):
            return False
    return True


# ── Markdown 标题正则 ──────────────────────────────────────────

_MARKDOWN_PATTERN = re.compile(r"^(#{1,6})\s+(.{2,60})", re.MULTILINE)

# ── 句子边界 ───────────────────────────────────────────────────

_SENTENCE_DELIMITERS = r"[。！？；\n]"


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
    source: str = "auto"  # "chapter" | "split" | "merge" | "filtered"

    def __post_init__(self):
        if self.tokens == 0:
            self.tokens = count_tokens(self.text)


def _match_heading(line: str) -> tuple[str | None, int]:
    """
    尝试匹配标题模式

    严格匹配规则：
    1. 标题不能包含句号/逗号等正文标点
    2. 标题长度限制在合理范围
    """
    line = line.strip()
    if not line or len(line) < 2:
        return None, 0

    # 跳过表格行
    if _is_table_line(line):
        return None, 0

    # Markdown 标题
    m = _MARKDOWN_PATTERN.match(line)
    if m:
        return m.group(2).strip(), len(m.group(1))

    # 中文序号标题（严格匹配）
    # 匹配: "一、公司简介", "一.公司简介", "第一节 业务", "第一章 总则"
    # 标题部分在遇到句号、逗号、冒号等正文标点时结束
    m = re.match(r"^([一二三四五六七八九十百零]+)\s*([章节条、\.])\s*([^\n，。、；：]*?)[\s　]*$", line)
    if m:
        prefix = m.group(1)
        separator = m.group(2)
        title = m.group(3).strip()
        level = 2 if "节" in separator else 1
        if not title:
            title = f"第{prefix}{separator}"
        return title, level

    # 阿拉伯数字标题（严格匹配）
    # 匹配: "1. 公司概况", "1.1 主要业务"
    # 标题部分在遇到正文标点时结束
    m = re.match(r"^(\d+(?:\.\d+)*)\s*[\.、]\s*([^\n，。、；：]+)[\s　]*$", line)
    if m:
        prefix = m.group(1)
        title = m.group(2).strip()
        level = prefix.count(".") + 1
        if not title:
            return None, 0  # 只有 "1." 而没有标题，不作为章节
        # 标题不能太长（正文被误识别）
        if len(title) > 30:
            return None, 0
        return title, level

    # 正文段落，不是标题
    if _is_prose_line(line):
        return None, 0

    return None, 0


def _group_into_paragraphs(text: str) -> list[str]:
    """将文本按段落（连续非空行）分组"""
    raw_lines = text.split("\n")
    paragraphs: list[str] = []
    current_lines: list[str] = []

    for line in raw_lines:
        if line.strip():
            current_lines.append(line)
        else:
            if current_lines:
                paragraphs.append("\n".join(current_lines))
                current_lines = []
    if current_lines:
        paragraphs.append("\n".join(current_lines))

    return paragraphs


def split_by_chapters(text: str) -> list[Chapter]:
    """
    按标题层级检测并分割章节

    支持的标题格式:
    - 中文序号: "一、公司简介", "第一节 业务概述", "一条 总则"
    - 阿拉伯数字: "1. 公司概况", "1.1 主要业务"
    - Markdown: "# 标题", "## 副标题"

    特殊处理:
    - 修复 PDF 列宽导致的截断标题（追加到上一段）

    Returns:
        list[Chapter]: 章节列表
    """
    if not text or not text.strip():
        return []

    # 按段落分组
    paragraphs = _group_into_paragraphs(text)

    chapters: list[Chapter] = []
    current_body_paragraphs: list[str] = []
    current_heading = ""
    current_level = 1

    def _flush_chapter(heading: str, level: int):
        """将当前内容 flush 为一个章节"""
        nonlocal current_body_paragraphs
        if current_body_paragraphs:
            body = "\n\n".join(current_body_paragraphs).strip()
            if body:
                chapters.append(
                    Chapter(
                        heading=heading,
                        body=body,
                        level=level,
                    )
                )
            current_body_paragraphs = []

    prev_body = ""  # 用于检测截断段落

    for para in paragraphs:
        # 只在段落开头检测标题
        lines = para.split("\n")
        first_line = lines[0] if lines else ""
        heading, level = _match_heading(first_line)

        if heading:
            # 遇到新标题，先 flush 之前的内容
            if current_heading or current_body_paragraphs:
                _flush_chapter(current_heading, current_level)
            current_heading = heading
            current_level = level
            # 标题后的内容作为正文
            if len(lines) > 1:
                body_lines = lines[1:]
                body = "\n".join(body_lines).strip()
                current_body_paragraphs.append(body)
                prev_body = body
            else:
                prev_body = ""
        elif _is_truncated_paragraph(para, prev_body):
            # 被截断的段落，追加到上一段
            if current_body_paragraphs and current_heading:
                current_body_paragraphs[-1] += "\n" + para
                prev_body = current_body_paragraphs[-1]
            else:
                current_body_paragraphs.append(para)
                prev_body = para
        else:
            current_body_paragraphs.append(para)
            prev_body = para

    # 处理最后一个章节
    if current_heading or current_body_paragraphs:
        _flush_chapter(current_heading, current_level)

    # 如果没有检测到任何标题，将全文作为一个章节
    if not chapters:
        chapters.append(
            Chapter(
                heading="",
                body=text.strip(),
                level=0,
            )
        )

    return chapters


def _split_oversized_chapter(chapter: Chapter, max_tokens: int) -> list[Chunk]:
    """
    切分过大的章节

    策略: 按段落累加，保持语义完整
    """
    paragraphs = _group_into_paragraphs(chapter.body)

    chunks: list[Chunk] = []
    current_para = ""
    current_tokens = 0

    for para in paragraphs:
        para_tokens = count_tokens(para)

        # 如果单个段落就超过 max_tokens，按句子切分
        if para_tokens > max_tokens:
            if current_para:
                chunks.append(
                    Chunk(
                        text=current_para,
                        heading=chapter.heading,
                        tokens=count_tokens(current_para),
                        source="split",
                    )
                )
                current_para = ""
                current_tokens = 0

            # 按句子边界切分超长段落
            sentences = re.split(f"({_SENTENCE_DELIMITERS}+)", para)
            for i in range(0, len(sentences), 2):
                sentence = sentences[i]
                delimiter = sentences[i + 1] if i + 1 < len(sentences) else ""
                full_sentence = sentence + delimiter

                sent_tokens = count_tokens(full_sentence)
                if sent_tokens > max_tokens:
                    # 超长句子保留原样
                    if full_sentence.strip():
                        chunks.append(
                            Chunk(
                                text=full_sentence.strip(),
                                heading=chapter.heading,
                                tokens=sent_tokens,
                                source="split",
                            )
                        )
                else:
                    current_para += full_sentence
                    current_tokens += sent_tokens
                    if current_tokens >= max_tokens:
                        chunks.append(
                            Chunk(
                                text=current_para.strip(),
                                heading=chapter.heading,
                                tokens=current_tokens,
                                source="split",
                            )
                        )
                        current_para = ""
                        current_tokens = 0
        else:
            # 普通段落累加
            if current_tokens + para_tokens > max_tokens:
                if current_para:
                    chunks.append(
                        Chunk(
                            text=current_para.strip(),
                            heading=chapter.heading,
                            tokens=current_tokens,
                            source="split",
                        )
                    )
                current_para = para
                current_tokens = para_tokens
            else:
                if current_para:
                    current_para += "\n\n" + para
                else:
                    current_para = para
                current_tokens += para_tokens

    # 处理剩余内容
    if current_para.strip():
        chunks.append(
            Chunk(
                text=current_para.strip(),
                heading=chapter.heading,
                tokens=count_tokens(current_para.strip()),
                source="split",
            )
        )

    return chunks


def merge_small_chunks(chapters: list[Chapter], target_tokens: int = MERGE_TARGET_TOKENS) -> list[Chapter]:
    """
    合并相邻小章节

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
            combined_body = "\n\n".join(c.body for c in buffer)
            first_heading = buffer[0].heading
            min_level = min(c.level for c in buffer)
            merged.append(
                Chapter(
                    heading=first_heading,
                    body=combined_body,
                    level=min_level,
                )
            )
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
    智能多策略分块主函数 v2

    流程:
    1. 章节检测
    2. 小章节合并
    3. 过大的章节按段落切分

    Args:
        text: 输入文本
        max_tokens: 单块最大 token 数

    Returns:
        list[Chunk]: 分块结果
    """
    if not text or not text.strip():
        return []

    # 策略1: 章节检测
    chapters = split_by_chapters(text)

    # 策略2: 小章节合并
    chapters = merge_small_chunks(chapters)

    # 策略3: 过大的章节按段落切分
    result_chunks: list[Chunk] = []

    for chapter in chapters:
        if chapter.tokens <= max_tokens:
            result_chunks.append(
                Chunk(
                    text=f"{chapter.heading}\n\n{chapter.body}" if chapter.heading else chapter.body,
                    heading=chapter.heading,
                    tokens=chapter.tokens,
                    source="chapter",
                )
            )
        else:
            sub_chunks = _split_oversized_chapter(chapter, max_tokens)
            result_chunks.extend(sub_chunks)

    return result_chunks


def filter_invalid_chunks(chunks: list[Chunk]) -> list[Chunk]:
    """过滤无效 chunks"""
    result = []
    for chunk in chunks:
        if _is_valid_chunk(chunk.text, chunk.heading):
            # 过滤纯表格内容（无标题时）
            if not chunk.heading:
                first_line = chunk.text.strip().split("\n")[0] if chunk.text else ""
                if first_line.startswith("|"):
                    continue
            result.append(chunk)
    return result


class SmartChunker:
    """
    智能分块器 v2

    改进:
    - 按段落累加，保持语义完整
    - 过滤无效章节（表格行、纯数字标题）
    - 增大 token 限制（6000）
    - 小章节合并到 ~2000 tokens
    """

    def __init__(
        self,
        max_tokens: int = MAX_CHUNK_TOKENS,
        min_tokens: int = MIN_CHUNK_TOKENS,
        merge_target: int = MERGE_TARGET_TOKENS,
        filter_invalid: bool = True,
    ):
        self.max_tokens = max_tokens
        self.min_tokens = min_tokens
        self.merge_target = merge_target
        self.filter_invalid = filter_invalid

    def chunk(self, text: str) -> list[Chunk]:
        """对文本进行智能分块"""
        chunks = chunk_text(text, self.max_tokens)
        if self.filter_invalid:
            chunks = filter_invalid_chunks(chunks)
        return chunks

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
