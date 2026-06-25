"""add events table (财联社新闻事件库)

Revision ID: 024
Revises: 023
Create Date: 2026-06-25
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "024"
down_revision: Union[str, Sequence[str], None] = "023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.String(32), unique=True, nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("source", sa.String(32), nullable=False, server_default="cls"),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("publish_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("ingested_at", postgresql.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
    )
    op.create_index("idx_events_publish_at", "events", ["publish_at"])
    op.create_index("idx_events_source", "events", ["source"])
    op.create_index(
        "idx_events_tags", "events", ["metadata"],
        postgresql_using="gin",
        postgresql_ops={"metadata": "jsonb_path_ops"},
    )


def downgrade() -> None:
    op.drop_index("idx_events_tags", table_name="events")
    op.drop_index("idx_events_source", table_name="events")
    op.drop_index("idx_events_publish_at", table_name="events")
    op.drop_table("events")
