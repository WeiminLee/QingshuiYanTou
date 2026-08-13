"""
互动易（IRM）关键词过滤模块

根据问答内容判断是否属于有价值的信息，只保存有实质回答的产业链、公司业务相关问题。

改进说明（2026-08-11）：
1. 增加回答质量检查：模板回答（"感谢您的关注"）、空回答直接跳过
2. 股东人数类问题：只有回答包含具体数字时才保留
3. 纯问候/建议类问题收紧：短问题+模板问候模式直接跳过
4. 回答内容纳入过滤：不再只看问题关键词
"""

from __future__ import annotations

import re

# ── 文档类型常量 ────────────────────────────────────────────────
DOC_TYPE_SAVE = "save"
DOC_TYPE_SKIP = "skip"


# ── 回答质量相关 ──────────────────────────────────────────────────

# 模板回答模式（命中即跳过，因为不含实质信息）
ANSWER_TEMPLATE_PATTERNS = [
    "感谢您的关注",
    "谢谢您的关注",
    "感谢您对公司的关注",
    "感谢您对公司的关注和支持",
    "感谢您的关注和支持",
    "感谢您的关注和建议",
    "感谢您的关注，谢谢",
    "感谢您的关注！",
    "感谢您的关注。",
]

# 回答长度阈值
ANSWER_MIN_LENGTH = 15  # 回答少于15个字符视为无实质内容

# 股东人数类问题——只有回答包含具体数字时才保留
SHAREHOLDER_COUNT_KEYWORDS = [
    "股东人数",
    "股东户数",
    "股东数量",
    "股东总户数",
    "股东总数",
]


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
# 注意：不包含"股价""市值"——这类通常由股民问"为什么跌"，价值不高，在低价值检测中处理
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
    "业绩公告",
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
    # 注意："投资"太宽泛（"投资者""理性投资"等都会命中），移至SUBSTANCE_KEYWORDS
    "项目",
    "海外",
    "出口",
    "进口",
    "海外业务",
]

# 行业/技术细分关键词（针对候选池：半导体/CPO/机器人/锂电池/新材料/航天/军工）
INDUSTRY_TECH_KEYWORDS = [
    # 半导体/芯片
    "芯片", "半导体", "晶圆", "封装", "制程", "光刻", "刻蚀",
    "SiC", "GaN", "IGBT", "MOSFET", "功率器件", "功率半导体",
    "第三代半导体", "化合物半导体", "模拟芯片", "MCU", "FPGA",
    "ASIC", "EDA", "IP核", "先进封装", "Chiplet", "SiP",
    "半导体设备", "半导体材料", "光刻机",
    "HBM", "存储芯片", "逻辑芯片", "SoC", "CIS",
    # CPO/光通信
    "光模块", "光通信", "CPO", "硅光", "相干", "DSP",
    "800G", "1.6T", "高速光模块", "光芯片", "激光器", "探测器",
    "WDM", "波分复用", "光连接", "光互连",
    # 机器人
    "机器人", "人形机器人", "具身智能", "灵巧手",
    "减速器", "谐波", "RV减速器", "伺服", "伺服电机",
    "编码器", "力矩传感器", "六维力", "传感器",
    "执行器", "关节", "电机", "无框力矩", "空心杯",
    "滚珠丝杠", "行星滚柱丝杠", "丝杠",
    "运动控制", "机器视觉", "SLAM",
    # 锂电池/新能源
    "电池", "固态电池", "钠离子", "钠电池",
    "正极材料", "负极材料", "电解液", "隔膜",
    "磷酸铁锂", "磷酸锰铁锂", "三元材料", "前驱体",
    "复合集流体", "PET铜箔", "铜箔",
    "能量密度", "快充", "超充", "BMS", "热管理",
    "CTP", "CTC", "刀片电池", "4680",
    # 新材料
    "新材料", "复合材料", "碳纤维", "陶瓷基",
    "高温合金", "钛合金", "镁合金", "超导",
    "石墨烯", "碳纳米管", "纳米材料",
    "特种材料", "功能材料", "涂层",
    # 航天/军工
    "航天", "卫星", "火箭", "低轨", "星链",
    "星间链路", "遥感", "导航", "北斗", "雷达", "相控阵",
    "红外", "夜视", "制导", "惯性导航",
    "陀螺", "加速度计", "MEMS", "MEMS传感器",
    "军品", "军工", "导弹", "无人机", "舰船",
    "装甲", "火控", "电子对抗", "电磁",
    "SAR", "电子战", "数据链",
    # AI/算力
    "AI", "大模型", "算力", "算法", "深度学习",
    "训练", "推理", "GPU", "NPU", "AI芯片",
    "多模态", "AIGC", "生成式AI", "LLM",
    "大语言模型", "Transformer", "神经网络",
    # 智能驾驶/低空经济
    "自动驾驶", "智能驾驶", "无人驾驶",
    "低空经济", "eVTOL", "飞行汽车",
]

# ── 低价值关键词（命中即跳过）───────────────────────────────────

# 无关痛痒的问题（用于辅助判断，不再单独跳过）
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

# 投资者关系管理无关的问题（低价值，用于二次过滤）
IRRELEVANT_KEYWORDS = [
    "股价",
    "股票",
    "市值",
    "建议",
    "希望",
    "希望公司",
    "希望管理层",
    "涨停",
    "跌停",
    "拉升",
    "炒作",
    "庄家",
    "主力",
    "利好",
    "利空",
]


# ── 实质内容关键词（用于判断问题是否包含具体业务信息）───────────

