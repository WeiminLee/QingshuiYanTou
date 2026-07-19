from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.database import Base


class Signal(Base):
    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    signal_id: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[str] = mapped_column(String(128), nullable=False)
    source_title: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    detected_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    subject_name: Mapped[str] = mapped_column(Text, nullable=False)
    subject_type: Mapped[str] = mapped_column(String(32), nullable=False)
    signal_type: Mapped[str] = mapped_column(String(64), nullable=False)
    polarity: Mapped[str] = mapped_column(String(16), nullable=False)
    strength: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    freshness_score: Mapped[int] = mapped_column(Integer, nullable=False)
    value_score: Mapped[int] = mapped_column(Integer, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_excerpt: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="new")
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())


class SignalPropagation(Base):
    __tablename__ = "signal_propagations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    propagation_id: Mapped[str] = mapped_column(String(48), unique=True, nullable=False)
    signal_id: Mapped[str] = mapped_column(
        String(40),
        ForeignKey("signals.signal_id", ondelete="CASCADE"),
        nullable=False,
    )
    target_name: Mapped[str] = mapped_column(Text, nullable=False)
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    relation_path: Mapped[str] = mapped_column(Text, nullable=False)
    direction: Mapped[str] = mapped_column(String(24), nullable=False)
    impact_horizon: Mapped[str] = mapped_column(String(24), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    reasoning: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_refs: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())


Index("idx_signals_value_score", Signal.value_score, Signal.published_at)
Index("idx_signals_source", Signal.source_type, Signal.source_id)
Index("idx_signals_subject", Signal.subject_type, Signal.subject_name)
Index("idx_signals_status", Signal.status)
Index("idx_signals_metadata_gin", Signal.metadata_, postgresql_using="gin", postgresql_ops={"metadata": "jsonb_path_ops"})
Index("idx_signal_propagations_signal_id", SignalPropagation.signal_id)
Index("idx_signal_propagations_target", SignalPropagation.target_type, SignalPropagation.target_name)
Index("idx_signal_propagations_direction", SignalPropagation.direction)

