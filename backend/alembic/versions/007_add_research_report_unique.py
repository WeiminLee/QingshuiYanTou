"""为 research_report_meta 添加唯一约束

Revision ID: 007
Revises: 006
Create Date: 2026-04-03
"""
from alembic import op

revision = '007'
down_revision = '006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        'idx_rmeta_unique',
        'research_report_meta',
        ['trade_date', 'file_name'],
        unique=True,
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index('idx_rmeta_unique', table_name='research_report_meta')
