"""
Token 级文本分块器

参考 RAGFlow rag/nlp/__init__.py 的 naive_merge 策略，重构核心分块逻辑。

投研文档分块策略（知识抽取专用）：
1. Markdown 标题（# ## ###）作为主要切分边界（硬切分）
   — 每个标题及其下内容视为独立语义单元，跨越标题会破坏实体上下文的完整性
   — 章节数：投研文档通常 5-20 个主要章节，不会产生过多 chunk
2. 标题块超限（>max_tokens）→ 按段落（\n\n）分割，再贪婪合并至 max_tokens
3. 极端超长段落 → 按句末标点（。！？）切分为句子，再贪婪合并
4. 非 Markdown 文件 → 直接按段落+句末标点处理

chunk size 设计（2026-04-14 重构）：
- RAGFlow General: 512 tokens
- 清水知识抽取: 1024 tokens（投研文档信息密度高，扩展上下文提升实体召回率）
- 投研文档段落较长，1024 tokens ≈ 1500-2500 中文字符
"""
from __future__ import annotations

import re
import tiktoken
from typing import NamedTuple


class Chunk(NamedTuple):
    """
    单个文本块。

    Fields:
        content:      chunk 正文
        token_count: 该 chunk 的 token 数
        chunk_id:    块编号（全局唯一）
        heading:     所属段落的标题/小标题（用于溯源和上下文还原）
    """
    content: str
    token_count: int
    chunk_id: int
    heading: str = ""


# ── tiktoken cl100k_base encoder（全局复用） ────────────────────────────────

_encoder = None


def _get_encoder():
    global _encoder
    if _encoder is None:
        _encoder = tiktoken.get_encoding("cl100k_base")
    return _encoder


def num_tokens(text: str) -> int:
    """计算文本的 token 数（cl100k_base）"""
    return len(_get_encoder().encode(text))


# ── 分块策略常量 ──────────────────────────────────────────────────────────────

DEFAULT_CHUNK_TOKEN_NUM = 1024
MIN_CHUNK_TOKENS_FOR_HEADING = 8


# ── Markdown 解析 ──────────────────────────────────────────────────────────────

# Markdown 标题行模式：# ## ### #### ##### ######（1-6 级）
_RE_HEADING = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
# 段落分隔：连续空行
_RE_PARAGRAPH = re.compile(r"\n{2,}")
# 句末标点（中英文）
_RE_SENTENCE = re.compile(r"(?<=[。！？!?\.!\?])\s*")


def _is_markdown(text: str) -> bool:
    """快速判断文本是否为 Markdown 格式（以 # 开头的行存在）"""
    return bool(_RE_HEADING.search(text))


def _extract_headings(text: str) -> list[tuple[int, str, str]]:
    """
    提取所有 Markdown 标题。

    Returns:
        list of (line_number, heading_level, heading_text)
    """
    lines = text.split("\n")
    headings = []
    for i, line in enumerate(lines):
        m = _RE_HEADING.match(line.strip())
        if m:
            level = len(m.group(1))
            headings.append((i, level, m.group(2).strip()))
    return headings


def _split_by_headings(text: str) -> list[tuple[str, str, int]]:
    """
    按 Markdown 标题切分文本。

    Returns:
        list of (block_text, heading_text, heading_level)
        第一个 block 为文档开头（无标题），heading=""，level=0
    """
    headings = _extract_headings(text)
    if not headings:
        return [(text.strip(), "", 0)]

    lines = text.split("\n")
    blocks = []

    # 文档开头（从0到第一个标题）
    if headings[0][0] > 0:
        start_line = 0
        start_heading = ""
        start_level = 0
    else:
        start_line = headings[0][0]
        start_heading = headings[0][1]
        start_level = headings[0][2]

    # 按标题分块
    prev_pos = 0
    prev_heading = start_heading
    prev_level = start_level

    for i, (line_no, level, heading_text) in enumerate(headings):
        if line_no == start_line:
            continue  # 跳过第一个标题
        # 当前块：从 prev_pos 到当前标题行之前
        block_text = "\n".join(lines[prev_pos:line_no]).strip()
        blocks.append((block_text, prev_heading, prev_level))
        prev_pos = line_no
        prev_heading = heading_text
        prev_level = level

    # 最后一个块：从最后标题到文档末尾
    last_block = "\n".join(lines[prev_pos:]).strip()
    blocks.append((last_block, prev_heading, prev_level))

    return blocks


