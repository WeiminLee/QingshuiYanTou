"""
研报关键词过滤模块

根据研报标题判断是否属于产业链相关报告，只保存产业链报告。
"""
from __future__ import annotations

# ── 文档类型常量 ────────────────────────────────────────────────
DOC_TYPE_SAVE = "save"
DOC_TYPE_SKIP = "skip"


# ── 产业链关键词分类表 ───────────────────────────────────────────
# 更具体的关键词必须排在更通用的之前，避免被截胡。
TITLE_CLASSIFICATION: dict[str, tuple[str, str]] = {
    # ── 产业链 / 供应链（最核心） ───────────────────────────
    "产业链":         ("industry_chain",  DOC_TYPE_SAVE),
    "供应链":         ("industry_chain",  DOC_TYPE_SAVE),
    "产业供应链":     ("industry_chain",  DOC_TYPE_SAVE),
    "上下游":         ("industry_chain",  DOC_TYPE_SAVE),
    "产业链研究":     ("industry_chain",  DOC_TYPE_SAVE),
    "供应链研究":     ("industry_chain",  DOC_TYPE_SAVE),
    "产业链深度":     ("industry_chain",  DOC_TYPE_SAVE),
    "供应链专题":     ("industry_chain",  DOC_TYPE_SAVE),

    # ── 行业报告 ───────────────────────────────────────────
    "行业报告":       ("industry",        DOC_TYPE_SAVE),
    "行业深度":      ("industry",        DOC_TYPE_SAVE),
    "行业专题":      ("industry",        DOC_TYPE_SAVE),
    "行业研究":      ("industry",        DOC_TYPE_SAVE),
    "行业策略":      ("industry",        DOC_TYPE_SAVE),
    "行业跟踪":      ("industry",        DOC_TYPE_SAVE),
    "行业动态":      ("industry",        DOC_TYPE_SAVE),
    "行业点评":      ("industry",        DOC_TYPE_SAVE),
    "行业周报":      ("industry",        DOC_TYPE_SAVE),
    "行业月报":      ("industry",        DOC_TYPE_SAVE),
    "行业季报":      ("industry",        DOC_TYPE_SAVE),
    "行业年报":      ("industry",        DOC_TYPE_SAVE),
    "行业综述":      ("industry",        DOC_TYPE_SAVE),
    "行业分析":      ("industry",        DOC_TYPE_SAVE),
    "行业趋势":      ("industry",        DOC_TYPE_SAVE),
    "行业展望":      ("industry",        DOC_TYPE_SAVE),
    "行业概览":      ("industry",        DOC_TYPE_SAVE),
    "行业图谱":      ("industry",        DOC_TYPE_SAVE),
    "行业地图":      ("industry",        DOC_TYPE_SAVE),

    # ── 产业研究报告 ────────────────────────────────────────
    "产业报告":       ("industry",        DOC_TYPE_SAVE),
    "产业研究":      ("industry",        DOC_TYPE_SAVE),
    "产业深度":      ("industry",        DOC_TYPE_SAVE),
    "产业专题":      ("industry",        DOC_TYPE_SAVE),
    "产业分析":      ("industry",        DOC_TYPE_SAVE),
    "产业趋势":      ("industry",        DOC_TYPE_SAVE),

    # ── 大宗商品 / 原材料 ──────────────────────────────────
    "大宗商品":       ("commodity",       DOC_TYPE_SAVE),
    "原材料":        ("commodity",       DOC_TYPE_SAVE),

    # ── 专题 / 深度报告 ───────────────────────────────────
    "专题报告":       ("special_topic",  DOC_TYPE_SAVE),
    "深度报告":       ("special_topic",  DOC_TYPE_SAVE),
    "深度研究":       ("special_topic",  DOC_TYPE_SAVE),
    "专题研究":       ("special_topic",  DOC_TYPE_SAVE),
}


def classify_title(title: str) -> tuple[str, str]:
    """根据研报标题返回 ``(doc_type, action)``

    Args:
        title: 研报标题

    Returns:
        元组 ``(doc_type, action)``：
        - ``doc_type``: 业务分类标签（``industry_chain``, ``industry``, ``commodity``, ``special_topic``, ``other``, ``unknown``）
        - ``action``: ``DOC_TYPE_SAVE`` / ``DOC_TYPE_SKIP``
    """
    if not title:
        return ("unknown", DOC_TYPE_SKIP)

    for keyword, (doc_type, action) in TITLE_CLASSIFICATION.items():
        if keyword in title:
            return (doc_type, action)

    return ("other", DOC_TYPE_SKIP)


def should_save(title: str) -> bool:
    """判断该研报是否需要保存（产业链相关）。

    Returns:
        ``True`` 当且仅当 ``classify_title`` 返回的 action 为 ``DOC_TYPE_SAVE``
    """
    _, action = classify_title(title)
    return action == DOC_TYPE_SAVE


def get_doc_type(title: str) -> str:
    """获取研报的业务分类标签"""
    doc_type, _ = classify_title(title)
    return doc_type


__all__ = [
    "DOC_TYPE_SKIP",
    "DOC_TYPE_SAVE",
    "TITLE_CLASSIFICATION",
    "classify_title",
    "get_doc_type",
    "should_save",
]