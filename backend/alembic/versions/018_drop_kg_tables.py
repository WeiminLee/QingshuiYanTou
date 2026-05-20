"""删除 kg_entities / kg_relationships 表（迁移至 Neo4j）

Revision ID: 018
Revises: 017
Create Date: 2026-04-08
"""
from alembic import op

revision = '018'
down_revision = '017'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 先删外键引用表，再删主表
    op.execute("DROP TABLE IF EXISTS kg_relationships CASCADE")
    op.execute("DROP TABLE IF EXISTS kg_entities CASCADE")


def downgrade() -> None:
    # 保留空实现，降级需手动重建（不常用）
    pass
