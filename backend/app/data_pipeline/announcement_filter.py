"""
公告关键词过滤模块

根据公告标题判断是否需要下载 PDF（DOC_TYPE_SAVE）或仅建索引（DOC_TYPE_INDEX/SKIP）。
迁移自 ``data_access_mvp/src/utils/announcement_filter.py``，新增 ``DOC_TYPE_INDEX``
分类常量和补充关键词，与 cninfo 公告主流类型对齐。

Plan: 03-02 (phase 03-cninfoclient)
Decisions referenced: D-02 (启用 PDF 下载，使用关键词过滤逻辑)
"""

from __future__ import annotations

# ── 文档类型常量 ────────────────────────────────────────────────
# DOC_TYPE_SAVE  : 命中关键词，需要下载 PDF 并保存
# DOC_TYPE_SKIP  : 默认值，不下载 PDF，也不建索引（旧行为）
# DOC_TYPE_INDEX : 显式只建索引（保留位，供未来扩展使用，例如非业务类公告）
DOC_TYPE_SAVE = "save"
DOC_TYPE_SKIP = "skip"
DOC_TYPE_INDEX = "index"


# ── 标题关键词分类表 ────────────────────────────────────────────
# 注：dict 按插入顺序遍历（Python 3.7+），命中先匹配的关键词。
# 关键：更具体的关键词必须排在更通用的之前，否则会被截胡。
# 例："半年度报告" 必须先于 "年度报告"，否则 "2024年半年度报告" 会被错误归到 annual_report；
#     同理 "第一季度报告" / "第三季度报告" 必须先于 "季度报告"。
TITLE_CLASSIFICATION: dict[str, tuple[str, str]] = {
    # ── 业绩报告（细分关键词先于泛指） ─────────────────────
    # 半年报相关（必须放在年报之前，避免 "半年度报告" 被 "年度报告" 截胡）
    "半年度业绩预告": ("half_report", DOC_TYPE_SAVE),
    "半年度业绩快报": ("half_report", DOC_TYPE_SAVE),
    "半年度报告": ("half_report", DOC_TYPE_SAVE),
    # 季报相关（具体季度先于泛指）
    "第一季度业绩预告": ("quarter_report", DOC_TYPE_SAVE),
    "第一季度业绩快报": ("quarter_report", DOC_TYPE_SAVE),
    "第一季度报告": ("quarter_report", DOC_TYPE_SAVE),
    "第三季度业绩预告": ("quarter_report", DOC_TYPE_SAVE),
    "第三季度业绩快报": ("quarter_report", DOC_TYPE_SAVE),
    "第三季度报告": ("quarter_report", DOC_TYPE_SAVE),
    "季度业绩预告": ("quarter_report", DOC_TYPE_SAVE),
    "季度业绩快报": ("quarter_report", DOC_TYPE_SAVE),
    "季度报告": ("quarter_report", DOC_TYPE_SAVE),
    # 年报相关（最后匹配，避免吞掉 "半年度报告"）
    "年度业绩预告": ("annual_report", DOC_TYPE_SAVE),
    "年度业绩快报": ("annual_report", DOC_TYPE_SAVE),
    "年度报告": ("annual_report", DOC_TYPE_SAVE),
    # ── 投资者关系 ────────────────────────────────────────
    "投资者关系活动": ("research_survey", DOC_TYPE_SAVE),
    "投资者调研": ("research_survey", DOC_TYPE_SAVE),
    "接待机构调研": ("research_survey", DOC_TYPE_SAVE),
    "路演活动": ("research_survey", DOC_TYPE_SAVE),
    # ── 投资类 ────────────────────────────────────────────
    "重大资产重组": ("ma_activity", DOC_TYPE_SAVE),
    "对外投资": ("investment", DOC_TYPE_SAVE),
    "股权收购": ("investment", DOC_TYPE_SAVE),
    "收购资产": ("investment", DOC_TYPE_SAVE),
    "投资设立": ("investment", DOC_TYPE_SAVE),
    "增资": ("investment", DOC_TYPE_SAVE),
}


def classify_title(title: str) -> tuple[str, str]:
    """根据公告标题返回 ``(doc_type, action)``

    Args:
        title: 公告标题

    Returns:
        元组 ``(doc_type, action)``：
        - ``doc_type``: 业务分类标签（``annual_report``, ``half_report``,
          ``quarter_report``, ``research_survey``, ``ma_activity``,
          ``investment``, ``other``, ``unknown``）
        - ``action``: ``DOC_TYPE_SAVE`` / ``DOC_TYPE_SKIP`` / ``DOC_TYPE_INDEX``
    """
    if not title:
        return ("unknown", DOC_TYPE_SKIP)

    for keyword, (doc_type, action) in TITLE_CLASSIFICATION.items():
        if keyword in title:
            return (doc_type, action)

    # 默认不下载（避免存储压力）；下游若需要建索引可改为 DOC_TYPE_INDEX
    return ("other", DOC_TYPE_SKIP)


def should_download(title: str) -> bool:
    """判断该公告是否需要下载 PDF。

    Returns:
        ``True`` 当且仅当 ``classify_title`` 返回的 action 为 ``DOC_TYPE_SAVE``
    """
    _, action = classify_title(title)
    return action == DOC_TYPE_SAVE


def get_doc_type(title: str) -> str:
    """获取公告的业务分类标签（用作 ``announcements.announcement_type``）"""
    doc_type, _ = classify_title(title)
    return doc_type


__all__ = [
    "DOC_TYPE_INDEX",
    "DOC_TYPE_SAVE",
    "DOC_TYPE_SKIP",
    "TITLE_CLASSIFICATION",
    "classify_title",
    "get_doc_type",
    "should_download",
]
