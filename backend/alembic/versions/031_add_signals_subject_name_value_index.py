"""add signals(subject_name, value_score desc) index for worker watermark lookups

Revision ID: 031
Revises: 030
Create Date: 2026-10-27

背景：worker 的 signal 推导经 Knowledge API 查水位，24 并发下原查询退化为
idx_signals_value_score 反向扫描 + subject_name 过滤（实测 ~162ms），
2s statement_timeout 被打满后 500 → job 失败。新增复合索引后 ~1ms。
生产库已于 2026-10-27 手工 CONCURRENTLY 建好同名索引；本迁移保证新库/重放一致。
"""

from alembic import op

revision = "031"
down_revision = "030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_signals_subject_name_value "
            "ON signals (subject_name, value_score DESC)"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_signals_subject_name_value")
