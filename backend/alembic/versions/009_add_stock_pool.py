"""新增：stock_pool 表

Revision ID: 009
Revises: 008
Create Date: 2026-04-03
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import Index

revision = '009'
down_revision = '008'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'stock_pool',
        sa.Column('ts_code', sa.String(20), primary_key=True, comment='股票代码'),
        sa.Column('concept_code', sa.String(20), comment='所属强势板块代码（TI格式）'),
        sa.Column('concept_name', sa.String(100), comment='所属强势板块名称'),
        sa.Column('in_date', sa.Date(), nullable=False, comment='纳入日期'),
        sa.Column('out_date', sa.Date(), comment='剔除日期（NULL=仍在池中）'),
        sa.Column('pct_chg_5d', sa.Numeric(8, 2), comment='近5日累计涨幅'),
        sa.Column('score', sa.Numeric(5, 2), comment='综合评分'),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index('idx_pool_in_date', 'stock_pool', ['in_date'])
    op.create_index('idx_pool_out', 'stock_pool', ['out_date'], unique=True, postgresql_where=sa.text('out_date IS NULL'))


def downgrade() -> None:
    op.drop_table('stock_pool')
