from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.database import Base


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    content: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="cls")
    url: Mapped[str | None] = mapped_column(Text)
    publish_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, nullable=False, server_default="{}")


Index("idx_events_publish_at", Event.publish_at, postgresql_using="btree")
Index("idx_events_source", Event.source, postgresql_using="btree")
Index("idx_events_tags", Event.metadata_, postgresql_using="gin", postgresql_ops={"metadata": "jsonb_path_ops"})
