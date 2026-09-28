# backend/app/knowledge/linklayer/normalize.py
"""surface form → 规范键。铁律（spec 附录 A #3）：归一化永远机械，LLM 不参与。"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.knowledge.linklayer.dict_match import SubjectIndex
from app.knowledge.linklayer.models import Keyword, make_keyword_id


def canonicalize_subject(surface: str, subject_index: SubjectIndex) -> str | None:
    """公司 surface form → ts_code（上市）或规范全称（非上市）。查不到返回 None。

    两级：精确（ts_code/简称/规范全称）→ 前缀/后缀规则
    （"隆基绿能科技股份有限公司" = 简称"隆基绿能"+注册后缀 → ts_code）。
    """
    return subject_index.canonicalize(surface)


# 标准维度 → 判定词。LLM 的 metric.name 是原文字面串（可能是
# "电源管理芯片毛利率比上年变动" 这类整句），必须机械映射到 YAML 定义的
# 标准维度，否则 dimension 层会被长句淹没（实测曾达 49.9 万条脏词 / 12.4 万条超 20 字）。
_DIMENSION_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("毛利率", ("毛利率", "毛利水平", "毛利润", "毛利")),
    ("营收", ("营业收入", "营收", "销售收入", "营业额")),
    ("净利润", ("净利润", "归母净利", "净利")),
    ("开工率", ("开工率", "产能利用率")),
    ("价格", ("单价", "售价", "均价", "价格")),
    ("产能", ("产能", "产量")),
    ("订单", ("订单", "在手订单", "排产")),
    ("客户认证", ("认证", "客户导入", "送样", "验证")),
    ("产线进展", ("产线", "量产", "投产", "达产", "爬坡", "扩产", "试产")),
)


def canonicalize_dimension(surface: str, known_dimensions: set[str] | None = None) -> str | None:
    """metric surface form → 标准维度名；无法映射返回 None（宁缺毋滥）。

    精确命中已知维度集（YAML）优先；否则按**最长标记优先**匹配——
    避免"产能爬坡"被短标记"产能"抢先命中而丢失"产线进展"语义。
    """
    text = (surface or "").strip()
    if not text:
        return None
    if known_dimensions and text in known_dimensions:
        return text

    # 收集所有命中（dim, marker_len），取标记最长者
    hits: list[tuple[str, int]] = []
    for dim, markers in _DIMENSION_MARKERS:
        if known_dimensions and dim not in known_dimensions:
            continue
        for marker in markers:
            if marker in text:
                hits.append((dim, len(marker)))
    if not hits:
        return None
    # 衍生形态黑名单：占比类表述（"占营业收入比例"/"营收占比"/"某业务比重"）
    # 是别的量对某维度的占比，不是该维度的构成细分；挂在标准维度 parent 下
    # 会稀释 rollup children（实战 [3] top30 一半是占比碎片）。
    # 注意只拦占比类：同比/增长率/合计等衍射维度按既有契约保留 parent
    # （"归母净利润同比"仍归"净利润"，供上卷深挖）。
    if _DERIVED_MARKERS and any(m in text for m in _DERIVED_MARKERS):
        return None
    return max(hits, key=lambda x: x[1])[0]


def canonicalize_period(surface: str | None) -> str:
    """metric period surface → 规范期间标签（机械，报告分口径分组用）。

    解析「2024年1-6月」→ H1 2024；「2025年度」→ FY 2025；「2025年一季度」→ Q1 2025；
    无法解析 → 原样保留（"本报告期"/"报告期内"需结合 evidence 发布日期推断，
    机械层不猜）。"""
    s = (surface or "").strip()
    if not s:
        return ""
    m = re.search(r"(\d{4})\s*年", s)
    year = m.group(1) if m else None
    if not year:
        return s
    if re.search(r"1[-—~至]\s*6|上半年|半年度", s):
        return f"H1 {year}"
    if re.search(r"7[-—~至]\s*12|下半年", s):
        return f"H2 {year}"
    m_q = re.search(r"[第]?\s*([一二三四1234])\s*季度", s)
    if m_q:
        q = {"一": "1", "二": "2", "三": "3", "四": "4"}.get(m_q.group(1), m_q.group(1))
        return f"Q{q} {year}"
    if re.search(r"1[-—~至]\s*3", s):
        return f"Q1 {year}"
    if re.search(r"1[-—~至]\s*9", s):
        return f"Q1-Q3 {year}"
    if re.search(r"年1\s*[-—~至]\s*1[012]", s):  # 1-11月等
        return f"1-11M {year}"
    return f"FY {year}"


# 占比类判定词（机械规则）：出现在 metric surface = 该表述是"别的量对某
# 维度的比值"而非该维度的构成细分，不挂标准维度 parent（词本身保留）。
_DERIVED_MARKERS: tuple[str, ...] = (
    "占营业收入", "营业收入占比", "营收占比", "占比", "比重", "比例",
)


# ── 单位一致性（实战长尾：毛利率表混亿元行 / 营收表混 % 行） ─────────────────
# 按标准维度 parent 分型，值/单位可疑的行只摘 value/unit（link 保留，不收缩）。
_MONEY_UNITS = ("元", "万元", "亿元", "万", "亿", "人民币", "美元", "港元")
_RATIO_UNITS = ("%", "个百分点", "pct", "百分点")

# 标准维度 parent → 单位类型（未列出的维度不校验，开放词表不收缩）
_DIM_UNIT_TYPE: dict[str, str] = {
    "毛利率": "ratio",
    "营收": "money",
    "净利润": "money",
}


def clean_metric_value(value: str | None) -> str | None:
    """value 串去单位尾巴（LLM 常抓 "290亿元" 带"亿元"塞进 value）。"""
    if value is None:
        return None
    v = str(value).strip()
    m = re.search(r"-?\d[\d,.]*", v)
    return m.group(0) if m else v


def enforce_unit(dimension: str | None, unit: str | None) -> bool:
    """值行的 unit 与标准维度 parent 是否同型。未知维度恒 ok。"""
    t = _DIM_UNIT_TYPE.get(dimension or "")
    if not t:
        return True
    u = (unit or "").strip()
    if not u:
        return True  # 无 unit 不判违规（值句主语内常自带"亿元"被 clean 摘出）
    if t == "ratio":
        return any(k in u for k in _RATIO_UNITS)
    if t == "money":
        return not any(k in u for k in _RATIO_UNITS)  # 额型禁止 %
    return True


async def ensure_keyword(
    session, layer: str, norm_text: str, *, source: str, parent: str | None = None
) -> str:
    """幂等确保 keyword 存在，返回最终应有链接归属的 keyword_id。

    - subject/dimension/stage 层调用前应已完成归一化，直接 active。
    - scope 层允许未知 surface form 直接建条目（recall 优先），status="candidate"，
      由词表治理流程审核后转 active（LLM 提议、词典裁决）。
    - 若目标已处于 merged 状态，链接归属其后继（merged_into），治理不产生孤儿链接。
    - parent：开放词表的聚合锚点（细粒度词挂到粗粒度标准词），写入 parent_keyword_id，
      查询时可沿此上卷；不替换 norm_text。
    """
    keyword_id = make_keyword_id(layer, norm_text)
    status = "candidate" if (layer == "scope" and source == "llm") else "active"
    parent_id = make_keyword_id(layer, parent) if parent else None
    stmt = pg_insert(Keyword).values(
        keyword_id=keyword_id, layer=layer, norm_text=norm_text,
        display_text=norm_text, status=status, parent_keyword_id=parent_id,
    ).on_conflict_do_nothing(index_elements=["keyword_id"])
    await session.execute(stmt)

    row = (
        await session.execute(
            select(Keyword.status, Keyword.merged_into).where(Keyword.keyword_id == keyword_id)
        )
    ).first()
    if row is not None and row.status == "merged" and row.merged_into:
        return row.merged_into
    return keyword_id
