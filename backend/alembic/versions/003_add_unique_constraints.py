"""新增：daily_basic 和 index_daily 唯一约束（支持 on_conflict_do_nothing）

Revision ID: 003_add_unique_constraints
Revises: 002
Create Date: 2026-04-03
"""
from alembic import op

revision = '003'
down_revision = '002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # daily_basic: ts_code+trade_date 唯一约束（替换原普通索引）
    op.drop_index('idx_daily_basic_ts_date', 'daily_basic', if_exists=True)
    op.create_index(
        'idx_daily_basic_ts_date',
        'daily_basic',
        ['ts_code', 'trade_date'],
        unique=True,
    )
    # index_daily: ts_code+trade_date 唯一约束（替换原普通索引）
    op.drop_index('idx_index_daily_ts_date', 'index_daily', if_exists=True)
    op.create_index(
        'idx_index_daily_ts_date',
        'index_daily',
        ['ts_code', 'trade_date'],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index('idx_index_daily_ts_date', 'index_daily')
    op.drop_index('idx_daily_basic_ts_date', 'daily_basic')
