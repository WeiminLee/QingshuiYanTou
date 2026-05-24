"""add ingestion jobs queue

Revision ID: 022
Revises: 021
Create Date: 2026-05-23
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "022"
down_revision: Union[str, Sequence[str], None] = "021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ingestion_jobs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("job_type", sa.String(50), nullable=False),
        sa.Column("job_key", sa.String(200), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column(
            "payload",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
        sa.Column(
            "next_run_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.String(100), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("result_summary", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_unique_constraint(
        "uq_ingestion_jobs_type_key",
        "ingestion_jobs",
        ["job_type", "job_key"],
    )
    op.create_index(
        "idx_ingestion_jobs_claim",
        "ingestion_jobs",
        ["status", "next_run_at", "priority", "id"],
    )
    op.create_index("idx_ingestion_jobs_type_status", "ingestion_jobs", ["job_type", "status"])
    op.create_index("idx_ingestion_jobs_locked_at", "ingestion_jobs", ["locked_at"])


def downgrade() -> None:
    op.drop_index("idx_ingestion_jobs_locked_at", table_name="ingestion_jobs")
    op.drop_index("idx_ingestion_jobs_type_status", table_name="ingestion_jobs")
    op.drop_index("idx_ingestion_jobs_claim", table_name="ingestion_jobs")
    op.drop_constraint("uq_ingestion_jobs_type_key", "ingestion_jobs", type_="unique")
    op.drop_table("ingestion_jobs")
