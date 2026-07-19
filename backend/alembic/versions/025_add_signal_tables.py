"""add signal tables

Revision ID: 025
Revises: 024
Create Date: 2026-07-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "025"
down_revision: Union[str, Sequence[str], None] = "024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "signals",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("signal_id", sa.String(40), nullable=False, unique=True),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("source_id", sa.String(128), nullable=False),
        sa.Column("source_title", sa.Text(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("published_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("detected_at", postgresql.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("subject_name", sa.Text(), nullable=False),
        sa.Column("subject_type", sa.String(32), nullable=False),
        sa.Column("signal_type", sa.String(64), nullable=False),
        sa.Column("polarity", sa.String(16), nullable=False),
        sa.Column("strength", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=False),
        sa.Column("freshness_score", sa.Integer(), nullable=False),
        sa.Column("value_score", sa.Integer(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("evidence_excerpt", sa.Text(), nullable=True),
        sa.Column("status", sa.String(24), nullable=False, server_default="new"),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", postgresql.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_signals_value_score", "signals", ["value_score", "published_at"])
    op.create_index("idx_signals_source", "signals", ["source_type", "source_id"])
    op.create_index("idx_signals_subject", "signals", ["subject_type", "subject_name"])
    op.create_index("idx_signals_status", "signals", ["status"])
    op.create_index(
        "idx_signals_metadata_gin",
        "signals",
        ["metadata"],
        postgresql_using="gin",
        postgresql_ops={"metadata": "jsonb_path_ops"},
    )

    op.create_table(
        "signal_propagations",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("propagation_id", sa.String(48), nullable=False, unique=True),
        sa.Column("signal_id", sa.String(40), sa.ForeignKey("signals.signal_id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_name", sa.Text(), nullable=False),
        sa.Column("target_type", sa.String(32), nullable=False),
        sa.Column("relation_path", sa.Text(), nullable=False),
        sa.Column("direction", sa.String(24), nullable=False),
        sa.Column("impact_horizon", sa.String(24), nullable=False),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=False),
        sa.Column("reasoning", sa.Text(), nullable=False),
        sa.Column("evidence_refs", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_signal_propagations_signal_id", "signal_propagations", ["signal_id"])
    op.create_index("idx_signal_propagations_target", "signal_propagations", ["target_type", "target_name"])
    op.create_index("idx_signal_propagations_direction", "signal_propagations", ["direction"])


def downgrade() -> None:
    op.drop_index("idx_signal_propagations_direction", table_name="signal_propagations")
    op.drop_index("idx_signal_propagations_target", table_name="signal_propagations")
    op.drop_index("idx_signal_propagations_signal_id", table_name="signal_propagations")
    op.drop_table("signal_propagations")
    op.drop_index("idx_signals_metadata_gin", table_name="signals")
    op.drop_index("idx_signals_status", table_name="signals")
    op.drop_index("idx_signals_subject", table_name="signals")
    op.drop_index("idx_signals_source", table_name="signals")
    op.drop_index("idx_signals_value_score", table_name="signals")
    op.drop_table("signals")

