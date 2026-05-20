"""扩大 announcements 表字段 + 修正主键

Revision ID: 010
Revises: 009
Create Date: 2026-04-03
"""
from alembic import op
import sqlalchemy as sa

revision = '010'
down_revision = '009'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 扩大字段
    op.alter_column('announcements', 'title', type_=sa.Text(), existing_type=sa.String(500))
    op.alter_column('announcements', 'type', type_=sa.Text(), existing_type=sa.String(50))
    op.alter_column('announcements', 'announcement_type', type_=sa.Text(), existing_type=sa.String(20))
    op.alter_column('announcements', 'pdf_url', type_=sa.Text(), existing_type=sa.String(500))
    op.alter_column('announcements', 'cninfo_id', type_=sa.String(100), existing_type=sa.String(100))
    op.execute("ALTER TABLE announcements ADD COLUMN IF NOT EXISTS file_path VARCHAR(500)")
    # 复合唯一约束（cninfo_id 为空时兜底）
    op.create_index('idx_ann_unique_key', 'announcements',
        ['ts_code', 'ann_date', 'title'], unique=True, if_not_exists=True)


def downgrade() -> None:
    pass
