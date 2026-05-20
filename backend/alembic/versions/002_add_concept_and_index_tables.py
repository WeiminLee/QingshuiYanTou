"""新增：概念板块、指数日线、每日基本面表

Revision ID: 002_add_concept_and_index_tables
Revises: 001_init_tables
Create Date: 2026-04-03
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import Index

revision = '002'
down_revision = '001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 概念板块表
    op.create_table(
        'concepts',
        sa.Column('code', sa.String(20), primary_key=True, comment='概念代码'),
        sa.Column('name', sa.String(100), nullable=False, comment='概念名称'),
        sa.Column('src', sa.String(20), comment='来源'),
    )

    # 个股-概念映射表
    op.create_table(
        'stock_concepts',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('ts_code', sa.String(20), nullable=False, comment='股票代码'),
        sa.Column('concept_code', sa.String(20), nullable=False, comment='概念代码'),
    )
    op.create_index(
        'idx_stock_concepts_unique',
        'stock_concepts',
        ['ts_code', 'concept_code'],
        unique=True,
    )
    op.create_index('idx_stock_concepts_concept', 'stock_concepts', ['concept_code'])

    # 指数日线表（HS300等）
    op.create_table(
        'index_daily',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('ts_code', sa.String(20), nullable=False, comment='指数代码'),
        sa.Column('trade_date', sa.Date(), nullable=False, comment='交易日期'),
        sa.Column('open', sa.Float(), comment='开盘价'),
        sa.Column('high', sa.Float(), comment='最高价'),
        sa.Column('low', sa.Float(), comment='最低价'),
        sa.Column('close', sa.Float(), comment='收盘价'),
        sa.Column('pre_close', sa.Float(), comment='前收盘价'),
        sa.Column('change', sa.Float(), comment='涨跌额'),
        sa.Column('pct_chg', sa.Float(), comment='涨跌幅'),
        sa.Column('vol', sa.Float(), comment='成交量'),
        sa.Column('amount', sa.Float(), comment='成交额'),
    )
    op.create_index('idx_index_daily_ts_date', 'index_daily', ['ts_code', 'trade_date'])

    # 每日基本面表（PE/PB/换手率等）
    op.create_table(
        'daily_basic',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('ts_code', sa.String(20), nullable=False, comment='股票代码'),
        sa.Column('trade_date', sa.Date(), nullable=False, comment='交易日期'),
        sa.Column('close', sa.Float(), comment='收盘价'),
        sa.Column('turnover_rate', sa.Float(), comment='换手率(%)'),
        sa.Column('turnover_rate_f', sa.Float(), comment='自由流通股换手率(%)'),
        sa.Column('volume_ratio', sa.Float(), comment='量比'),
        sa.Column('pe', sa.Float(), comment='市盈率'),
        sa.Column('pe_ttm', sa.Float(), comment='滚动市盈率'),
        sa.Column('pb', sa.Float(), comment='市净率'),
        sa.Column('ps', sa.Float(), comment='市销率'),
        sa.Column('ps_ttm', sa.Float(), comment='滚动市销率'),
        sa.Column('dv_ratio', sa.Float(), comment='股息率(%)'),
        sa.Column('dv_ttm', sa.Float(), comment='滚动股息率(%)'),
        sa.Column('total_share', sa.Float(), comment='总股本(万股)'),
        sa.Column('float_share', sa.Float(), comment='流通股本(万股)'),
        sa.Column('free_share', sa.Float(), comment='自由流通股本(万股)'),
        sa.Column('total_mv', sa.Float(), comment='总市值(万元)'),
        sa.Column('circ_mv', sa.Float(), comment='流通市值(万元)'),
    )
    op.create_index('idx_daily_basic_ts_date', 'daily_basic', ['ts_code', 'trade_date'])


def downgrade() -> None:
    op.drop_table('daily_basic')
    op.drop_table('index_daily')
    op.drop_table('stock_concepts')
    op.drop_table('concepts')
