"""公告 PDF 下载与章节切分模块。

公告 PDF 来自 cninfo（无频率限制），通过 pymupdf 解析正文，
按中文序号标题（一、二、三）切分为章节。
"""

from __future__ import annotations

import logging
import re

import fitz  # pymupdf
import requests

logger = logging.getLogger(__name__)

HTTP_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

# 匹配 "一、标题" 或 "一.标题" 或 "一 标题" 格式的章节标题行
# 标题长度 2-50 字符，避免匹配页码中的单个数字
_HEADING_PATTERN = re.compile(r"(?:^|\n)\s*([一二三四五六七八九十]+)[、，。．\.\s]+([^\n]{2,50})\s*\n")


def download_announcement_pdf(url: str, timeout: int = 15) -> bytes | None:
    """从 cninfo 下载公告 PDF。

    Returns:
        PDF 二进制内容，失败返回 None
    """
    if not url:
        return None
    try:
        resp = requests.get(url, timeout=timeout, headers=HTTP_HEADERS)
        resp.raise_for_status()
        content = resp.content
        if content[:5] != b"%PDF-":
            logger.warning(f"下载内容不是 PDF: {url[:80]}")
            return None
        return content
    except Exception as e:
        logger.warning(f"下载公告 PDF 失败 [{url[:80]}]: {e}")
        return None


def parse_pdf_text(pdf_content: bytes) -> str:
    """用 pymupdf 解析 PDF 正文。

    Returns:
        全文文本（多页合并，保留换行）
    """
    try:
        doc = fitz.open(stream=pdf_content, filetype="pdf")
        text_parts = []
        for page in doc:
            t = page.get_text()
            if t.strip():
                text_parts.append(t)
        doc.close()
        return "\n".join(text_parts)
    except Exception as e:
        logger.warning(f"PDF 解析失败: {e}")
        return ""


def split_by_chapters(text: str) -> list[dict]:
    """按中文序号标题切分章节。

    公告通常以"一、标题\n内容\n二、标题\n内容"格式组织。
    如果正文没有章节标题（如纯文本公告），则将全文作为一个 chunk。

    Returns:
        list of {"heading": str, "body": str}
        - heading: 章节标题（如 "一、股东会审议通过的权益分派方案等情况"），preamble 为空字符串
        - body: 该章节的正文文本
    """
    if not text.strip():
        return []

    matches = list(_HEADING_PATTERN.finditer(text))
    if not matches:
        # 无章节标题，全文作为一个 chunk
        return [{"heading": "", "body": text.strip()}]

    sections = []

    # Preamble：第一个标题之前的内容（如公司名称、公告编号等元信息）
    if matches[0].start() > 0:
        preamble = text[: matches[0].start()].strip()
        if preamble:
            sections.append({"heading": "", "body": preamble})

    # 各章节
    for i, m in enumerate(matches):
        start = m.start() + len(m.group(0))
        next_start = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        heading = f"{m.group(1)}、{m.group(2)}"
        body = text[start:next_start].strip()
        if body:
            sections.append({"heading": heading, "body": body})

    return sections
