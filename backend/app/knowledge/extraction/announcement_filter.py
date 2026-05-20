"""
公告 PDF 两级过滤引擎（文件级 + 章节级）

两级过滤流程：
  PDF 文件
    ├─ 文件级过滤：文件名 Skip / 内容 Skip → 整个文件跳过
    └─ 章节级过滤：解析章节，KEEP/SKIP 判断，只抽取实质章节

依赖：pdfplumber（纯规则，无 LLM 调用）
"""
import os
import re
from dataclasses import dataclass, field
from typing import Literal

import pdfplumber

# ── 文件级正则 ────────────────────────────────────────────────────────────────

_RE_STOCK_CODE = re.compile(r"证券代码[：:]\d+")
_RE_NOTICE_CODE = re.compile(r"公告编号[：:][\u4e00-\u9fa5]-?\d+号?")
_RE_TOC = re.compile(r"目\s{1,3}录")
_RE_LEGAL_CLAUSE = re.compile(
    r"第[一二三四五六七八九十百零\d]+\s*条[是为据依按及其和之的]*"
    r"(规定|说明|要求|意见)?"
)
_RE_AMOUNT = re.compile(r"\d+[万千百]元|\d+\.\d+[亿万]?元|\d+亿美元|\d+万美元")
_RE_SUBSTANTIVE_KW = re.compile(
    r"发行股份|购买资产|募集配套资金|股权|收购|重组|"
    r"交易对方|标的资产|业绩|盈利|净利润|营业收入|资产总额|资产净额"
)

# ── 文件名级 Skip ──────────────────────────────────────────────────────────────

SKIP_TITLE_KW = [
    "管理制度", "管理办法", "工作细则", "工作规程",
    "审计报告", "审计意见", "内部控制评价", "内部控制审计",
    "业绩说明会纪要", "续租办公楼", "金融服务协议",
    "内幕信息知情人", "员工持股计划", "股权激励计划",
    "信息披露管理制度", "信息披露暂缓与豁免管理制度",
    "外部信息使用人管理制度",
    "董事局审计委员会",   # 治理委员会工作规程
]

# ── 章节级关键词 ────────────────────────────────────────────────────────────────

# 公告：噪音章节（标题含这些 → SKIP）
SKIP_CHAPTER_KW = [
    "会计师事务所",    # 审计程序模板
    "其他相关说明",   # 通用模板
    "特此公告", "敬请", "广大投资者",   # 结尾声明
    "风险因素", "防范投资风险", "投资风险",   # 通用风险免责
    "独立董事",       # 法律意见模板
    "内部控制",       # 治理
    "累计投票", "网络投票",   # 治理程序
    "信息披露", "暂缓", "豁免",   # 信息披露
    "募集资金",       # 募资使用（模板类）
]

# 公告：实质性章节（标题含这些 → KEEP）
KEEP_CHAPTER_KW = [
    "业绩", "变动原因", "变动说明",   # 业绩相关
    "本次交易", "重组", "收购", "发行股份", "交易对方", "交易标的", "交易概述",   # 并购重组
    "中标", "合同", "订单", "协议",   # 商业合同
    "股权", "标的资产", "出资", "增资", "参股",   # 股权
    "备考财务", "财务数据",   # 财务数据
    "业务", "产品", "市场", "盈利", "营收",   # 业务实质
    "投资者关系",   # 投资者交流记录，含核心业务信息
]

# 研报：噪音章节
SKIP_CHAPTER_KW_REPORT = [
    "免责声明", "法律声明", "评级说明", "估值方法",
    "附录", "数据来源",
]

# 研报：实质性章节
KEEP_CHAPTER_KW_REPORT = [
    "宏观", "行业", "公司", "业务", "产品",
    "盈利预测", "竞争优势", "护城河", "市场份额",
    "风险提示", "投资评级", "目标价", "估值",
]


# ── 数据结构 ───────────────────────────────────────────────────────────────────

@dataclass
class FilterResult:
    decision: Literal["process", "skip"]
    file_reason: str = ""          # 文件级 skip 原因
    sections_kept: int = 0         # 保留章节数
    sections_skipped: int = 0      # 跳过章节数
    kept_chapters: list[str] = field(default_factory=list)   # 保留的章节标题
    detail: str = ""


# ── PDF 读取 ───────────────────────────────────────────────────────────────────

def _read_first_pages(path: str, n_pages: int = 5) -> list[str]:
    """读取 PDF 前 n 页文本"""
    texts = []
    try:
        with pdfplumber.open(path) as pdf:
            total = min(n_pages, len(pdf.pages))
            for page in pdf.pages[:total]:
                t = page.extract_text() or ""
                if t.strip():
                    texts.append(t.strip())
    except Exception:
        pass
    return texts


# ── 章节解析 ───────────────────────────────────────────────────────────────────

# H1：一、二、三... + 顿号/逗号 后接标题
_H1_PAT = re.compile(r"^([一二三四五六七八九十零]+)[、，,](.+)$", re.MULTILINE)
# H2：（一）（二）（三）...
_H2_PAT = re.compile(r"^（([一二三四五六七八九十]+)）")


