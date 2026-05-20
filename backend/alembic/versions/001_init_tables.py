"""init tables

Revision ID: 001
Revises:
Create Date: 2026-04-02

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # stocks 表
    op.create_table(
        'stocks',
        sa.Column('ts_code', sa.String(20), primary_key=True, comment='股票代码'),
        sa.Column('symbol', sa.String(10), nullable=False, comment='股票简码'),
        sa.Column('name', sa.String(50), nullable=False, comment='股票名称'),
        sa.Column('area', sa.String(50), comment='所在地区'),
        sa.Column('industry', sa.String(50), comment='所属行业'),
        sa.Column('market', sa.String(20), comment='市场类型'),
        sa.Column('list_date', sa.Date, comment='上市日期'),
        sa.Column('is_hs', sa.String(1), comment='是否沪深港通'),
    )

    # daily_data 表
    op.create_table(
        'daily_data',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('ts_code', sa.String(20), sa.ForeignKey('stocks.ts_code'), nullable=False),
        sa.Column('trade_date', sa.Date, nullable=False, comment='交易日期'),
        sa.Column('open', sa.Float, comment='开盘价'),
        sa.Column('high', sa.Float, comment='最高价'),
        sa.Column('low', sa.Float, comment='最低价'),
        sa.Column('close', sa.Float, comment='收盘价'),
        sa.Column('pre_close', sa.Float, comment='前收盘价'),
        sa.Column('change', sa.Float, comment='涨跌额'),
        sa.Column('pct_chg', sa.Float, comment='涨跌幅'),
        sa.Column('vol', sa.Float, comment='成交量(手)'),
        sa.Column('amount', sa.Float, comment='成交额(千元)'),
        sa.Column('is_suspended', sa.Boolean, default=False, comment='是否停牌'),
    )
    op.create_index('idx_daily_ts_date', 'daily_data', ['ts_code', 'trade_date'], unique=True)

    # watchlist 表
    op.create_table(
        'watchlist',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('ts_code', sa.String(20), sa.ForeignKey('stocks.ts_code'), nullable=False),
        sa.Column('added_at', sa.DateTime, server_default=sa.text('now()'), comment='添加时间'),
        sa.Column('note', sa.String(200), comment='备注'),
    )
    op.create_index('idx_watchlist_ts_code', 'watchlist', ['ts_code'], unique=True)

    # monitor_rules 表
    op.create_table(
        'monitor_rules',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('ts_code', sa.String(20), nullable=False),
        sa.Column('rule_type', sa.String(20), nullable=False, comment='规则类型'),
        sa.Column('threshold', sa.Float, nullable=False, comment='阈值'),
        sa.Column('enabled', sa.Boolean, default=True),
        sa.Column('created_at', sa.DateTime, server_default=sa.text('now()')),
    )

    # alerts 表
    op.create_table(
        'alerts',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('ts_code', sa.String(20), nullable=False),
        sa.Column('rule_type', sa.String(20), nullable=False),
        sa.Column('message', sa.Text, nullable=False),
        sa.Column('triggered_at', sa.DateTime, server_default=sa.text('now()')),
        sa.Column('is_read', sa.Boolean, default=False),
    )

    # analysis_reports 表
    op.create_table(
        'analysis_reports',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('ts_code', sa.String(20), nullable=False),
        sa.Column('agent_type', sa.String(50), nullable=False, comment='Agent类型'),
        sa.Column('report_content', sa.Text, nullable=False),
        sa.Column('trend', sa.String(20), comment='趋势判断'),
        sa.Column('score', sa.Integer, comment='综合评分'),
        sa.Column('created_at', sa.DateTime, server_default=sa.text('now()')),
    )
    op.create_index('idx_report_ts_created', 'analysis_reports', ['ts_code', 'created_at'])

    # research_documents 表
    op.create_table(
        'research_documents',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('ts_code', sa.String(20), nullable=False),
        sa.Column('title', sa.String(200), nullable=False),
        sa.Column('content', sa.Text),
        sa.Column('file_path', sa.String(500)),
        sa.Column('source', sa.String(50), comment='来源'),
        sa.Column('uploaded_at', sa.DateTime, server_default=sa.text('now()')),
    )


def downgrade() -> None:
    op.drop_table('research_documents')
    op.drop_table('analysis_reports')
    op.drop_table('alerts')
    op.drop_table('monitor_rules')
    op.drop_table('watchlist')
    op.drop_index('idx_daily_ts_date', 'daily_data')
    op.drop_table('daily_data')
    op.drop_table('stocks')
