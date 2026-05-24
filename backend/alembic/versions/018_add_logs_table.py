"""添加 logs 表（结构化日志表，用于跟踪数据接入层和推理服务）

Revision ID: 018_add_logs_table
Revises: 018
Create Date: 2026-05-16
"""
from alembic import op
import sqlalchemy as sa

revision = '018_add_logs_table'
down_revision = '018'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE logs (
            id            BIGSERIAL PRIMARY KEY,
            timestamp     TIMESTAMPTZ NOT NULL,
            level        VARCHAR(10) NOT NULL,
            service      VARCHAR(50) NOT NULL,
            module       VARCHAR(100) NOT NULL,
            message      TEXT NOT NULL,
            trace_id     UUID,
            task_id      UUID,
            duration_ms  INTEGER,
            extra_data   JSONB,
            created_at   TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX idx_logs_timestamp ON logs(timestamp)")
    op.execute("CREATE INDEX idx_logs_level ON logs(level)")
    op.execute("CREATE INDEX idx_logs_service ON logs(service)")
    op.execute("CREATE INDEX idx_logs_trace_id ON logs(trace_id)")
    op.execute("CREATE INDEX idx_logs_task_id ON logs(task_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS logs")
