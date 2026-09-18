"""add link layer tables (link_keywords / link_links)

Revision ID: 027
Revises: 026
Create Date: 2026-09-18
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "027"
down_revision: Union[str, Sequence[str], None] = "026"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "link_keywords",
        sa.Column("keyword_id", sa.String(32), primary_key=True),
        sa.Column("layer", sa.String(16), nullable=False),
        sa.Column("norm_text", sa.Text(), nullable=False),
        sa.Column("display_text", sa.Text(), nullable=True),
        sa.Column(
            "aliases",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("merged_into", sa.String(32), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("layer", "norm_text", name="uq_link_keywords_layer_norm"),
    )
    op.create_table(
        "link_links",
        sa.Column(
            "keyword_id",
            sa.String(32),
            sa.ForeignKey("link_keywords.keyword_id"),
            primary_key=True,
        ),
        sa.Column("evidence_id", sa.Text(), primary_key=True),
        sa.Column("span_start", sa.Integer(), primary_key=True),
        sa.Column("span_end", sa.Integer(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("idx_link_links_evidence", "link_links", ["evidence_id"])
    op.create_index("idx_link_links_keyword_date", "link_links", ["keyword_id", "published_at"])


def downgrade() -> None:
    op.drop_index("idx_link_links_keyword_date", table_name="link_links")
    op.drop_index("idx_link_links_evidence", table_name="link_links")
    op.drop_table("link_links")
    op.drop_table("link_keywords")
