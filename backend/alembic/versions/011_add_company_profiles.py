"""add_company_profiles

Revision ID: 011_add_company_profiles
Revises: 010_expand_announcement_fields
Create Date: 2026-04-05
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers
revision = "011_add_company_profiles"
down_revision = "010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "company_profiles",
        sa.Column("ts_code", sa.String(20), primary_key=True),
        sa.Column("com_name", sa.String(200), nullable=True),
        sa.Column("com_id", sa.String(50), nullable=True),
        sa.Column("chairman", sa.String(100), nullable=True),
        sa.Column("manager", sa.String(100), nullable=True),
        sa.Column("secretary", sa.String(100), nullable=True),
        sa.Column("reg_capital", sa.String(100), nullable=True),
        sa.Column("setup_date", sa.String(50), nullable=True),
        sa.Column("province", sa.String(50), nullable=True),
        sa.Column("city", sa.String(50), nullable=True),
        sa.Column("introduction", sa.Text, nullable=True),
        sa.Column("website", sa.String(200), nullable=True),
        sa.Column("email", sa.String(200), nullable=True),
        sa.Column("office", sa.Text, nullable=True),
        sa.Column("business_scope", sa.Text, nullable=True),
        sa.Column("employees", sa.Integer, nullable=True),
        sa.Column("main_business", sa.Text, nullable=True),
        sa.Column("exchange", sa.String(10), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_table("company_profiles")
