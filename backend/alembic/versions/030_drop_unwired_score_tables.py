"""drop three unwired score/pool tables and align announcements

Revision ID: 030
Revises: 029
Create Date: 2026-10-21

背景（docs/待办.md F2/F3 的收敛）：
1. `stock_pool` / `stock_scores` / `concept_scores` 三表在代码中**无任何读写路径**
   （ORM 与原生 SQL 引用均为 0），生产库均为 0 行。它们的模型声明与库结构长期不一致
   （模型比库多 10~12 列），是纯认知债。原 DDL 已备份至
   /data/qingshui/backup/ddl-before-drop-<ts>.sql，需要时可重建。
2. `announcements` 模型声明了 `parser_version` / `extracted_at`，而生产库没有这两列；
   `scripts/sync_minishare_ann_history.py` 等走 `pg_insert(Announcement.__table__)`，
   一旦传入这两列即 UndefinedColumnError。补齐为可空列，消除该写入炸点。

不涉及数据迁移（三表空表，两新列可空）。
"""

from alembic import op
import sqlalchemy as sa

revision = "030"
down_revision = "029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("concept_scores")
    op.drop_table("stock_scores")
    op.drop_table("stock_pool")

    op.add_column("announcements", sa.Column("parser_version", sa.String(20), nullable=True))
    op.add_column("announcements", sa.Column("extracted_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("announcements", "extracted_at")
    op.drop_column("announcements", "parser_version")

    # 原 DDL 重建（与 pg_dump --schema-only 备份一致；数据不可恢复，重建时为空表）
    op.create_table(
        "stock_pool",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("ts_code", sa.String(20), nullable=False),
        sa.Column("pool_type", sa.String(50), nullable=False),
        sa.Column("added_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("note", sa.Text()),
        sa.UniqueConstraint("ts_code", "pool_type", name="stock_pool_ts_code_pool_type_key"),
    )
    op.create_table(
        "stock_scores",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("ts_code", sa.String(20), nullable=False),
        sa.Column("composite_score", sa.Float()),
        sa.Column("momentum_score", sa.Float()),
        sa.Column("concept_score", sa.Float()),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("ts_code", name="stock_scores_ts_code_key"),
    )
    op.create_table(
        "concept_scores",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("ts_code", sa.String(20), nullable=False),
        sa.Column("concept_code", sa.String(50), nullable=False),
        sa.Column("score", sa.Float()),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "ts_code", "concept_code", "trade_date", name="concept_scores_ts_code_concept_code_trade_date_key"
        ),
    )