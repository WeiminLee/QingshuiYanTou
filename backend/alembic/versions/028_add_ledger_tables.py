"""add ledger tables (observations / findings / watermarks)

Revision ID: 028
Revises: 027
Create Date: 2026-09-18
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "028"
down_revision: Union[str, Sequence[str], None] = "027"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "observations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("obs_id", sa.String(32), nullable=False),
        sa.Column("subject_ts_code", sa.Text(), nullable=False),
        sa.Column("subject_name", sa.Text(), nullable=False),
        sa.Column("dimension", sa.Text(), nullable=False),
        sa.Column("dimension_scope", sa.Text(), nullable=True),
        sa.Column("stage_raw", sa.Text(), nullable=True),
        sa.Column("stage_level", sa.Integer(), nullable=True),
        sa.Column("metric_value", postgresql.JSONB(), nullable=True),
        sa.Column("evidence_id", sa.Text(), nullable=False),
        sa.Column("span_start", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("span_end", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("event_date", sa.Date(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("written_by", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="candidate"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("obs_id", name="uq_observations_obs_id"),
    )
    op.create_index(
        "idx_observations_subject", "observations", ["subject_ts_code", "dimension", "dimension_scope"]
    )
    op.create_index("idx_observations_evidence", "observations", ["evidence_id"])

    op.create_table(
        "findings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("finding_id", sa.String(32), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("subject_ts_code", sa.Text(), nullable=False),
        sa.Column("dimension", sa.Text(), nullable=False),
        sa.Column("dimension_scope", sa.Text(), nullable=True),
        sa.Column("from_state", postgresql.JSONB(), nullable=True),
        sa.Column("to_state", postgresql.JSONB(), nullable=True),
        sa.Column("delta", postgresql.JSONB(), nullable=True),
        sa.Column(
            "supports",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "contradicts",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("judgment", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="candidate"),
        sa.Column("supersedes", sa.String(32), nullable=True),
        sa.Column("created_by", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("finding_id", name="uq_findings_finding_id"),
    )
    op.create_index("idx_findings_subject", "findings", ["subject_ts_code", "dimension"])

    op.create_table(
        "watermarks",
        sa.Column("subject_ts_code", sa.Text(), primary_key=True),
        sa.Column("dimension", sa.Text(), primary_key=True),
        # 哨兵空串替代 NULL：复合主键不接受 NULL，且 NULL 不参与 ON CONFLICT 匹配
        sa.Column("dimension_scope", sa.Text(), primary_key=True, nullable=False, server_default=""),
        sa.Column("max_level", sa.Integer(), nullable=True),
        sa.Column("max_value", postgresql.JSONB(), nullable=True),
        sa.Column("first_reached_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_updated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("watermarks")
    op.drop_index("idx_findings_subject", table_name="findings")
    op.drop_table("findings")
    op.drop_index("idx_observations_evidence", table_name="observations")
    op.drop_index("idx_observations_subject", table_name="observations")
    op.drop_table("observations")
