"""add ingestion progress tracking

Revision ID: 021
Revises: 020
Create Date: 2026-05-17
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "021"
down_revision: Union[str, Sequence[str], None] = "020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ingestion_runs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("task_name", sa.String(100), nullable=False),
        sa.Column("scope", sa.String(100), nullable=False, server_default="default"),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("from_watermark", sa.String(50), nullable=True),
        sa.Column("to_watermark", sa.String(50), nullable=True),
        sa.Column("current_watermark", sa.String(50), nullable=True),
        sa.Column("current_page", sa.Integer(), nullable=True),
        sa.Column("total_pages", sa.Integer(), nullable=True),
        sa.Column("total_items", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("processed_items", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("success_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("downloaded_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fail_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_item_id", sa.String(100), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
    )
    op.create_unique_constraint("uq_ingestion_runs_run_id", "ingestion_runs", ["run_id"])
    op.create_index("idx_ingestion_runs_source_scope", "ingestion_runs", ["source", "scope"])
    op.create_index("idx_ingestion_runs_status", "ingestion_runs", ["status"])
    op.create_index("idx_ingestion_runs_started_at", "ingestion_runs", ["started_at"])

    op.create_table(
        "ingestion_progress_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("task_name", sa.String(100), nullable=False),
        sa.Column("scope", sa.String(100), nullable=False, server_default="default"),
        sa.Column("stage", sa.String(50), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("current_page", sa.Integer(), nullable=True),
        sa.Column("total_pages", sa.Integer(), nullable=True),
        sa.Column("total_items", sa.Integer(), nullable=True),
        sa.Column("processed_items", sa.Integer(), nullable=True),
        sa.Column("success_count", sa.Integer(), nullable=True),
        sa.Column("skipped_count", sa.Integer(), nullable=True),
        sa.Column("downloaded_count", sa.Integer(), nullable=True),
        sa.Column("fail_count", sa.Integer(), nullable=True),
        sa.Column("item_id", sa.String(100), nullable=True),
        sa.Column("item_title", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_ingestion_events_run_id", "ingestion_progress_events", ["run_id"])
    op.create_index("idx_ingestion_events_source_scope", "ingestion_progress_events", ["source", "scope"])
    op.create_index("idx_ingestion_events_created_at", "ingestion_progress_events", ["created_at"])

    op.create_table(
        "ingestion_checkpoints",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("task_name", sa.String(100), nullable=False),
        sa.Column("scope", sa.String(100), nullable=False, server_default="default"),
        sa.Column("watermark_type", sa.String(30), nullable=False, server_default="date"),
        sa.Column("last_success_watermark", sa.String(50), nullable=True),
        sa.Column("last_attempt_watermark", sa.String(50), nullable=True),
        sa.Column("last_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("last_status", sa.String(20), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_from_watermark", sa.String(50), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_unique_constraint(
        "uq_ingestion_checkpoints_source_scope",
        "ingestion_checkpoints",
        ["source", "task_name", "scope"],
    )
    op.create_index("idx_ingestion_checkpoints_source", "ingestion_checkpoints", ["source"])


def downgrade() -> None:
    op.drop_index("idx_ingestion_checkpoints_source", table_name="ingestion_checkpoints")
    op.drop_constraint("uq_ingestion_checkpoints_source_scope", "ingestion_checkpoints", type_="unique")
    op.drop_table("ingestion_checkpoints")
    op.drop_index("idx_ingestion_events_created_at", table_name="ingestion_progress_events")
    op.drop_index("idx_ingestion_events_source_scope", table_name="ingestion_progress_events")
    op.drop_index("idx_ingestion_events_run_id", table_name="ingestion_progress_events")
    op.drop_table("ingestion_progress_events")
    op.drop_index("idx_ingestion_runs_started_at", table_name="ingestion_runs")
    op.drop_index("idx_ingestion_runs_status", table_name="ingestion_runs")
    op.drop_index("idx_ingestion_runs_source_scope", table_name="ingestion_runs")
    op.drop_constraint("uq_ingestion_runs_run_id", "ingestion_runs", type_="unique")
    op.drop_table("ingestion_runs")
