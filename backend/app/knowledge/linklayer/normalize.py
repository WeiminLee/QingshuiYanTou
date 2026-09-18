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


async def ensure_keyword(session, layer: str, norm_text: str, *, source: str) -> str:
    """幂等确保 keyword 存在，返回最终应有链接归属的 keyword_id。

    - subject/dimension/stage 层调用前应已完成归一化，直接 active。
    - scope 层允许未知 surface form 直接建条目（recall 优先），status="candidate"，
      由词表治理流程审核后转 active（LLM 提议、词典裁决）。
    - 若目标已处于 merged 状态，链接归属其后继（merged_into），治理不产生孤儿链接。
    """
    keyword_id = make_keyword_id(layer, norm_text)
    status = "candidate" if (layer == "scope" and source == "llm") else "active"
    stmt = pg_insert(Keyword).values(
        keyword_id=keyword_id, layer=layer, norm_text=norm_text,
        display_text=norm_text, status=status,
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