# ── 按段落+句末标点 贪婪合并至 max_tokens ────────────────────────────────────

def _split_block_to_chunks(
    block_text: str,
    heading: str,
    max_tokens: int,
    chunk_id_start: int,
) -> list[Chunk]:
    """
    将一个 Markdown 标题块切分为多个不超过 max_tokens 的 chunk。

    策略（参考 RAGFlow _build_cks + _merge_cks）：
    1. 先按段落（\n\n）分割为子 section
    2. 每个 section < max_tokens → 直接加入当前 chunk
    3. section > max_tokens → 按句末标点贪婪合并至 max_tokens
    4. 合并后仍超限 → 按 token 强制等分（兜底）
    """
    if not block_text.strip():
        return []

    enc = _get_encoder()

    # Step 1: 按段落分割
    raw_sections = _RE_PARAGRAPH.split(block_text)
    sections = [s.strip() for s in raw_sections if s.strip()]
    if not sections:
        return []

    chunks: list[Chunk] = []
    chunk_id = chunk_id_start
    current_paras: list[str] = []
    current_tokens = 0

    def _flush() -> None:
        nonlocal current_paras, current_tokens, chunk_id
        if not current_paras:
            return
        chunks.append(Chunk(
            content="\n\n".join(current_paras),
            token_count=current_tokens,
            chunk_id=chunk_id,
            heading=heading,
        ))
        chunk_id += 1
        current_paras = []
        current_tokens = 0

    for section in sections:
        section_toks = num_tokens(section)

        # 段落本身超限 → 按句末标点切分后贪婪合并
        if section_toks > max_tokens:
            _flush()
            sub_chunks = _split_long_section(section, max_tokens, enc, heading)
            for sc in sub_chunks:
                chunks.append(Chunk(
                    content=sc,
                    token_count=num_tokens(sc),
                    chunk_id=chunk_id,
                    heading=heading,
                ))
                chunk_id += 1
            continue

        # 追加后超限 → 先 flush 当前块，再开新块
        if current_tokens + section_toks > max_tokens and current_paras:
            _flush()

        # 加入当前块
        current_paras.append(section)
        current_tokens += section_toks

    _flush()
    return chunks


def _split_long_section(
    section: str,
    max_tokens: int,
    enc: tiktoken.Encoding,
    heading: str,
) -> list[str]:
    """
    将超长段落按句末标点切分，贪婪合并至 max_tokens。

    参考 RAGFlow _split_long_paragraph + 兜底 token 等分。
    """
    # 按句末标点分割（中英文）
    sentences = _RE_SENTENCE.split(section)
    sentences = [s.strip() for s in sentences if s.strip()]
    if not sentences:
        return [section]

    result: list[str] = []
    current: list[str] = []
    current_toks = 0

    for sent in sentences:
        sent_toks = num_tokens(sent)
        if current_toks + sent_toks <= max_tokens:
            current.append(sent)
            current_toks += sent_toks
        else:
            if current:
                result.append(" ".join(current))
            current = [sent]
            current_toks = sent_toks

    if current:
        result.append(" ".join(current))

    # 兜底：仍有超限块时按 token 等分
    final: list[str] = []
    for block in result:
        block_toks = num_tokens(block)
        if block_toks <= max_tokens:
            final.append(block)
        else:
            tokens = enc.encode(block)
            for i in range(0, len(tokens), max_tokens):
                chunk_tokens = tokens[i : i + max_tokens]
                decoded = enc.decode(chunk_tokens)
                if decoded.strip():
                    final.append(decoded)

    return final


# ── 主分块函数 ────────────────────────────────────────────────────────────────

