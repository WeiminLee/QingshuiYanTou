"""
互动易（IRM）关键词过滤模块

根据问答内容判断是否属于有价值的信息，只保存产业链相关、公司业绩相关的问题。
"""

from __future__ import annotations

# ── 文档类型常量 ────────────────────────────────────────────────
DOC_TYPE_SAVE = "save"
DOC_TYPE_SKIP = "skip"


# ── 高价值关键词（命中即保存）───────────────────────────────────

# 产业链 / 供应链相关
INDUSTRY_CHAIN_KEYWORDS = [
    "产业链",
    "供应链",
    "上下游",
    "供应端",
    "需求端",
    "供应商",
    "采购",
    "销售渠道",
    "经销商",
    "代理商",
]

# 行业 / 产业相关
INDUSTRY_KEYWORDS = [
    "行业",
    "产业",
    "市场份额",
    "市场占有率",
    "竞争格局",
    "竞争对手",
    "竞争态势",
    "行业地位",
]

# 大宗商品 / 原材料
COMMODITY_KEYWORDS = [
    "碳酸锂",
    "锂",
    "钴",
    "镍",
    "铜",
    "铝",
    "稀土",
    "煤炭",
    "钢铁",
    "水泥",
    "玻璃",
    "大宗商品",
    "原材料",
    "原料",
    "黄金",
    "白银",
    "原油",
    "石油",
    "天然气",
    "价格",
    "涨价",
    "跌价",
    "成本",
]

# 业绩 / 财务相关
FINANCIAL_KEYWORDS = [
    "业绩",
    "营收",
    "收入",
    "利润",
    "净利润",
    "毛利率",
    "ROE",
    "EPS",
    "每股收益",
    "股价",
    "市值",
    "估值",
    "PE",
    "PB",
    "股息",
    "分红",
    "派息",
    "送股",
    "转增",
    "资产负债",
    "负债率",
    "现金流",
    "应收账款",
    "季报",
    "半年报",
    "年报",
    "三季报",
    "一季报",
    "业绩预告",
    "业绩快报",
    "业绩预告",
    "业绩公告",
    "营收",
    "营业额",
    "销售额",
    "订单",
    "在手订单",
]

# 产能 / 产量 / 扩产相关
PRODUCTION_KEYWORDS = [
    "产能",
    "产量",
    "扩产",
    "扩建",
    "投产",
    "量产",
    "开工率",
    "产能利用率",
    "利用率",
    "满产",
    "生产线",
    "工厂",
    "基地",
    "园区",
    "项目",
    "新产能",
    "新增产能",
    "规划产能",
]

# 研发 / 技术相关
TECH_KEYWORDS = [
    "研发",
    "技术",
    "专利",
    "研发投入",
    "研发费用",
    "新产品",
    "新业务",
    "技术创新",
    "核心优势",
]

# 重大事项
MAJOR_EVENT_KEYWORDS = [
    "并购",
    "收购",
    "重组",
    "定增",
    "配股",
    "股权激励",
    "期权",
    "限制性股票",
    "战略",
    "合作",
    "投资",
    "项目",
    "海外",
    "出口",
    "进口",
    "海外业务",
]

# ── 低价值关键词（命中即跳过）───────────────────────────────────

# 无关痛痒的问题
LOW_VALUE_KEYWORDS = [
    "请问",
    "你好",
    "请问一下",
    "请问董秘",
    "您好",
    "谢谢",
    "感谢",
    "辛苦了",
    "打扰了",
    "冒昧打扰",
    "请问贵公司",
    "能否告知",
    "能否介绍",
]

# 投资者关系管理无关的问题
IRRELEVANT_KEYWORDS = [
    "股价",
    "股票",
    "市值",  # 太泛，不单独作为过滤条件
    "建议",
    "希望",
    "希望公司",
    "希望管理层",
]


# ── 分类逻辑 ──────────────────────────────────────────────────────

