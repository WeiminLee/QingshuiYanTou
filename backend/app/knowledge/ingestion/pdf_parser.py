"""
PyMuPDF PDF 解析器

用 PyMuPDF（pymupdf）替代 pdfplumber，解析速度提升 10-50 倍，内存占用更低。

文本提取策略：
1. 按页读取纯文本（page.get_text("text")）
2. 按行过滤页眉页脚（页码等）
3. 按阅读顺序拼接
4. 不做专门的表格提取（表格以普通文本形式提取）

注意：使用 import pymupdf 而非 import fitz（fitz 已弃用）。
"""

import logging
import re
from dataclasses import dataclass

import pymupdf

try:
    import pymupdf4llm
except ImportError:  # optional enhancement; PyMuPDF remains the fallback
    pymupdf4llm = None

logger = logging.getLogger(__name__)


@dataclass
class PdfSection:
    """
    单个 PDF 区块。

    Fields:
        text:     区块正文
        pos:      位置标签（如页码，用于溯源）
        is_table: 是否为表格区块（当前版本始终为 False）
        table_str: 表格的 markdown 字符串（当前版本始终为空）
        page_num: 所在页码（1-indexed）
    """

    text: str
    pos: str = ""
    is_table: bool = False
    table_str: str = ""
    page_num: int = 0


# ── 页眉页脚过滤 ────────────────────────────────────────────────────────────

# 常见页眉页脚模式（用于过滤）
_HEADER_FOOTER_PATTERNS = [
    re.compile(r"^\d+\s*/\s*\d+$"),  # "1 / 3"
    re.compile(r"^-\s*\d+\s*-$"),  # "- 3 -"
    re.compile(r"^\*{3,}$"),  # "***"
    re.compile(r"^第\d+页$"),  # "第3页"
    re.compile(r"^\[\s*\d+\s*\]$"),  # "[3]"
    re.compile(r"^[A-Z]{2,}\s*\d{4}.*$"),  # "AA1234 ...", confidentiality headers
    re.compile(r"^\d+\s*$"),  # 纯数字（页码）
]


def _is_header_footer_line(line: str) -> bool:
    """判断一行文本是否为页眉/页脚（基于内容模式，不依赖位置）。"""
    line = line.strip()
    if not line or len(line) < 2:
        return True

    # 太短且纯数字 → 页码
    if len(line) <= 5 and re.match(r"^\d+$", line):
        return True

    # 仅数字和标点 → 可能是页码或分隔符
    if re.match(r"^[\d\s\-–\—.]+$", line):
        return True

    # 匹配常见页眉页脚模式
    for pat in _HEADER_FOOTER_PATTERNS:
        if pat.match(line):
            return True

    return False


def _clean_text(text: str) -> str:
    """
    清洗 PDF 文本：合并空格、精细化换行处理。

    策略：仅对"两边都是非标点中英文字符"的换行做合并。
    保留：列表项（• 开头）、代码块、诗歌等需要保留换行的内容。
    """
    if not text:
        return ""
    # 合并多个空格
    text = re.sub(r"[ \t]+", " ", text)

    def _should_merge(m: re.Match) -> str:
        """判断换行是否应合并为空格"""
        before = m.group(1)
        after = m.group(2)
        # 如果任一边是标点符号，保留换行（可能用于列表）
        if before.strip() in {"•", "-", "*", "+", "·", "|"} or after.strip() in {
            "•",
            "-",
            "*",
            "+",
            "·",
            "|",
        }:
            return before + "\n" + after
        # 如果后面是列表标记开头，保留换行
        if re.match(r"^\s*[•\-*+·\d]+\s", after):
            return before + "\n" + after
        # 合并为空格
        return before + " " + after

    text = re.sub(r"([^\n])\n([^\n])", _should_merge, text)
    return text.strip()


# ── PDF 文本提取 ─────────────────────────────────────────────────────────────


