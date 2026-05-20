"""新增：涨停概念每日汇总表及明细表

Revision ID: 004_add_concept_limit_tables
Revises: 003
Create Date: 2026-04-03
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import Index

revision = '004'
down_revision = '003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 涨停概念每日汇总
    op.create_table(
        'concept_limit',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('concept_code', sa.String(20), nullable=False, comment='概念代码'),
        sa.Column('concept_name', sa.String(100), nullable=False, comment='概念名称'),
        sa.Column('trade_date', sa.Date(), nullable=False, comment='交易日期'),
        sa.Column('days', sa.Integer(), comment='连板天数'),
        sa.Column('up_stat', sa.String(50), comment='涨停状态描述'),
        sa.Column('cons_nums', sa.Integer(), comment='成分股数'),
        sa.Column('up_nums', sa.Integer(), comment='涨停股票数'),
        sa.Column('pct_chg', sa.Float(), comment='概念涨跌幅(%)'),
        sa.Column('rank', sa.Integer(), comment='当日排名'),
    )
    op.create_index(
        'idx_concept_limit_unique',
        'concept_limit',
        ['concept_code', 'trade_date'],
        unique=True,
    )
    op.create_index('idx_concept_limit_date', 'concept_limit', ['trade_date'])

    # 涨停概念内个股明细（limit_cpt_list 返回的 ts_code/name 字段）
    op.create_table(
        'concept_limit_detail',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('concept_code', sa.String(20), nullable=False, comment='概念代码'),
        sa.Column('concept_name', sa.String(100), nullable=False, comment='概念名称'),
        sa.Column('ts_code', sa.String(20), nullable=False, comment='股票代码'),
        sa.Column('stock_name', sa.String(50), comment='股票名称'),
        sa.Column('trade_date', sa.Date(), nullable=False, comment='交易日期'),
    )
    op.create_index(
        'idx_concept_limit_detail_unique',
        'concept_limit_detail',
        ['concept_code', 'ts_code', 'trade_date'],
        unique=True,
    )
    op.create_index('idx_concept_limit_detail_date', 'concept_limit_detail', ['trade_date'])


def downgrade() -> None:
    op.drop_table('concept_limit_detail')
    op.drop_table('concept_limit')
