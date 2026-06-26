"""
RAGFlow 风格 PDF 解析器

参考 RAGFlow deepdoc/parser/pdf_parser.py 的分块策略：
1. 布局分析：按阅读顺序（x0, top）合并相邻文本块
2. 表格提取：pdfplumber 提取表格，保持结构
3. naive_merge：按 512 tokens + delimiter 分块（与 chunker.py 策略对齐）

投研文档优先保留表格结构（财务数据/产能/产品参数）
"""

import logging
import re
from dataclasses import dataclass

import pdfplumber

logger = logging.getLogger(__name__)


@dataclass
class PdfSection:
    """
    单个 PDF 区块，参考 RAGFlow 的 section 概念。

    Fields:
        text:     区块正文
        pos:      位置标签（如页码、列号，用于溯源）
        is_table: 是否为表格区块
        table_str: 表格的 markdown 字符串（is_table=True 时有效）
        page_num: 所在页码（1-indexed）
    """

    text: str
    pos: str = ""
    is_table: bool = False
    table_str: str = ""
    page_num: int = 0


# ── 布局分析 ────────────────────────────────────────────────────────────────

# 常见页眉页脚模式（用于过滤）
_HEADER_FOOTER_PATTERNS = [
    re.compile(r"^\d+\s*/\s*\d+$"),  # "1 / 3"
    re.compile(r"^-\s*\d+\s*-$"),  # "- 3 -"
    re.compile(r"^\*{3,}$"),  # "***"
    re.compile(r"^第\d+页$"),  # "第3页"
    re.compile(r"^\[\s*\d+\s*\]$"),  # "[3]"
    re.compile(r"^[A-Z]{2,}\s*\d{4}.*$"),  # "AA1234 ...", confidentiality headers
]


def _is_header_footer(text: str, page_width: float, page_height: float, x0: float, top: float, bottom: float) -> bool:
    """
    综合判断文本块是否为页眉/页脚。

    综合策略（K10 修复）：
    1. 短文本 + 纯数字 → 页码
    2. 匹配常见页眉页脚模式
    3. 位于页面边缘区域（顶部/底部 5%）
    4. 仅数字 + 标点符号
    5. 居中 + 短文本（可能是标题或页眉）

    注意：不能仅靠位置判断，大标题（如"年度策略报告"）可能落在前 5%。
    """
    text = text.strip()
    if not text or len(text) < 2:
        return True

    # 太短且纯数字 → 页码
    if len(text) <= 5 and re.match(r"^\d+$", text):
        return True

    # 仅数字和标点 → 可能是页码或分隔符
    if re.match(r"^[\d\s\-–\—.]+$", text):
        return True

    # 匹配常见页眉页脚模式
    for pat in _HEADER_FOOTER_PATTERNS:
        if pat.match(text):
            return True

    # 位于页面顶部 5% 或底部 5% 且为短文本
    top_ratio = top / page_height if page_height > 0 else 0
    bottom_ratio = bottom / page_height if page_height > 0 else 1
    if (top_ratio < 0.05 or bottom_ratio > 0.95) and len(text) < 30:
        # 短文本在边缘区域，很可能是页眉/页脚
        # 排除：以章节编号开头（大标题）或 Markdown 标题标记
        if not re.match(r"^#{1,6}\s", text) and not re.match(r"^\d+[\.、]\s", text):
            return True

    # 居中 + 短文本 + 无章节编号 → 可能是页眉
    if page_width > 0:
        center = page_width / 2
        if abs(x0 - center) < page_width * 0.1 and len(text) < 30:
            # 如果是以标题模式开头，可能是真正的标题（保留）
            if not re.match(r"^#{1,6}\s", text) and not re.match(r"^\d+[\.、]\s", text):
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
            return "\n"
        # 如果后面是列表标记开头，保留换行
        if re.match(r"^\s*[•\-*+·\d]+\s", after):
            return "\n"
        # 合并为空格
        return " "

    text = re.sub(r"([^\n])\n([^\n])", _should_merge, text)
    return text.strip()


# ── PDF 文本提取 ─────────────────────────────────────────────────────────────