def extract_pdf_sections(
    pdf_path: str,
    max_pages: int = 100,
    extract_tables: bool = True,  # kept for backwards compat, unused
) -> list[PdfSection]:
    """
    从 PDF 提取文本区块。

    使用 PyMuPDF（pymupdf）按页读取纯文本，过滤页眉页脚。

    Args:
        pdf_path: PDF 文件路径
        max_pages: 最大处理页数（默认 100）
        extract_tables: 保留参数，当前版本不做专门的表格提取

    Returns:
        list[PdfSection]，按阅读顺序排列
    """
    sections: list[PdfSection] = []

    try:
        doc = pymupdf.open(pdf_path)
    except Exception as e:
        logger.error("PDF 打开失败 [%s]: %s", pdf_path, e)
        return sections

    try:
        total_pages = min(len(doc), max_pages)

        for page_idx in range(total_pages):
            try:
                page = doc[page_idx]
                page_num = page_idx + 1
                page_text = page.get_text("text")
            except Exception as e:
                logger.debug("PDF 文本提取失败 [%s p%d]: %s", pdf_path, page_idx + 1, e)
                continue

            if not page_text.strip():
                continue

            # 按行分割，过滤页眉页脚
            lines = page_text.split("\n")
            filtered_lines: list[str] = []
            for line in lines:
                if not _is_header_footer_line(line):
                    filtered_lines.append(line)

            page_clean = "\n".join(filtered_lines).strip()
            if not page_clean:
                continue

            page_clean = _clean_text(page_clean)

            sections.append(
                PdfSection(
                    text=page_clean,
                    pos=f"p{page_num}",
                    page_num=page_num,
                )
            )

            # Table extraction is deliberately lazy: only invoke pdfplumber on
            # pages whose text looks tabular, keeping the fast PyMuPDF path for
            # ordinary prose.  Failures fall back to the already captured text.
            if extract_tables and _looks_like_table(page_text):
                sections.extend(_extract_table_sections(pdf_path, page_num))
    finally:
        doc.close()

    return sections


def _looks_like_table(text: str) -> bool:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < 3:
        return False
    numeric = sum(1 for line in lines if len(re.findall(r"[\d%,]", line)) >= 3)
    return numeric >= 2 or sum("  " in line for line in lines) >= 2


def _extract_table_sections(pdf_path: str, page_num: int) -> list[PdfSection]:
    try:
        import pdfplumber

        with pdfplumber.open(pdf_path) as pdf:
            page = pdf.pages[page_num - 1]
            tables = page.extract_tables() or []
    except Exception as exc:
        logger.debug("table extraction skipped [%s p%d]: %s", pdf_path, page_num, exc)
        return []

    sections: list[PdfSection] = []
    for table in tables:
        rows = [[str(cell or "").replace("\n", " ").strip() for cell in row] for row in table]
        rows = [row for row in rows if any(row)]
        if len(rows) < 2:
            continue
        width = max(len(row) for row in rows)
        rows = [row + [""] * (width - len(row)) for row in rows]
        header, body = rows[0], rows[1:]
        markdown = "| " + " | ".join(header) + " |\n"
        markdown += "| " + " | ".join(["---"] * width) + " |\n"
        markdown += "\n".join("| " + " | ".join(row) + " |" for row in body)
        sections.append(PdfSection(markdown, pos=f"p{page_num}", is_table=True, table_str=markdown, page_num=page_num))
    return sections


# ── 主入口 ─────────────────────────────────────────────────────────────────


def extract_text_from_pdf(
    pdf_path: str,
    max_pages: int = 1000,
) -> str:
    """
    提取 PDF 文本。

    使用 PyMuPDF（pymupdf）快速提取文本，按页排列。

    流程：
    1. extract_pdf_sections → list[PdfSection]（每页一个 section）
    2. sections 按阅读顺序拼接为纯文本字符串

    Args:
        pdf_path: PDF 文件路径
        max_pages: 最大处理页数（默认 1000）

    Returns:
        str: 提取的文本内容
    """
    sections = extract_pdf_sections(pdf_path, max_pages=max_pages, extract_tables=False)

    if not sections:
        return ""

    # 按阅读顺序拼接
    parts: list[str] = []
    for sec in sections:
        parts.append(sec.text)

    return "\n\n".join(parts)


def extract_structured_text_from_pdf(pdf_path: str, max_pages: int = 1000) -> str:
    """Extract Markdown-like headings/paragraphs when pymupdf4llm is available."""
    if pymupdf4llm is None:
        return extract_text_from_pdf(pdf_path, max_pages=max_pages)
    try:
        doc = pymupdf.open(pdf_path)
        pages = list(range(min(len(doc), max_pages)))
        doc.close()
        return pymupdf4llm.to_markdown(pdf_path, pages=pages)
    except Exception as exc:
        logger.warning("structured PDF extraction failed [%s]: %s", pdf_path, exc)
        return extract_text_from_pdf(pdf_path, max_pages=max_pages)