def chunk_by_token(
    text: str,
    max_tokens: int = DEFAULT_CHUNK_TOKEN_NUM,
    overlap_tokens: int = 0,
    overlapped_percent: float | None = None,
    chunk_id_start: int = 0,
) -> list[Chunk]:
    """
    投研文档分块策略（知识抽取专用）。

    核心原则：Markdown 标题作为主要切分边界，不跨标题合并。

    Args:
        text:               原始 Markdown 文本
        max_tokens:         单块最大 token 数（默认 1024，2026-04-14 重构）
        overlap_tokens:     块间重叠 token 数（绝对值，默认 0，不重叠）
                            关键实体常在跨段处，overlap 可防止关系丢失
        overlapped_percent:  基于 max_tokens 的重叠比例（0-50，推荐 10-20）
                            当设置时，会自动计算 overlap_tokens = max_tokens * overlapped_percent / 100
                            例如：max_tokens=1024, overlapped_percent=20 → overlap_tokens=205
        chunk_id_start:     chunk_id 起始编号

    Returns:
        list[Chunk]，按阅读顺序排列，每块带 heading 信息
    """
    if not text or not text.strip():
        return []

    # 处理 overlapped_percent 参数
    if overlapped_percent is not None:
        if overlapped_percent < 0 or overlapped_percent > 50:
            raise ValueError("overlapped_percent must be between 0 and 50")
        overlap_tokens = int(max_tokens * overlapped_percent / 100)

    text = text.strip()
    enc = _get_encoder()
    chunks: list[Chunk] = []
    chunk_id = chunk_id_start
    overlap_text = ""  # 累积 overlap 内容

    if _is_markdown(text):
        # ── Markdown 文件：按标题分块 ────────────────────────────────
        blocks = _split_by_headings(text)
        for block_text, heading, _ in blocks:
            if not block_text.strip():
                continue
            block_tokens = num_tokens(block_text)

            # 注入 overlap 前缀
            if overlap_text and overlap_tokens > 0:
                block_text = overlap_text + "\n\n" + block_text
                block_tokens = num_tokens(block_text)

            if block_tokens <= max_tokens:
                # 整体块不超过限制，直接作为一个 chunk
                chunks.append(Chunk(
                    content=block_text,
                    token_count=block_tokens,
                    chunk_id=chunk_id,
                    heading=heading,
                ))
                chunk_id += 1
                # 保留末尾 overlap
                overlap_text = _extract_tail_text(block_text, overlap_tokens, enc)
            else:
                # 超限 → 按段落+句末标点拆分
                sub_chunks = _split_block_to_chunks(
                    block_text, heading, max_tokens, chunk_id,
                )
                chunks.extend(sub_chunks)
                chunk_id += len(sub_chunks)
                # 从最后一个 sub_chunk 提取 overlap
                if sub_chunks:
                    overlap_text = _extract_tail_text(sub_chunks[-1].content, overlap_tokens, enc)
                else:
                    overlap_text = ""

    else:
        # ── 非 Markdown 文件：直接按段落处理 ───────────────────────────
        # 注入 overlap 前缀
        if overlap_text and overlap_tokens > 0:
            text = overlap_text + "\n\n" + text
        sub_chunks = _split_block_to_chunks(text, "", max_tokens, chunk_id_start)
        chunks.extend(sub_chunks)
        # 保留末尾 overlap
        if sub_chunks:
            overlap_text = _extract_tail_text(sub_chunks[-1].content, overlap_tokens, enc)

    return chunks


def _extract_tail_text(text: str, overlap_tokens: int, enc: tiktoken.Encoding) -> str:
    """从文本末尾提取指定 token 数的文本作为 overlap"""
    if overlap_tokens <= 0:
        return ""
    tokens = enc.encode(text)
    if len(tokens) <= overlap_tokens:
        return text
    # 取末尾 overlap_tokens
    tail_tokens = tokens[-overlap_tokens:]
    return enc.decode(tail_tokens)


# ── 保留旧接口（用于非 Markdown 或测试）───────────────────────────────────────

def chunk_by_paragraph(
    text: str,
    max_tokens: int = DEFAULT_CHUNK_TOKEN_NUM,
    chunk_id_start: int = 0,
) -> list[Chunk]:
    """简单按段落分割（不按句子切分超长段落）"""
    if not text or not text.strip():
        return []

    paragraphs = [p.strip() for p in _RE_PARAGRAPH.split(text) if p.strip()]
    if not paragraphs:
        return []

    chunks: list[Chunk] = []
    chunk_id = chunk_id_start
    current: list[str] = []
    current_tokens = 0

    for para in paragraphs:
        para_toks = num_tokens(para)
        if current_tokens + para_toks > max_tokens and current:
            chunks.append(Chunk(
                content="\n".join(current),
                token_count=current_tokens,
                chunk_id=chunk_id,
            ))
            chunk_id += 1
            current = []
            current_tokens = 0
        current.append(para)
        current_tokens += para_toks

    if current:
        chunks.append(Chunk(
            content="\n".join(current),
            token_count=current_tokens,
            chunk_id=chunk_id,
        ))

    return chunks