TITLE_CLASSIFICATION: dict[str, tuple[str, str]] = {}


def _build_classification():
    """动态构建分类字典"""
    result = {}

    for kw in INDUSTRY_CHAIN_KEYWORDS:
        result[kw] = ("industry_chain", DOC_TYPE_SAVE)

    for kw in INDUSTRY_KEYWORDS:
        result[kw] = ("industry", DOC_TYPE_SAVE)

    for kw in COMMODITY_KEYWORDS:
        result[kw] = ("commodity", DOC_TYPE_SAVE)

    for kw in FINANCIAL_KEYWORDS:
        result[kw] = ("financial", DOC_TYPE_SAVE)

    for kw in PRODUCTION_KEYWORDS:
        result[kw] = ("production", DOC_TYPE_SAVE)

    for kw in TECH_KEYWORDS:
        result[kw] = ("technology", DOC_TYPE_SAVE)

    for kw in MAJOR_EVENT_KEYWORDS:
        result[kw] = ("major_event", DOC_TYPE_SAVE)

    return result


TITLE_CLASSIFICATION = _build_classification()


def classify_content(question: str, answer: str = "") -> tuple[str, str]:
    """根据问答内容返回 ``(doc_type, action)``

    Args:
        question: 提问内容
        answer: 回答内容（可选）

    Returns:
        元组 ``(doc_type, action)``：
        - ``doc_type``: 业务分类标签
        - ``action``: ``DOC_TYPE_SAVE`` / ``DOC_TYPE_SKIP``
    """
    if not question:
        return ("unknown", DOC_TYPE_SKIP)

    # 合并问答内容进行匹配
    content = f"{question} {answer}"

    # 检查高价值关键词
    for keyword, (doc_type, action) in TITLE_CLASSIFICATION.items():
        if keyword in content:
            return (doc_type, action)

    # 检查低价值模式
    # 1. 纯问候语（问句很短且包含问候词）
    if len(question) < 20:
        for kw in LOW_VALUE_KEYWORDS:
            if kw in question:
                # 需要同时检查是否有实质性内容
                has_substance = any(k in content for k in ["业绩", "产能", "产品", "销售", "市场"])
                if not has_substance:
                    return ("low_value", DOC_TYPE_SKIP)

    # 2. 纯咨询性问题（没有实质性业务内容）
    substance_indicators = [
        "业绩",
        "收入",
        "利润",
        "产能",
        "产品",
        "销售",
        "市场",
        "客户",
        "供应商",
        "成本",
        "毛利率",
        "订单",
        "项目",
        "研发",
        "技术",
        "行业",
        "竞争",
    ]
    has_substance = any(ind in content for ind in substance_indicators)
    if not has_substance:
        return ("low_value", DOC_TYPE_SKIP)

    return ("other", DOC_TYPE_SKIP)


def should_save(question: str, answer: str = "") -> bool:
    """判断该问答是否需要保存。

    Returns:
        ``True`` 当且仅当 ``classify_content`` 返回的 action 为 ``DOC_TYPE_SAVE``
    """
    _, action = classify_content(question, answer)
    return action == DOC_TYPE_SAVE


def get_doc_type(question: str, answer: str = "") -> str:
    """获取问答的业务分类标签"""
    doc_type, _ = classify_content(question, answer)
    return doc_type


__all__ = [
    "DOC_TYPE_SKIP",
    "DOC_TYPE_SAVE",
    "INDUSTRY_CHAIN_KEYWORDS",
    "INDUSTRY_KEYWORDS",
    "COMMODITY_KEYWORDS",
    "FINANCIAL_KEYWORDS",
    "PRODUCTION_KEYWORDS",
    "TECH_KEYWORDS",
    "MAJOR_EVENT_KEYWORDS",
    "LOW_VALUE_KEYWORDS",
    "classify_content",
    "get_doc_type",
    "should_save",
]
