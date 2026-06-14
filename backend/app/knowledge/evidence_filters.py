"""
Evidence 内容过滤器

过滤策略：
1. 最小长度过滤 - 过滤标题、页眉、分隔符等短内容
2. 无效模式过滤 - 过滤法律声明、合规声明
3. 表格格式过滤 - 过滤 PDF 表格噪声
4. 页眉页脚过滤 - 过滤证券代码、页码等
5. 纯符号行过滤 - 过滤纯表格行、纯符号行
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class FilterConfig:
    """过滤器配置"""
    min_chars: int = 50          # 最小字符数
    min_tokens: int | None = None  # 最小 token 数（可选）
    max_tokens: int = 2048       # 最大 token 数
    enable_table_filter: bool = True    # 过滤表格噪声
    enable_legal_filter: bool = True    # 过滤法律声明
    enable_header_filter: bool = True   # 过滤页眉页脚
    enable_noise_filter: bool = True    # 过滤纯符号行


# ── 无效内容模式 ──────────────────────────────────────────────────────────────

# 法律声明模式（常见于公告开头）
LEGAL_DISCLAIMER_PATTERNS = [
    # 中文法律声明
    r"本公司及董事会全体成员保证.{0,30}没有虚假记载",
    r"本公司及董事、监事和高级管理人员保证.{0,30}没有虚假记载",
    r"公司董事会、监事会及董事、监事、高级管理人员保证.{0,50}没有虚假记载",
    r"信息披露的内容真实、准确、完整，没有虚假记载",
    r"不存在虚假记载、误导性陈述或重大遗漏",
    r"经中国证券监督管理委员会核准",
    r"本次非公开发行股票相关事项",
    r"根据《公司法》《证券法》",
    r"按照《企业会计准则》",
    r"符合《深圳证券交易所股票上市规则》",
    r"属于公司董事会权限范围之内",
    r"无需提交股东大会审议",
    # 英文/混合
    r"Disclaimer[:：]",
    r"Copyright\s*\d{4}",
    r"版权所有",
    r"All rights reserved",
]

# 页眉页脚模式（只匹配单行纯文本，不匹配包含在其他内容中的模式）
HEADER_FOOTER_PATTERNS = [
    # 证券代码格式（精确匹配整行）
    r"^证券代码[:：]\d{6}",
    r"^证券简称[:：]",
    # 页码（精确匹配整行）
    r"^第\s*\d+\s*页$",
    r"^Page\s*\d+$",
    r"^\d+\s*/\s*\d+$",
    # 文档标题行（精确匹配整行）
    r"^投资者关系活动记录表$",
    r"^公告编号$",
]

# 表格噪声模式
TABLE_NOISE_PATTERNS = [
    # 纯表格分隔符行
    r"^\s*\|?\s*[-─═]{3,}\s*\|?\s*$",
    # Markdown 表格分隔符
    r"^\s*\|?\s*[-─═]+\s*(\|\s*[-─═]+\s*)+\|?\s*$",
    # PDF 转文本的表格行（只有 | 和 空格）
    r"^\s*\|?\s*[|\s\-─═]+\s*\|?\s*$",
    # 空或几乎空的表格单元格
    r"^\s*\|\s*\|\s*\|\s*$",
    r"^\s*\|\s*\|\s*$",
]

# 纯噪声内容模式
NOISE_PATTERNS = [
    # 纯数字或纯符号行
    r"^[数字\d\s\.%年日月时]+$",
    r"^[年月日\d]+至[\d年月日]+$",
    # 单个符号行
    r"^[\-\─=\.\·\•\‥\⋯]{3,}$",
    # 乱码或无效字符
    r"^[\x00-\x08\x0b\x0c\x0e-\x1f]+$",
]

# 合并所有模式（用于预过滤）
ALL_NOISE_PATTERNS = (
    LEGAL_DISCLAIMER_PATTERNS +
    HEADER_FOOTER_PATTERNS +
    TABLE_NOISE_PATTERNS +
    NOISE_PATTERNS
)


# ── 编译正则表达式（全局复用）──────────────────────────────────────────────────

_COMPILED_PATTERNS = {
    "legal": [re.compile(p, re.IGNORECASE) for p in LEGAL_DISCLAIMER_PATTERNS],
    "header": [re.compile(p) for p in HEADER_FOOTER_PATTERNS],
    "table": [re.compile(p) for p in TABLE_NOISE_PATTERNS],
    "noise": [re.compile(p) for p in NOISE_PATTERNS],
}


# ── 过滤函数 ──────────────────────────────────────────────────────────────────

def is_noise_content(text: str, config: FilterConfig | None = None) -> tuple[bool, str]:
    """
    判断内容是否为噪声内容。

    Args:
        text: 待检测文本
        config: 过滤器配置（可选）

    Returns:
        (is_noise, reason): 是否为噪声及原因
    """
    if not text or not text.strip():
        return True, "empty"

    config = config or FilterConfig()
    stripped = text.strip()

    # 1. 长度检查
    if len(stripped) < config.min_chars:
        return True, f"too_short ({len(stripped)} chars < {config.min_chars})"

    # 2. 法律声明检查
    if config.enable_legal_filter:
        for pattern in _COMPILED_PATTERNS["legal"]:
            if pattern.search(stripped):
                return True, "legal_disclaimer"

    # 3. 页眉页脚检查
    if config.enable_header_filter:
        for pattern in _COMPILED_PATTERNS["header"]:
            if pattern.search(stripped):
                return True, "header_footer"

    # 4. 表格噪声检查
    if config.enable_table_filter:
        for pattern in _COMPILED_PATTERNS["table"]:
            if pattern.match(stripped):
                return True, "table_noise"

    # 5. 纯噪声检查
    if config.enable_noise_filter:
        for pattern in _COMPILED_PATTERNS["noise"]:
            if pattern.match(stripped):
                return True, "noise_pattern"

    return False, ""


def should_include_chunk(text: str, config: FilterConfig | None = None) -> bool:
    """
    判断 chunk 是否应该被包含。

    Args:
        text: chunk 文本
        config: 过滤器配置

    Returns:
        True: 应该包含
        False: 应该过滤
    """
    is_noise, _ = is_noise_content(text, config)
    return not is_noise


def filter_chunks(
    chunks: list,
    config: FilterConfig | None = None,
) -> list:
    """
    过滤 chunk 列表，移除无效 chunk。

    Args:
        chunks: Chunk 对象列表或字符串列表
        config: 过滤器配置

    Returns:
        过滤后的 chunk 列表
    """
    config = config or FilterConfig()
    filtered = []

    for chunk in chunks:
        # 支持 Chunk 对象和字符串
        if hasattr(chunk, "content"):
            text = chunk.content
        else:
            text = str(chunk)

        if should_include_chunk(text, config):
            filtered.append(chunk)

    return filtered


def preprocess_text(text: str, config: FilterConfig | None = None) -> str:
    """
    预处理文本：去除明显的噪声行。

    预处理阶段只过滤明确的噪声行（不是有效内容）：
    - 页眉页脚
    - 证券代码行
    - 纯分隔符行
    - 文档标题

    表格内容在此阶段保留不分块，确保分块时不会把表格行与内容分开。
    """
    if not text:
        return text

    config = config or FilterConfig()
    lines = text.split("\n")
    filtered_lines = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        is_noise = False

        # 1. 表格分隔符行（纯分隔符）
        if config.enable_table_filter:
            for pattern in _COMPILED_PATTERNS["table"]:
                if pattern.match(stripped):
                    is_noise = True
                    break

        # 2. 页眉页脚（精确匹配）
        if not is_noise and config.enable_header_filter:
            if stripped.startswith("证券代码："):
                is_noise = True
            elif stripped == "投资者关系活动记录表":
                is_noise = True
            elif stripped == "编号：2026-002":
                is_noise = True

        if not is_noise:
            filtered_lines.append(line)

    result = "\n".join(filtered_lines)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


def clean_chunk_text(text: str) -> str:
    """
    清理 chunk 文本：规范化表格格式，去除残留噪声。

    处理策略：
    1. 跳过纯分隔符行（| --- | --- |）
    2. 处理表格行：| A | B | → A / B（更易读的格式）
    3. 合并多个连续空行
    """
    if not text:
        return text

    text = text.strip()
    lines = text.split("\n")
    cleaned_lines = []

    for line in lines:
        stripped = line.strip()

        # 跳过纯分隔符行
        if re.match(r"^\s*\|?\s*[-─═·\s]+\s*\|?\s*$", stripped):
            continue

        # 处理表格行（包含 | 但不是纯分隔符）
        if "|" in stripped:
            cells = [c.strip() for c in stripped.split("|") if c.strip()]
            if cells:
                cleaned_lines.append(" / ".join(cells))
            continue

        cleaned_lines.append(line)

    text = "\n".join(cleaned_lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ── Token 计算（用于精确过滤）─────────────────────────────────────────────────

def count_tokens(text: str) -> int:
    """计算文本的 token 数（使用 tiktoken）"""
    import tiktoken
    enc = tiktoken.get_encoding("cl100k_base")
    return len(enc.encode(text))


def is_valid_token_count(text: str, min_tokens: int, max_tokens: int) -> bool:
    """检查 token 数是否在有效范围内"""
    token_count = count_tokens(text)
    return min_tokens <= token_count <= max_tokens