def _parse_sections(text: str) -> list[dict]:
    """
    解析章节结构。

    规则：
    - H1（一、二...）触发新章节
    - H2/H3 子章节跟随最近 H1，不独立判断

    Returns:
        [{'level': 1, 'title': '...', 'body': '...', 'h1_idx': int}, ...]
    """
    lines = text.split("\n")
    sections = []
    current_h1_idx = None

    for i, line in enumerate(lines):
        raw = line.strip()
        h1_m = _H1_PAT.match(raw)
        h2_m = _H2_PAT.match(raw)

        if h1_m:
            # 截取 body：当前行之后到下一个 H1/H2 之前
            body_lines = []
            for j in range(i + 1, min(i + 50, len(lines))):
                if _H1_PAT.match(lines[j].strip()) or _H2_PAT.match(lines[j].strip()):
                    break
                body_lines.append(lines[j])
            sections.append({
                "level": 1,
                "title": raw,
                "body": "\n".join(body_lines),
                "h1_idx": len(sections),
            })
            current_h1_idx = len(sections) - 1

        elif h2_m and current_h1_idx is not None:
            sections.append({
                "level": 2,
                "title": raw,
                "parent_idx": current_h1_idx,
            })

    return sections


# ── 章节分类 ───────────────────────────────────────────────────────────────────

def _classify_title(title: str) -> Literal["keep", "skip"]:
    """
    基于完整标题判断章节类型。

    优先级：
    1. 标题含 SKIP_KW → skip
    2. 标题含 KEEP_KW → keep
    3. 否则 → skip
    """
    for kw in SKIP_CHAPTER_KW:
        if kw in title:
            return "skip"
    for kw in KEEP_CHAPTER_KW:
        if kw in title:
            return "keep"
    return "skip"


def _classify_with_inheritance(
    sections: list[dict],
    is_announcement: bool,
) -> list[dict]:
    """
    对章节列表分类，H2/H3 继承 H1 结果。

    正文兜底：H1 标记 skip，但正文含实质性关键词 → keep。
    """
    kw_skip = SKIP_CHAPTER_KW if is_announcement else SKIP_CHAPTER_KW_REPORT
    kw_keep = KEEP_CHAPTER_KW if is_announcement else KEEP_CHAPTER_KW_REPORT
    result = []
    h1_class: Literal["keep", "skip"] | None = None

    for sec in sections:
        if sec["level"] == 1:
            # 判断 H1
            title = sec["title"]
            h1_class = _classify_title(title)
            # 正文兜底 override
            if h1_class == "skip" and _RE_SUBSTANTIVE_KW.search(sec.get("body", "")):
                h1_class = "keep"
            result.append({**sec, "_class": h1_class})
        else:
            # H2 跟随 H1；正文含实质性关键词可 override
            inherited = h1_class or "skip"
            body = sec.get("body", "")
            if inherited == "skip" and body and _RE_SUBSTANTIVE_KW.search(body):
                inherited = "keep"
            result.append({**sec, "_class": inherited})

    return result


# ── 主过滤函数 ─────────────────────────────────────────────────────────────────

def filter_announcement_pdf(
    file_path: str,
    is_announcement: bool = True,
) -> FilterResult:
    """
    两级过滤：文件级 + 章节级。

    Returns:
        FilterResult(decision="process", ...)
        FilterResult(decision="skip", file_reason=...)   # 文件级跳过
    """
    fname = os.path.basename(file_path)

    # ── 一级：文件级过滤 ────────────────────────────────────────────────────

    for kw in SKIP_TITLE_KW:
        if kw in fname:
            return FilterResult("skip", f"filename:{kw}")

    short_texts = _read_first_pages(file_path, n_pages=2)
    if not short_texts:
        return FilterResult("skip", "empty_pdf")

    short_combined = " ".join(short_texts)

    if _RE_TOC.search(short_combined):
        return FilterResult("skip", "toc")

    # ── 二级：章节级过滤（所有 PDF 必经）─────────────────────────────────────

    all_texts = _read_first_pages(file_path, n_pages=5)
    if not all_texts:
        return FilterResult("skip", "empty_pdf")

    full_text = "\n".join(all_texts)
    sections = _parse_sections(full_text)

    if not sections:
        # 无法解析章节 → 检查文件名/标题是否含实质性关键词
        if _RE_STOCK_CODE.search(short_combined) or _RE_AMOUNT.search(short_combined):
            return FilterResult("process", "no_sections",
                              detail="无可解析章节，全量抽取（标准格式/含金额）")
        if "投资者关系" in fname:
            return FilterResult("process", "no_sections",
                              detail="投资者关系记录表，全量抽取")
        return FilterResult("skip", "no_sections")

    classified = _classify_with_inheritance(sections, is_announcement)

    kept = [s for s in classified if s["_class"] == "keep"]
    if not kept:
        return FilterResult("skip", "no_substantive_sections",
                            detail=f"无可保留章节（{len(sections)}个章节全跳）")

    return FilterResult(
        decision="process",
        file_reason="section_filtered",
        sections_kept=len(kept),
        sections_skipped=len(sections) - len(kept),
        kept_chapters=[s["title"] for s in kept],
    )


def extract_filtered_text(
    file_path: str,
    is_announcement: bool = True,
) -> str:
    """
    返回过滤后的文本（只含实质章节的标题+正文）。

    若文件应整体跳过，返回空字符串。
    """
    fr = filter_announcement_pdf(file_path, is_announcement)
    if fr.decision == "skip":
        return ""

    all_texts = _read_first_pages(file_path, n_pages=5)
    if not all_texts:
        return ""

    full_text = "\n".join(all_texts)
    sections = _parse_sections(full_text)
    if not sections:
        return full_text  # fallback：全量

    classified = _classify_with_inheritance(sections, is_announcement)

    kept_parts = []
    for sec in classified:
        if sec["_class"] == "keep":
            kept_parts.append(sec["title"])
            body = sec.get("body", "")
            if body:
                kept_parts.append(body)

    return "\n\n".join(kept_parts)
