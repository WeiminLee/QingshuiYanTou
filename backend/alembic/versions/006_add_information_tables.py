"""新增：公告索引表 + 研报元数据表

Revision ID: 006
Revises: 005
Create Date: 2026-04-03
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import Index

revision = '006'
down_revision = '005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 公告索引表
    op.create_table(
        'announcements',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('ann_date', sa.Date(), nullable=False, comment='公告日期'),
        sa.Column('ts_code', sa.String(20), nullable=False, comment='股票代码'),
        sa.Column('name', sa.String(100), comment='股票名称'),
        sa.Column('title', sa.String(500), comment='公告标题'),
        sa.Column('type', sa.String(50), comment='公告类型'),
    )
    op.create_index('idx_ann_ts_date', 'announcements', ['ts_code', 'ann_date'])
    op.create_index('idx_ann_date', 'announcements', ['ann_date'])

    # 研报元数据表
    op.create_table(
        'research_report_meta',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('trade_date', sa.Date(), nullable=False, comment='交易日期'),
        sa.Column('ts_code', sa.String(20), nullable=True, comment='股票代码（可能为空）'),
        sa.Column('file_name', sa.String(500), nullable=False, comment='文件名'),
        sa.Column('author', sa.String(200), comment='分析师'),
        sa.Column('inst_csname', sa.String(200), comment='机构名称'),
    )
    op.create_index('idx_rmeta_ts_date', 'research_report_meta', ['ts_code', 'trade_date'])
    op.create_index('idx_rmeta_date', 'research_report_meta', ['trade_date'])


def downgrade() -> None:
    op.drop_table('research_report_meta')
    op.drop_table('announcements')
