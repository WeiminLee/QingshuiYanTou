"""add_eval_runs

Revision ID: 019
Revises: 2d5d913bd156
Create Date: 2026-04-20 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '019'
down_revision: Union[str, None] = '2d5d913bd156'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'eval_runs',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        # 关联 AnalysisReport（D-04: report_id 一一对应）
        sa.Column('report_id', sa.Integer(), sa.ForeignKey('analysis_reports.id', ondelete='CASCADE'), nullable=True),
        sa.Column('ts_code', sa.String(20), nullable=True),
        sa.Column('industry', sa.String(100), nullable=True),
        # run_type: automated_daily / quarterly_manual（D-01）
        sa.Column('run_type', sa.String(50), nullable=False, server_default='automated_daily'),
        sa.Column('run_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        # 三大评估指标（ADV-EVAL-01）
        sa.Column('recall_score', sa.Float(), nullable=True),
        sa.Column('coverage_score', sa.Float(), nullable=True),
        sa.Column('entity_count', sa.Integer(), nullable=True),
        sa.Column('confidence_avg', sa.Float(), nullable=True),
        # 人工评估字段
        sa.Column('analyst_id', sa.String(50), nullable=True),
        sa.Column('sample_size', sa.Integer(), nullable=True),
        # notes JSONB 存储评估详情
        sa.Column('notes', postgresql.JSONB, nullable=True),
        # A/B 实验字段（D-03）
        sa.Column('experiment_group', sa.String(50), nullable=True),
        sa.Column('variant', sa.String(50), nullable=True),
        # 溯源字段
        sa.Column('source_type', sa.String(50), server_default='research_report'),
        sa.Column('confidence_tier', sa.String(20), server_default='Tier 4'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), onupdate=sa.text('now()')),
    )
    # 唯一约束（D-04: report_id 一一对应）
    op.create_unique_constraint('uq_eval_runs_report_id', 'eval_runs', ['report_id'])
    # 索引
    op.create_index('idx_eval_runs_report_id', 'eval_runs', ['report_id'])
    op.create_index('idx_eval_runs_run_type', 'eval_runs', ['run_type'])
    op.create_index('idx_eval_runs_run_at', 'eval_runs', ['run_at'])


def downgrade() -> None:
    op.drop_index('idx_eval_runs_run_at', table_name='eval_runs')
    op.drop_index('idx_eval_runs_run_type', table_name='eval_runs')
    op.drop_index('idx_eval_runs_report_id', table_name='eval_runs')
    op.drop_constraint('uq_eval_runs_report_id', 'eval_runs', type_='unique')
    op.drop_table('eval_runs')
