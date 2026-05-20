"""新增：THS 概念板块表及成分股表（统一 TI 格式）

Revision ID: 005_add_ths_concept_tables
Revises: 004
Create Date: 2026-04-03
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import Index

revision = '005'
down_revision = '004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # THS 概念板块表（TI 格式代码，与 limit_cpt_list 体系一致）
    op.create_table(
        'ths_concepts',
        sa.Column('ts_code', sa.String(20), primary_key=True, comment='THS概念代码，如 885800.TI'),
        sa.Column('name', sa.String(100), nullable=False, comment='概念名称'),
        sa.Column('count', sa.Integer(), comment='成分股数量'),
        sa.Column('exchange', sa.String(10), comment='所属交易所：A=全部，N=概念，E=行业'),
        sa.Column('list_date', sa.Date(), comment='纳入日期'),
        sa.Column('type', sa.String(10), comment='类型：N=概念，E=行业'),
    )

    # THS 概念-个股映射表
    op.create_table(
        'ths_concept_members',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('ts_code', sa.String(20), nullable=False, comment='THS概念代码'),
        sa.Column('con_code', sa.String(20), nullable=False, comment='成分股代码，如 000016.SZ'),
        sa.Column('con_name', sa.String(50), comment='成分股名称'),
        sa.Column('in_date', sa.Date(), comment='纳入日期'),
    )
    op.create_index(
        'idx_ths_member_unique', 'ths_concept_members', ['ts_code', 'con_code'], unique=True,
    )
    op.create_index('idx_ths_member_concept', 'ths_concept_members', ['ts_code'])
    op.create_index('idx_ths_member_stock', 'ths_concept_members', ['con_code'])


def downgrade() -> None:
    op.drop_table('ths_concept_members')
    op.drop_table('ths_concepts')
