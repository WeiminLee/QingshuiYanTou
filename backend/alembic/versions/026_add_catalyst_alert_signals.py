"""add catalyst alert signals

Revision ID: 026
Revises: 025
Create Date: 2026-07-23
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "026"
down_revision: Union[str, Sequence[str], None] = "025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "catalyst_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.String(40), nullable=False, unique=True),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("event_date", sa.Date(), nullable=False),
        sa.Column("event_time", sa.Time(), nullable=True),
        sa.Column("timezone", sa.String(64), nullable=False, server_default="Asia/Shanghai"),
        sa.Column("source_type", sa.String(40), nullable=False),
        sa.Column("source_id", sa.String(128), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("importance", sa.Integer(), nullable=False),
        sa.Column("subjects", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(24), nullable=False, server_default="scheduled"),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", postgresql.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_catalyst_events_event_date", "catalyst_events", ["event_date"])
    op.create_index("idx_catalyst_events_status", "catalyst_events", ["status"])
    op.create_index("idx_catalyst_events_source", "catalyst_events", ["source_type", "source_id"])
    op.create_index(
        "idx_catalyst_events_subjects_gin",
        "catalyst_events",
        ["subjects"],
        postgresql_using="gin",
        postgresql_ops={"subjects": "jsonb_path_ops"},
    )

    op.add_column("signals", sa.Column("signal_kind", sa.String(24), nullable=False, server_default="observed"))
    op.add_column("signals", sa.Column("event_date", sa.Date(), nullable=True))
    op.create_index("idx_signals_kind_value", "signals", ["signal_kind", "value_score", "published_at"])
    op.create_index("idx_signals_event_date", "signals", ["event_date"])


def downgrade() -> None:
    op.drop_index("idx_signals_event_date", table_name="signals")
    op.drop_index("idx_signals_kind_value", table_name="signals")
    op.drop_column("signals", "event_date")
    op.drop_column("signals", "signal_kind")

    op.drop_index("idx_catalyst_events_subjects_gin", table_name="catalyst_events")
    op.drop_index("idx_catalyst_events_source", table_name="catalyst_events")
    op.drop_index("idx_catalyst_events_status", table_name="catalyst_events")
    op.drop_index("idx_catalyst_events_event_date", table_name="catalyst_events")
    op.drop_table("catalyst_events")