def extract_pdf_sections(
    pdf_path: str,
    max_pages: int = 100,  # K14 修复：默认 100 页，防止超大 PDF 超时
    extract_tables: bool = True,
) -> list[PdfSection]:
    """
    从 PDF 提取文本区块，保留阅读顺序和位置信息。

    参考 RAGFlow deepdoc/parser/pdf_parser.py 的布局分析 + _text_merge 逻辑：
    1. 逐字符/块提取，记录 x0, top, bottom（用于判断阅读顺序）
    2. 合并相邻块（x 方向重叠 → 同段落；x 方向分开 → 多列）
    3. 过滤页眉页脚
    4. 提取表格（pdfplumber）

    Args:
        pdf_path: PDF 文件路径
        max_pages: 最大处理页数（默认1000，防止超大PDF超时）
        extract_tables: 是否提取表格

    Returns:
        list[PdfSection]，按阅读顺序排列
    """
    sections: list[PdfSection] = []
    seen_table_headers: set[str] = set()  # 用于跨页表格表头去重

    try:
        with pdfplumber.open(pdf_path) as pdf:
            total_pages = min(len(pdf.pages), max_pages)

            for page_idx, page in enumerate(pdf.pages[:total_pages]):
                page_num = page_idx + 1
                page_height = page.height or 0
                page_width = page.width or 0

                # ── 提取表格 ──────────────────────────────────────────────
                if extract_tables:
                    try:
                        tables = page.extract_tables()
                        if tables:
                            for tbl_idx, table_data in enumerate(tables):
                                if not table_data:
                                    continue
                                # 转 markdown 格式
                                tbl_md = _table_to_markdown(table_data)
                                if tbl_md and len(tbl_md) > 10:
                                    # 跨页表头去重：检查表头是否已出现过
                                    tbl_md = _deduplicate_table_header(tbl_md, seen_table_headers)
                                    if not tbl_md:  # 表头已去重，表体为空则跳过
                                        continue
                                    sections.append(
                                        PdfSection(
                                            text=tbl_md,
                                            pos=f"p{page_num}",
                                            is_table=True,
                                            table_str=tbl_md,
                                            page_num=page_num,
                                        )
                                    )
                    except Exception as tbl_err:
                        logger.debug("PDF 表格提取失败 [%s p%d]: %s", pdf_path, page_num, tbl_err)

                # ── 提取文本块 ────────────────────────────────────────────
                try:
                    chars = page.chars
                except Exception:
                    chars = []

                if not chars:
                    continue

                # 按 top 分组（同一行内的字符）
                lines = _group_chars_by_line(chars, page_height)

                for line_text, (x0, top, bottom) in lines:
                    line_text = _clean_text(line_text)
                    if not line_text or len(line_text) < 2:
                        continue

                    # 过滤页眉页脚
                    if _is_header_footer(line_text, page_width, page_height, x0, top, bottom):
                        continue

                    # 判断是否为标题（字体大小异常，或以特定模式开头）
                    is_title = _detect_title(line_text, page_width, x0)
                    pos = f"p{page_num}" + ("(title)" if is_title else "")

                    sections.append(
                        PdfSection(
                            text=line_text,
                            pos=pos,
                            page_num=page_num,
                        )
                    )

    except Exception as e:
        logger.error("PDF 解析失败 [%s]: %s", pdf_path, e)

    return sections


def _group_chars_by_line(
    chars: list[dict],
    page_height: float,
    y_tolerance: float = 5.0,
) -> list[tuple[str, tuple[float, float, float]]]:
    """
    将字符按阅读顺序（从上到下、从左到右）分组为行。

    参考 RAGFlow _text_merge：按 y 坐标分行，按 x 坐标排序。
    返回：(line_text, (x0_min, top_min, bottom_max))
    """
    if not chars:
        return []

    # 按 top 坐标排序（从上到下）
    sorted_chars = sorted(chars, key=lambda c: (round(c.get("top", 0) / y_tolerance) * y_tolerance, c.get("x0", 0)))

    lines: dict[int, list[dict]] = {}
    for ch in sorted_chars:
        top = ch.get("top", 0)
        # 找最近的行分组
        row_key = round(top / y_tolerance) * y_tolerance
        if row_key not in lines:
            lines[row_key] = []
        lines[row_key].append(ch)

    result: list[tuple[str, tuple[float, float, float]]] = []
    for row_key in sorted(lines.keys()):
        row_chars = sorted(lines[row_key], key=lambda c: c.get("x0", 0))
        line_text = "".join(c.get("text", "") for c in row_chars)
        x0_min = min(c.get("x0", 0) for c in row_chars) if row_chars else 0
        top_min = min(c.get("top", 0) for c in row_chars)
        bottom_max = max(c.get("bottom", 0) for c in row_chars)
        result.append((line_text, (x0_min, top_min, bottom_max)))

    return result


