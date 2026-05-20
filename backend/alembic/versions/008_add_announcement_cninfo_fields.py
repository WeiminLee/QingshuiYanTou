"""为 announcements 表新增巨潮字段

Revision ID: 008
Revises: 007
Create Date: 2026-04-03
"""
from alembic import op
import sqlalchemy as sa

revision = '008'
down_revision = '007'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('announcements', sa.Column('cninfo_id', sa.String(100), unique=True, comment='巨潮公告唯一ID'))
    op.add_column('announcements', sa.Column('org_id', sa.String(50), comment='巨潮机构ID'))
    op.add_column('announcements', sa.Column('announcement_type', sa.String(20), comment='巨潮公告类型编码'))
    op.add_column('announcements', sa.Column('pdf_url', sa.String(500), comment='PDF下载链接'))
    # 替换唯一约束（原来没有唯一约束，现在用 cninfo_id 做唯一键）
    op.create_index('idx_ann_cninfo_id', 'announcements', ['cninfo_id'], unique=True, if_not_exists=True)


def downgrade() -> None:
    op.drop_index('idx_ann_cninfo_id', table_name='announcements')
    op.drop_column('announcements', 'pdf_url')
    op.drop_column('announcements', 'announcement_type')
    op.drop_column('announcements', 'org_id')
    op.drop_column('announcements', 'cninfo_id')
