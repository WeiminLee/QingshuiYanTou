"""数据接入进度与断点跟踪服务。"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from app.core.database import engine


RUNNING = "running"
SUCCESS = "success"
PARTIAL = "partial"
FAILED = "failed"


@dataclass(frozen=True)
class IngestionRunContext:
    run_id: uuid.UUID
    source: str
    task_name: str
    scope: str


class IngestionProgressTracker:
    """持久化记录一次接入任务的运行状态、事件和 checkpoint。"""
    _tables_ready = False

    def __init__(
        self,
        source: str,
        task_name: str,
        scope: str = "default",
    ) -> None:
        self.source = source
        self.task_name = task_name
        self.scope = scope

    async def ensure_tables(self) -> None:
        """确保审计跟踪表存在。

        生产环境仍应通过迁移创建表；这里的幂等兜底避免数据任务因为审计表缺失直接中断。
        """
        if IngestionProgressTracker._tables_ready:
            return
        statements = [
            """
            CREATE TABLE IF NOT EXISTS ingestion_runs (
                id BIGSERIAL PRIMARY KEY,
                run_id UUID NOT NULL UNIQUE,
                source VARCHAR(50) NOT NULL,
                task_name VARCHAR(100) NOT NULL,
                scope VARCHAR(100) NOT NULL DEFAULT 'default',
                status VARCHAR(20) NOT NULL,
                started_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW(),
                completed_at TIMESTAMPTZ,
                from_watermark VARCHAR(50),
                to_watermark VARCHAR(50),
                current_watermark VARCHAR(50),
                current_page INTEGER,
                total_pages INTEGER,
                total_items INTEGER DEFAULT 0,
                processed_items INTEGER DEFAULT 0,
                success_count INTEGER DEFAULT 0,
                skipped_count INTEGER DEFAULT 0,
                downloaded_count INTEGER DEFAULT 0,
                fail_count INTEGER DEFAULT 0,
                last_item_id VARCHAR(100),
                last_error TEXT,
                metadata JSONB
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_ingestion_runs_source_scope ON ingestion_runs(source, scope)",
            "CREATE INDEX IF NOT EXISTS idx_ingestion_runs_status ON ingestion_runs(status)",
            "CREATE INDEX IF NOT EXISTS idx_ingestion_runs_started_at ON ingestion_runs(started_at)",
            """
            CREATE TABLE IF NOT EXISTS ingestion_progress_events (
                id BIGSERIAL PRIMARY KEY,
                run_id UUID NOT NULL,
                source VARCHAR(50) NOT NULL,
                task_name VARCHAR(100) NOT NULL,
                scope VARCHAR(100) NOT NULL DEFAULT 'default',
                stage VARCHAR(50) NOT NULL,
                message TEXT NOT NULL,
                current_page INTEGER,
                total_pages INTEGER,
                total_items INTEGER,
                processed_items INTEGER,
                success_count INTEGER,
                skipped_count INTEGER,
                downloaded_count INTEGER,
                fail_count INTEGER,
                item_id VARCHAR(100),
                item_title TEXT,
                error TEXT,
                metadata JSONB,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_ingestion_events_run_id ON ingestion_progress_events(run_id)",
            "CREATE INDEX IF NOT EXISTS idx_ingestion_events_source_scope ON ingestion_progress_events(source, scope)",
            "CREATE INDEX IF NOT EXISTS idx_ingestion_events_created_at ON ingestion_progress_events(created_at)",
            """
            CREATE TABLE IF NOT EXISTS ingestion_checkpoints (
                id BIGSERIAL PRIMARY KEY,
                source VARCHAR(50) NOT NULL,
                task_name VARCHAR(100) NOT NULL,
                scope VARCHAR(100) NOT NULL DEFAULT 'default',
                watermark_type VARCHAR(30) NOT NULL DEFAULT 'date',
                last_success_watermark VARCHAR(50),
                last_attempt_watermark VARCHAR(50),
                last_run_id UUID,
                last_status VARCHAR(20),
                last_success_at TIMESTAMPTZ,
                last_attempt_at TIMESTAMPTZ,
                next_from_watermark VARCHAR(50),
                metadata JSONB,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW(),
                CONSTRAINT uq_ingestion_checkpoints_source_scope UNIQUE (source, task_name, scope)
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_ingestion_checkpoints_source ON ingestion_checkpoints(source)",
        ]
        async with engine.begin() as conn:
            for sql in statements:
                await conn.execute(text(sql))
        IngestionProgressTracker._tables_ready = True

    async def get_checkpoint(self) -> dict[str, Any] | None:
        await self.ensure_tables()
        async with engine.connect() as conn:
            row = (
                await conn.execute(
                    text(
                        """
                        SELECT source, task_name, scope, watermark_type,
                               last_success_watermark, last_attempt_watermark,
                               last_run_id, last_status, last_success_at,
                               last_attempt_at, next_from_watermark, metadata
                        FROM ingestion_checkpoints
                        WHERE source = :source
                          AND task_name = :task_name
                          AND scope = :scope
                        """
                    ),
                    {
                        "source": self.source,
                        "task_name": self.task_name,
                        "scope": self.scope,
                    },
                )
            ).mappings().first()
        return dict(row) if row else None

    async def start_run(
        self,
        from_watermark: str | None = None,
        to_watermark: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> IngestionRunContext:
        await self.ensure_tables()
        run_id = uuid.uuid4()
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    """
                    INSERT INTO ingestion_runs (
                        run_id, source, task_name, scope, status,
                        from_watermark, to_watermark, current_watermark,
                        metadata
                    ) VALUES (
                        :run_id, :source, :task_name, :scope, :status,
                        :from_watermark, :to_watermark, :current_watermark,
                        CAST(:metadata AS jsonb)
                    )
                    """
                ),
                {
                    "run_id": run_id,
                    "source": self.source,
                    "task_name": self.task_name,
                    "scope": self.scope,
                    "status": RUNNING,
                    "from_watermark": from_watermark,
                    "to_watermark": to_watermark,
                    "current_watermark": from_watermark,
                    "metadata": _json_dumps(metadata),
                },
            )

        ctx = IngestionRunContext(run_id, self.source, self.task_name, self.scope)
        await self.event(
            ctx,
            stage="start",
            message="接入任务开始",
            metadata=metadata,
        )
        return ctx

    async def event(
        self,
        ctx: IngestionRunContext,
        stage: str,
        message: str,
        current_page: int | None = None,
        total_pages: int | None = None,
        total_items: int | None = None,
        processed_items: int | None = None,
        success_count: int | None = None,
        skipped_count: int | None = None,
        downloaded_count: int | None = None,
        fail_count: int | None = None,
        item_id: str | None = None,
        item_title: str | None = None,
        error: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    """
                    INSERT INTO ingestion_progress_events (
                        run_id, source, task_name, scope, stage, message,
                        current_page, total_pages, total_items, processed_items,
                        success_count, skipped_count, downloaded_count, fail_count,
                        item_id, item_title, error, metadata
                    ) VALUES (
                        :run_id, :source, :task_name, :scope, :stage, :message,
                        :current_page, :total_pages, :total_items, :processed_items,
                        :success_count, :skipped_count, :downloaded_count, :fail_count,
                        :item_id, :item_title, :error, CAST(:metadata AS jsonb)
                    )
                    """
                ),
                {
                    "run_id": ctx.run_id,
                    "source": ctx.source,
                    "task_name": ctx.task_name,
                    "scope": ctx.scope,
                    "stage": stage,
                    "message": message,
                    "current_page": current_page,
                    "total_pages": total_pages,
                    "total_items": total_items,
                    "processed_items": processed_items,
                    "success_count": success_count,
                    "skipped_count": skipped_count,
                    "downloaded_count": downloaded_count,
                    "fail_count": fail_count,
                    "item_id": item_id,
                    "item_title": item_title,
                    "error": error,
                    "metadata": _json_dumps(metadata),
                },
            )

    async def update_run(
        self,
        ctx: IngestionRunContext,
        current_watermark: str | None = None,
        current_page: int | None = None,
        total_pages: int | None = None,
        total_items: int | None = None,
        processed_items: int | None = None,
        success_count: int | None = None,
        skipped_count: int | None = None,
        downloaded_count: int | None = None,
        fail_count: int | None = None,
        last_item_id: str | None = None,
        last_error: str | None = None,
    ) -> None:
        values = {
            "current_watermark": current_watermark,
            "current_page": current_page,
            "total_pages": total_pages,
            "total_items": total_items,
            "processed_items": processed_items,
            "success_count": success_count,
            "skipped_count": skipped_count,
            "downloaded_count": downloaded_count,
            "fail_count": fail_count,
            "last_item_id": last_item_id,
            "last_error": last_error,
        }
        if values["last_item_id"] is not None:
            values["last_item_id"] = str(values["last_item_id"])[:100]
        assignments = [
            f"{name} = :{name}"
            for name, value in values.items()
            if value is not None
        ]
        if not assignments:
            return
        assignments.append("updated_at = NOW()")

        params = {name: value for name, value in values.items() if value is not None}
        params["run_id"] = ctx.run_id
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    f"""
                    UPDATE ingestion_runs
                    SET {", ".join(assignments)}
                    WHERE run_id = :run_id
                    """
                ),
                params,
            )

    async def finish_run(
        self,
        ctx: IngestionRunContext,
        status: str,
        total_items: int,
        processed_items: int,
        success_count: int,
        skipped_count: int,
        downloaded_count: int,
        fail_count: int,
        current_watermark: str | None = None,
        last_item_id: str | None = None,
        last_error: str | None = None,
        checkpoint_watermark: str | None = None,
        next_from_watermark: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        now = datetime.now(timezone.utc)
        if last_item_id is not None:
            last_item_id = str(last_item_id)[:100]
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    """
                    UPDATE ingestion_runs
                    SET status = :status,
                        completed_at = :completed_at,
                        updated_at = :completed_at,
                        current_watermark = COALESCE(:current_watermark, current_watermark),
                        total_items = :total_items,
                        processed_items = :processed_items,
                        success_count = :success_count,
                        skipped_count = :skipped_count,
                        downloaded_count = :downloaded_count,
                        fail_count = :fail_count,
                        last_item_id = :last_item_id,
                        last_error = :last_error
                    WHERE run_id = :run_id
                    """
                ),
                {
                    "run_id": ctx.run_id,
                    "status": status,
                    "completed_at": now,
                    "current_watermark": current_watermark,
                    "total_items": total_items,
                    "processed_items": processed_items,
                    "success_count": success_count,
                    "skipped_count": skipped_count,
                    "downloaded_count": downloaded_count,
                    "fail_count": fail_count,
                    "last_item_id": last_item_id,
                    "last_error": last_error,
                },
            )

        await self.event(
            ctx,
            stage="finish",
            message="接入任务完成" if status in (SUCCESS, PARTIAL) else "接入任务失败",
            total_items=total_items,
            processed_items=processed_items,
            success_count=success_count,
            skipped_count=skipped_count,
            downloaded_count=downloaded_count,
            fail_count=fail_count,
            item_id=last_item_id,
            error=last_error,
            metadata=metadata,
        )

        await self.upsert_checkpoint(
            ctx,
            status=status,
            checkpoint_watermark=checkpoint_watermark,
            attempt_watermark=current_watermark,
            next_from_watermark=next_from_watermark,
            metadata=metadata,
        )

    async def upsert_checkpoint(
        self,
        ctx: IngestionRunContext,
        status: str,
        checkpoint_watermark: str | None,
        attempt_watermark: str | None,
        next_from_watermark: str | None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    """
                    INSERT INTO ingestion_checkpoints (
                        source, task_name, scope, watermark_type,
                        last_success_watermark, last_attempt_watermark,
                        last_run_id, last_status, last_success_at, last_attempt_at,
                        next_from_watermark, metadata, updated_at
                    ) VALUES (
                        :source, :task_name, :scope, 'date',
                        :last_success_watermark, :last_attempt_watermark,
                        :last_run_id, :last_status,
                        CASE WHEN :is_success THEN NOW() ELSE NULL END,
                        NOW(), :next_from_watermark, CAST(:metadata AS jsonb), NOW()
                    )
                    ON CONFLICT (source, task_name, scope) DO UPDATE SET
                        last_success_watermark = CASE
                            WHEN :is_success THEN EXCLUDED.last_success_watermark
                            ELSE ingestion_checkpoints.last_success_watermark
                        END,
                        last_attempt_watermark = EXCLUDED.last_attempt_watermark,
                        last_run_id = EXCLUDED.last_run_id,
                        last_status = EXCLUDED.last_status,
                        last_success_at = CASE
                            WHEN :is_success THEN NOW()
                            ELSE ingestion_checkpoints.last_success_at
                        END,
                        last_attempt_at = NOW(),
                        next_from_watermark = CASE
                            WHEN :is_success THEN EXCLUDED.next_from_watermark
                            ELSE ingestion_checkpoints.next_from_watermark
                        END,
                        metadata = EXCLUDED.metadata,
                        updated_at = NOW()
                    """
                ),
                {
                    "source": ctx.source,
                    "task_name": ctx.task_name,
                    "scope": ctx.scope,
                    "last_success_watermark": checkpoint_watermark,
                    "last_attempt_watermark": attempt_watermark,
                    "last_run_id": ctx.run_id,
                    "last_status": status,
                    "is_success": status in (SUCCESS, PARTIAL),
                    "next_from_watermark": next_from_watermark,
                    "metadata": _json_dumps(metadata),
                },
            )


def _json_dumps(value: dict[str, Any] | None) -> str | None:
    if value is None:
        return None
    import json

    return json.dumps(value, ensure_ascii=False, default=str)