def _detect_title(text: str, page_width: float, x0: float) -> bool:
    """
    标题检测：Markdown 标记 / 数字编号 / 居中短文本。

    K15 修复：原居中判断用 abs(x0 - center) 不准确，因为 x0 是文本左边界。
    改进：如果文本左边界接近页面中间且文本较短，认为是居中标题。
    """
    text = text.strip()
    if not text:
        return False

    # 太长不可能是标题
    if len(text) > 200:
        return False

    # 以 Markdown 标题标记开头
    if re.match(r"^#{1,6}\s+", text):
        return True

    # 以数字编号章节开头，如 "1. ", "1.1 ", "第一章"
    if re.match(r"^\d+[\.、]\s", text) or re.match(r"^[一二三四五六七八九十]+[、\.]\s", text):
        return True

    # 居中判断：文本左边界在页面中间附近（容忍 20% 偏移）
    # 注意：x0 是文本块左边界，不是文本中心，所以容忍度需要更大
    if page_width > 0:
        page_width / 2
        # 文本左边界在页面宽度的 30%-70% 之间，认为是居中
        left_ratio = x0 / page_width
        if 0.30 <= left_ratio <= 0.70 and len(text) < 80:
            return True

    return False


# ── 表格转 Markdown ────────────────────────────────────────────────────────


def _deduplicate_table_header(table_md: str, seen_headers: set[str]) -> str:
    """
    跨页表格表头去重。

    pdfplumber 在跨页表格时每页都返回表头，需要去重。
    策略：第一页记录表头，后续页表头与已记录表头相同则移除。
    """
    lines = table_md.strip().split("\n")
    if len(lines) < 2:
        return table_md

    # 提取表头行（第一行）
    header_line = lines[0]
    header_key = header_line.strip().lower()

    if header_key in seen_headers:
        # 表头已出现过，移除第一行（表头）和第二行（分隔线）
        if len(lines) > 2:
            return "\n".join(lines[2:])
        return ""
    else:
        # 首次出现，记录表头
        seen_headers.add(header_key)
        return table_md


def _table_to_markdown(table_data: list[list[str | None]]) -> str:
    """
    将 pdfplumber 表格数据转换为 Markdown 格式。

    参考 RAGFlow：保留表格结构，便于后续 naive_merge 分块时识别。
    """
    if not table_data:
        return ""

    rows = []
    for row in table_data:
        # 清理单元格
        cells = []
        for cell in row:
            cell_text = (cell or "").strip()
            cell_text = re.sub(r"\s+", " ", cell_text)
            cells.append(cell_text)
        # 过滤全空行
        if any(c for c in cells):
            rows.append(cells)

    if not rows:
        return ""

    # 生成 Markdown 表格
    md_lines = []
    for i, row in enumerate(rows):
        # 转义管道符
        escaped_row = [cell.replace("|", "\\|") for cell in row]
        md_lines.append("| " + " | ".join(escaped_row) + " |")
        # 第二行：分隔线
        if i == 0 and len(rows) > 1:
            sep = "| " + " | ".join(["---"] * len(row)) + " |"
            md_lines.append(sep)

    return "\n".join(md_lines)


# ── 主入口 ─────────────────────────────────────────────────────────────────


def extract_text_from_pdf(
    pdf_path: str,
    max_pages: int = 1000,
) -> str:
    """
    提取 PDF 文本，参考 RAGFlow chunk() 的 naive_merge 策略。

    流程：
    1. extract_pdf_sections → list[PdfSection]（保留表格结构）
    2. sections 转为 (text, pos) 元组列表
    3. 由调用方用 chunker.chunk_by_token 做最终分块

    表格以 Markdown 格式嵌入 text 中，保留行结构。
    """
    sections = extract_pdf_sections(pdf_path, max_pages=max_pages, extract_tables=True)

    if not sections:
        return ""

    # 按阅读顺序拼接，表格用空行包裹以示区分
    parts: list[str] = []
    for sec in sections:
        if sec.is_table:
            parts.append(f"\n{sec.table_str}\n")
        else:
            parts.append(sec.text)

    return "\n\n".join(parts)
