"""
添加概念评分和个股评分表

Revision ID: 012
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

revision = '012_add_score_tables'
down_revision = '011_add_company_profiles'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # concept_scores 表
    op.create_table(
        'concept_scores',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('concept_ts_code', sa.String(20), nullable=False, comment='THS概念代码'),
        sa.Column('name', sa.String(100), comment='概念名称'),
        sa.Column('score', sa.Float(), comment='综合评分 0-100'),
        sa.Column('momentum_5d', sa.Float(), comment='5日动量'),
        sa.Column('momentum_1d', sa.Float(), comment='当日涨幅'),
        sa.Column('breadth', sa.Float(), comment='广度（上涨股数/总股数）'),
        sa.Column('breadth_rising', sa.Integer(), comment='上涨股票数'),
        sa.Column('breadth_total', sa.Integer(), comment='成分股总数'),
        sa.Column('relative_strength', sa.Float(), comment='相对强度（概念涨幅-HS300涨幅）'),
        sa.Column('stock_count', sa.Integer(), comment='成分股数量'),
        sa.Column('trade_date', sa.Date(), nullable=False, comment='计算日期'),
        sa.Column('calculated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('concept_ts_code', 'trade_date', name='uq_concept_score_ts_date'),
    )
    op.create_index('idx_concept_score_trade_date', 'concept_scores', ['trade_date'])
    op.create_index('idx_concept_score_score', 'concept_scores', ['score'])

    # stock_scores 表
    op.create_table(
        'stock_scores',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('ts_code', sa.String(20), nullable=False, comment='股票代码'),
        sa.Column('name', sa.String(50), comment='股票名称'),
        sa.Column('total_score', sa.Float(), comment='总分 0-100'),
        sa.Column('momentum_score', sa.Float(), comment='动量分 0-25'),
        sa.Column('trend_score', sa.Float(), comment='趋势分 0-30'),
        sa.Column('capital_score', sa.Float(), comment='资金面分 0-25'),
        sa.Column('concept_bonus', sa.Float(), comment='概念溢价 0-15'),
        sa.Column('valuation_bonus', sa.Float(), comment='估值加分 0-5'),
        sa.Column('momentum_5d', sa.Float(), comment='近5日累计涨幅'),
        sa.Column('turnover_rate_pct', sa.Float(), comment='换手率'),
        sa.Column('vol_ratio', sa.Float(), comment='量比'),
        sa.Column('ma_state', sa.String(20), comment='均线状态'),
        sa.Column('trade_date', sa.Date(), nullable=False, comment='计算日期'),
        sa.Column('calculated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('ts_code', 'trade_date', name='uq_stock_score_ts_date'),
    )
    op.create_index('idx_stock_score_trade_date', 'stock_scores', ['trade_date'])
    op.create_index('idx_stock_score_total', 'stock_scores', ['total_score'])


def downgrade() -> None:
    op.drop_table('stock_scores')
    op.drop_table('concept_scores')
