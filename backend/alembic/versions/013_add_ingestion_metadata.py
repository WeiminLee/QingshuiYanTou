"""
添加数据接入层元数据字段

- announcements 表：source_type, source_name, confidence_tier, parser_version, extracted_at
- research_report_meta 表：同上

Revises: 012_add_score_tables
"""
from alembic import op
import sqlalchemy as sa

revision = "013_add_ingestion_metadata"
down_revision = "012_add_score_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # announcements 表
    op.add_column("announcements", sa.Column("source_type", sa.String(50), nullable=False, server_default="cninfo_announcement"))
    op.add_column("announcements", sa.Column("source_name", sa.String(100), nullable=False, server_default="巨潮资讯网"))
    op.add_column("announcements", sa.Column("confidence_tier", sa.String(20), nullable=False, server_default="Tier 1"))
    op.add_column("announcements", sa.Column("parser_version", sa.String(20), nullable=False, server_default="v1.0"))
    op.add_column("announcements", sa.Column("extracted_at", sa.DateTime(), nullable=True))

    # research_report_meta 表
    op.add_column("research_report_meta", sa.Column("source_type", sa.String(50), nullable=False, server_default="research_report"))
    op.add_column("research_report_meta", sa.Column("source_name", sa.String(100), nullable=False, server_default="Tushare研报"))
    op.add_column("research_report_meta", sa.Column("confidence_tier", sa.String(20), nullable=False, server_default="Tier 4"))
    op.add_column("research_report_meta", sa.Column("parser_version", sa.String(20), nullable=False, server_default="v1.0"))
    op.add_column("research_report_meta", sa.Column("extracted_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("research_report_meta", "extracted_at")
    op.drop_column("research_report_meta", "parser_version")
    op.drop_column("research_report_meta", "confidence_tier")
    op.drop_column("research_report_meta", "source_name")
    op.drop_column("research_report_meta", "source_type")
    op.drop_column("announcements", "extracted_at")
    op.drop_column("announcements", "parser_version")
    op.drop_column("announcements", "confidence_tier")
    op.drop_column("announcements", "source_name")
    op.drop_column("announcements", "source_type")
