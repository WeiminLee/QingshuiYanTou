"""
研报关键词过滤模块

根据研报标题判断是否属于产业链相关报告，只保存产业链报告。
"""
from __future__ import annotations

# ── 文档类型常量 ────────────────────────────────────────────────
DOC_TYPE_SAVE = "save"
DOC_TYPE_SKIP = "skip"


# ── 产业链 / 供应链（最核心） ───────────────────────────
TITLE_CLASSIFICATION: dict[str, tuple[str, str]] = {
    # ── 产业链 / 供应链 ────────────────────────────────
    "产业链":         ("industry_chain",  DOC_TYPE_SAVE),
    "供应链":         ("industry_chain",  DOC_TYPE_SAVE),
    "上下游":         ("industry_chain",  DOC_TYPE_SAVE),

    # ── 行业报告（细分先于通用） ─────────────────────
    "行业深度":      ("industry",        DOC_TYPE_SAVE),
    "行业报告":       ("industry",        DOC_TYPE_SAVE),
    "行业跟踪":      ("industry",        DOC_TYPE_SAVE),
    "行业动态":      ("industry",        DOC_TYPE_SAVE),
    "行业专题":      ("industry",        DOC_TYPE_SAVE),
    "行业月报":      ("industry",        DOC_TYPE_SAVE),
    "行业周报":      ("industry",        DOC_TYPE_SAVE),
    "行业季报":      ("industry",        DOC_TYPE_SAVE),
    "行业策略":      ("industry",        DOC_TYPE_SAVE),
    "行业研究":      ("industry",        DOC_TYPE_SAVE),
    "行业分析":      ("industry",        DOC_TYPE_SAVE),
    "行业点评":      ("industry",        DOC_TYPE_SAVE),
    "行业趋势":      ("industry",        DOC_TYPE_SAVE),
    "行业展望":      ("industry",        DOC_TYPE_SAVE),
    "行业图谱":      ("industry",        DOC_TYPE_SAVE),

    # ── 产业报告 ────────────────────────────────────
    "产业报告":       ("industry",        DOC_TYPE_SAVE),
    "产业研究":      ("industry",        DOC_TYPE_SAVE),
    "产业深度":      ("industry",        DOC_TYPE_SAVE),
    "产业专题":      ("industry",        DOC_TYPE_SAVE),

    # ── 大宗商品 ────────────────────────────────────
    "碳酸锂":         ("commodity",       DOC_TYPE_SAVE),
    "黄金":           ("commodity",       DOC_TYPE_SAVE),
    "原油":           ("commodity",       DOC_TYPE_SAVE),
    "大宗商品":       ("commodity",       DOC_TYPE_SAVE),
    "铜":             ("commodity",       DOC_TYPE_SAVE),
    "铝":             ("commodity",       DOC_TYPE_SAVE),
    "锂":             ("commodity",       DOC_TYPE_SAVE),
    "稀土":           ("commodity",       DOC_TYPE_SAVE),
    "煤炭":           ("commodity",       DOC_TYPE_SAVE),
    "钢铁":           ("commodity",       DOC_TYPE_SAVE),
    "水泥":           ("commodity",       DOC_TYPE_SAVE),
    "玻璃":           ("commodity",       DOC_TYPE_SAVE),

    # ── 宏观 / 债券 ──────────────────────────────────
    "宏观":           ("macro",           DOC_TYPE_SAVE),
    "利率":           ("macro",           DOC_TYPE_SAVE),
    "流动性":         ("macro",           DOC_TYPE_SAVE),
    "社融":           ("macro",           DOC_TYPE_SAVE),
    "通胀":           ("macro",           DOC_TYPE_SAVE),
    "CPI":            ("macro",           DOC_TYPE_SAVE),
    "PPI":            ("macro",           DOC_TYPE_SAVE),
    "固收":           ("macro",           DOC_TYPE_SAVE),
    "债券":           ("macro",           DOC_TYPE_SAVE),
    "货币政策":       ("macro",           DOC_TYPE_SAVE),
    "财政":           ("macro",           DOC_TYPE_SAVE),
    "外贸":           ("macro",           DOC_TYPE_SAVE),

    # ── 专题 / 深度报告 ───────────────────────────────
    "专题":           ("special_topic",  DOC_TYPE_SAVE),
    "深度报告":       ("special_topic",  DOC_TYPE_SAVE),
    "深度研究":       ("special_topic",  DOC_TYPE_SAVE),

    # ── 公司研报 ─────────────────────────────────────
    # 首次覆盖 / 深度覆盖（公司级别）
    "首次覆盖":       ("company",         DOC_TYPE_SAVE),
    "深度覆盖":       ("company",         DOC_TYPE_SAVE),
    "公司跟踪":       ("company",         DOC_TYPE_SAVE),
    "公司研究":       ("company",         DOC_TYPE_SAVE),
    "公司动态":       ("company",         DOC_TYPE_SAVE),
    "公司信息":       ("company",         DOC_TYPE_SAVE),
    # 季报/年报/半年报点评
    "一季报":         ("company",         DOC_TYPE_SAVE),
    "半年报":         ("company",         DOC_TYPE_SAVE),
    "三季报":         ("company",         DOC_TYPE_SAVE),
    "年报":           ("company",         DOC_TYPE_SAVE),
    "业绩预告":       ("company",         DOC_TYPE_SAVE),
    "业绩快报":       ("company",         DOC_TYPE_SAVE),
    "业绩点评":       ("company",         DOC_TYPE_SAVE),
    # 其他常见公司研报
    "公司点评":       ("company",         DOC_TYPE_SAVE),
    "公司深度":       ("company",         DOC_TYPE_SAVE),
    "事件点评":       ("company",         DOC_TYPE_SAVE),
    "重大事项":       ("company",         DOC_TYPE_SAVE),
    "股权激励":       ("company",         DOC_TYPE_SAVE),
    "收购":           ("company",         DOC_TYPE_SAVE),
    "并购":           ("company",         DOC_TYPE_SAVE),
    "调研":           ("company",         DOC_TYPE_SAVE),
    "股东大会":       ("company",         DOC_TYPE_SAVE),
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