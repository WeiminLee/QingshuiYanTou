"""add account tables (users, portfolio_positions)

Revision ID: 023
Revises: 022
Create Date: 2026-06-25
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "023"
down_revision: Union[str, Sequence[str], None] = "022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("user_id", sa.String(64), primary_key=True),
        sa.Column("display_name", sa.String(128), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    op.create_table(
        "portfolio_positions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(64), sa.ForeignKey("users.user_id"), nullable=False),
        sa.Column("ts_code", sa.String(16), nullable=False),
        sa.Column("stock_name", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("user_id", "ts_code", name="uq_portfolio_user_ts_code"),
    )
    op.create_index(
        "ix_portfolio_positions_user_id",
        "portfolio_positions",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_portfolio_positions_user_id", table_name="portfolio_positions")
    op.drop_table("portfolio_positions")
    op.drop_table("users")
