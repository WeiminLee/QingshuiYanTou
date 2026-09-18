# backend/app/knowledge/linklayer/models.py
"""链接层模型：keyword（受控词表）+ link（evidence↔keyword 双向引用）。"""
from __future__ import annotations

import hashlib
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.database import Base


def make_keyword_id(layer: str, norm_text: str) -> str:
    """由 (layer, norm_text) 确定性生成 keyword_id，形如 KW:<16位十六进制>。"""
    return "KW:" + hashlib.sha256(f"{layer}:{norm_text}".encode("utf-8")).hexdigest()[:16]


class Keyword(Base):
    """受控词表条目。layer ∈ subject | dimension | stage | scope；status ∈ active | candidate | merged | retired"""

    __tablename__ = "link_keywords"
    __table_args__ = (UniqueConstraint("layer", "norm_text", name="uq_link_keywords_layer_norm"),)

    keyword_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    layer: Mapped[str] = mapped_column(String(16), nullable=False)
    norm_text: Mapped[str] = mapped_column(Text, nullable=False)
    display_text: Mapped[str | None] = mapped_column(Text)
    aliases: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="active")
    merged_into: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Link(Base):
    """evidence ↔ keyword 关联（双向引用的物化）。幂等：PK(keyword_id, evidence_id, span_start)。"""

    __tablename__ = "link_links"
    __table_args__ = (
        Index("idx_link_links_evidence", "evidence_id"),
        Index("idx_link_links_keyword_date", "keyword_id", "published_at"),
    )

    keyword_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("link_keywords.keyword_id"), primary_key=True
    )
    evidence_id: Mapped[str] = mapped_column(Text, primary_key=True)
    span_start: Mapped[int] = mapped_column(Integer, primary_key=True)
    span_end: Mapped[int] = mapped_column(Integer)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(String(16), nullable=False)  # llm | dictionary
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
