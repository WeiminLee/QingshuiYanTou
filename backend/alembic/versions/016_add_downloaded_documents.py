"""添加 downloaded_documents 表（已下载文档记录，防重+断点续传）

Revision ID: 016
Revises: 015
Create Date: 2026-04-08
"""
from alembic import op
import sqlalchemy as sa

revision = '016'
down_revision = '015'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE downloaded_documents (
            id            SERIAL PRIMARY KEY,
            cninfo_id     VARCHAR(100) NOT NULL UNIQUE,
            ts_code       VARCHAR(20) NOT NULL,
            title         TEXT NOT NULL,
            doc_type      VARCHAR(30) NOT NULL,
            doc_date      DATE NOT NULL,
            file_path     VARCHAR(500) NOT NULL,
            file_size     INTEGER,
            org_id        VARCHAR(50),
            pdf_url       TEXT,
            downloaded_at TIMESTAMP DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX idx_doc_ts_date ON downloaded_documents(ts_code, doc_date)")
    op.execute("CREATE INDEX idx_doc_downloaded_at ON downloaded_documents(downloaded_at)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS downloaded_documents")
