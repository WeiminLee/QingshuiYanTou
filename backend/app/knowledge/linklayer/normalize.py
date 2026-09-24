# backend/app/knowledge/linklayer/normalize.py
"""surface form → 规范键。铁律（spec 附录 A #3）：归一化永远机械，LLM 不参与。"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.knowledge.linklayer.dict_match import SubjectIndex
from app.knowledge.linklayer.models import Keyword, make_keyword_id


def canonicalize_subject(surface: str, subject_index: SubjectIndex) -> str | None:
    """公司 surface form → ts_code（上市）或规范全称（非上市）。查不到返回 None。"""
    return subject_index.alias_to_norm.get(surface)


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
    return max(hits, key=lambda x: x[1])[0]


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
