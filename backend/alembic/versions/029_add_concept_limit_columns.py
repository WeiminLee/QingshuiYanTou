"""align concept_limit with models.py / alembic 004 — add 4 nullable columns

Revision ID: 029
Revises: 028
Create Date: 2026-10-15

背景：concept_limit 表由 scripts/init_database.py 的瘦表 DDL 引导创建
（项目首日即如此），缺 models.py 与 alembic 004 声明的 days/up_stat/
cons_nums/rank 四列，导致 ORM 整实体 SELECT（get_top_concepts/
get_concept_history）抛 UndefinedColumnError。本迁移补齐结构对齐，
不涉及数据（fetch_concept 从不写这四列，保持 NULL）。
"""

from alembic import op
import sqlalchemy as sa

revision = "029"
down_revision = "028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("concept_limit", sa.Column("days", sa.Integer(), nullable=True, comment="连板天数"))
    op.add_column("concept_limit", sa.Column("up_stat", sa.String(50), nullable=True, comment="涨停状态描述"))
    op.add_column("concept_limit", sa.Column("cons_nums", sa.Integer(), nullable=True, comment="成分股数"))
    op.add_column("concept_limit", sa.Column("rank", sa.Integer(), nullable=True, comment="当日排名"))


def downgrade() -> None:
    op.drop_column("concept_limit", "rank")
    op.drop_column("concept_limit", "cons_nums")
    op.drop_column("concept_limit", "up_stat")
    op.drop_column("concept_limit", "days")