SUBSTANCE_KEYWORDS = [
    # 业绩/财务
    "业绩", "收入", "利润", "净利润", "营收", "毛利率", "ROE",
    "订单", "在手订单", "现金流", "分红", "股息",
    # 产能/生产
    "产能", "产量", "投产", "量产", "扩产", "开工率", "生产线",
    # 产品/市场
    "产品", "销售", "市场", "客户", "供应商", "渠道",
    "份额", "市占率", "竞争", "行业", "产业",
    # 产业链
    "产业链", "供应链", "上下游",
    # 研发/技术
    "研发", "技术", "专利", "新产品", "新技术",
    "芯片", "半导体", "AI", "大模型", "机器人", "电池",
    # 成本/价格（业务层面，非纯股价）
    "成本", "价格", "原材料",
    # 重大事项
    "并购", "收购", "重组", "定增", "股权激励",
    "合作", "项目", "战略", "海外", "出口",
    # 业务通用
    "业务", "布局", "进展", "规划", "目标",
]


# ── 数字模式（用于判断股东人数等回答是否包含实际数据）───────────

_DIGIT_PATTERN = re.compile(r"\d+")


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

    for kw in INDUSTRY_TECH_KEYWORDS:
        result[kw] = ("industry_tech", DOC_TYPE_SAVE)

    return result


TITLE_CLASSIFICATION = _build_classification()


def _is_template_answer(answer: str) -> bool:
    """判断回答是否为模板回复（不含实质信息）"""
    if not answer:
        return True
    answer = answer.strip()
    for pattern in ANSWER_TEMPLATE_PATTERNS:
        if pattern in answer:
            # 模板回答中若包含实质业务关键词（如具体数字、产能、产品等），仍保留
            has_substance = any(kw in answer for kw in [
                "产能", "产量", "产品", "业务", "研发", "技术",
                "订单", "客户", "项目", "合作", "投资",
            ])
            if has_substance:
                return False
            return True
    return False


def _is_shareholder_count_question(question: str) -> bool:
    """判断是否是股东人数类问题"""
    for kw in SHAREHOLDER_COUNT_KEYWORDS:
        if kw in question:
            return True
    return False


def _has_digit(answer: str) -> bool:
    """判断回答是否包含数字（用于股东人数等需要具体数字的场景）"""
    return bool(_DIGIT_PATTERN.search(answer))


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

    question = question.strip()
    answer = (answer or "").strip()

    # ── 第一阶段：回答质量检查 ──

    # 1. 空回答/回答为None → 跳过
    if not answer or answer in ("None", "nan", ""):
        return ("empty_answer", DOC_TYPE_SKIP)

    # 2. 回答太短 (< 15字符) → 跳过
    if len(answer) < ANSWER_MIN_LENGTH:
        return ("short_answer", DOC_TYPE_SKIP)

    # 3. 股东人数类问题：只有回答包含具体数字时才保留
    #    注意：此检测必须在模板回答检测之前，因为很多股东人数回答也包含"感谢您的关注"
    if _is_shareholder_count_question(question):
        if not _has_digit(answer):
            return ("shareholder_no_data", DOC_TYPE_SKIP)
        return ("shareholder_count", DOC_TYPE_SAVE)

    # 4. 模板回答检测（如"感谢您的关注"）
    if _is_template_answer(answer):
        return ("template_answer", DOC_TYPE_SKIP)

    # ── 第二阶段：问题内容评估 ──

    # 合并问答内容进行关键词匹配
    content = f"{question} {answer}"

    # 检查高价值关键词
    for keyword, (doc_type, action) in TITLE_CLASSIFICATION.items():
        if keyword in content:
            return (doc_type, action)

    # ═══ 低价值模式检测 ═══

    has_substance = any(kw in content for kw in SUBSTANCE_KEYWORDS)

    # 1. 纯问候/请问类（问题短且只有礼貌用语，无实质内容）
    #    放宽到 < 40 字，因为很多模板问题是"请问贵公司是否有XX业务？"
    if len(question) < 40:
        greeting_count = sum(1 for kw in LOW_VALUE_KEYWORDS if kw in question)
        if greeting_count >= 2:
            # 双重问候语命中（如"请问"+"您好"）且无实质内容 → 跳过
            if not has_substance:
                return ("pure_greeting", DOC_TYPE_SKIP)

    # 2. 纯股价/市值/涨跌类问题（只有 IRRELEVANT_KEYWORDS，无实质性业务内容）
    has_irrelevant = any(kw in content for kw in IRRELEVANT_KEYWORDS)
    if has_irrelevant and not has_substance:
        return ("low_value_irrelevant", DOC_TYPE_SKIP)

    # 3. 纯建议类问题（"建议公司..."），无实质业务内容
    if "建议" in question and not has_substance:
        return ("pure_suggestion", DOC_TYPE_SKIP)

    # 4. 纯咨询性问题（没有实质性业务内容）
    if not has_substance:
        return ("low_value", DOC_TYPE_SKIP)

    return ("other", DOC_TYPE_SAVE)


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
    "DOC_TYPE_SAVE",
    "DOC_TYPE_SKIP",
    "ANSWER_TEMPLATE_PATTERNS",
    "ANSWER_MIN_LENGTH",
    "SHAREHOLDER_COUNT_KEYWORDS",
    "INDUSTRY_CHAIN_KEYWORDS",
    "INDUSTRY_KEYWORDS",
    "COMMODITY_KEYWORDS",
    "FINANCIAL_KEYWORDS",
    "PRODUCTION_KEYWORDS",
    "TECH_KEYWORDS",
    "MAJOR_EVENT_KEYWORDS",
    "INDUSTRY_TECH_KEYWORDS",
    "LOW_VALUE_KEYWORDS",
    "IRRELEVANT_KEYWORDS",
    "SUBSTANCE_KEYWORDS",
    "classify_content",
    "get_doc_type",
    "should_save",
    "_is_template_answer",
    "_is_shareholder_count_question",
    "_has_digit",
]