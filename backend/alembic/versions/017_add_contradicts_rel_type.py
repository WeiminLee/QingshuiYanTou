"""添加 CONTRADICTS 关系类型到 kg_relationships CheckConstraint

Revision ID: 017
Revises: 016
Create Date: 2026-04-08
"""
from alembic import op

revision = '017'
down_revision = '016'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 删除旧约束，重建含 CONTRADICTS 的约束
    op.execute("""
        ALTER TABLE kg_relationships
        DROP CONSTRAINT IF EXISTS chk_rel_type
    """)
    op.execute("""
        ALTER TABLE kg_relationships
        ADD CONSTRAINT chk_rel_type
        CHECK (relationship_type IN (
            'BELONGS_TO','PRODUCES','SUPPLIES_TO','USES','APPLIES_TO',
            'CATALYZES','CONSTRAINS','DISCLOSES','SUBSTITUTES',
            'COMPETES_WITH','STATE_TRANSITION','CONTRADICTS'
        ))
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE kg_relationships
        DROP CONSTRAINT IF EXISTS chk_rel_type
    """)
    op.execute("""
        ALTER TABLE kg_relationships
        ADD CONSTRAINT chk_rel_type
        CHECK (relationship_type IN (
            'BELONGS_TO','PRODUCES','SUPPLIES_TO','USES','APPLIES_TO',
            'CATALYZES','CONSTRAINS','DISCLOSES','SUBSTITUTES',
            'COMPETES_WITH','STATE_TRANSITION'
        ))
    """)
