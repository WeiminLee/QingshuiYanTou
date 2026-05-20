"""drop research_documents（统一到 research_report_meta，Phase 31 D-B1）

Revision ID: 020
Revises: 019
Create Date: 2026-05-13

Phase 30 已移除上传写路径；本 migration 删除孤岛表 research_documents。
upgrade 前先 COUNT(*) 安全检查（assumption A4：表预期为空）；非空则 abort 等待人工备份。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '020'
down_revision: Union[str, Sequence[str], None] = '019'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 安全检查：有数据则 abort（T-31-03-drop-prod-data mitigation）
    conn = op.get_bind()
    count = conn.execute(sa.text("SELECT COUNT(*) FROM research_documents")).scalar()
    if count is not None and count > 0:
        raise RuntimeError(
            f"research_documents 仍有 {count} 行数据，请先手动备份再运行此 migration "
            "(参考 Phase 31 D-B1 / RESEARCH §Delete 清单 B)"
        )
    op.drop_table("research_documents")


def downgrade() -> None:
    """重建空 schema（复用 001_init_tables.py 中 ResearchDocument 的原始字段定义）。"""
    op.create_table(
        'research_documents',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('ts_code', sa.String(20), nullable=False),
        sa.Column('title', sa.String(200), nullable=False),
        sa.Column('content', sa.Text()),
        sa.Column('file_path', sa.String(500)),
        sa.Column('source', sa.String(50)),
        sa.Column('uploaded_at', sa.DateTime(), server_default=sa.text('now()')),
    )
