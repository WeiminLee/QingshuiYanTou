# 数据接入任务队列实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 将巨潮公告和互动易同步改为统一任务队列消费模型，默认滚动生成最近 7 天公告任务，并以股票为粒度可靠消费互动易任务。

**架构：** 新增 PostgreSQL `ingestion_jobs` 队列表作为唯一调度事实源，producer 只负责幂等生成任务，worker 通过 `FOR UPDATE SKIP LOCKED` 领取并执行任务。公告按日期建 job，互动易按 `ts_code` 建 job；失败进入可重试队列，达到最大次数后进入 `dead`，监控 API 从队列表和现有 `ingestion_runs` 汇总状态。

**技术栈：** Python 3.11、FastAPI、SQLAlchemy async、asyncpg、Alembic、APScheduler、PostgreSQL JSONB、pytest。

---

## 文件结构

- 创建：`backend/alembic/versions/022_add_ingestion_jobs.py`
  - 创建 `ingestion_jobs` 队列表、唯一键、领取索引、状态索引。
- 修改：`backend/app/models/models.py`
  - 添加 `IngestionJob` ORM 模型，保持与 Alembic 表结构一致。
- 创建：`backend/app/data_pipeline/job_queue.py`
  - 定义 job 类型、状态、队列服务：幂等 enqueue、claim、success、failure、dead、stale running 回收。
- 创建：`backend/app/data_pipeline/job_producers.py`
  - 生成 `cninfo_announcement_date` 和 `irm_company` job；公告默认最近 7 天；互动易按股票列表生成。
- 创建：`backend/app/data_pipeline/job_handlers.py`
  - 将 job 派发到现有 `DataFetcher.fetch_announcements()` 和 `DataFetcher.fetch_irm(ts_codes=[...])`，把结果归一化为 `JobExecutionResult`。
- 创建：`backend/app/data_pipeline/job_worker.py`
  - 批量领取 job 并执行；支持单 job 超时、重试退避、worker id、一次性运行和循环运行。
- 创建：`backend/scripts/ingestion_worker.py`
  - 命令行入口：`python scripts/ingestion_worker.py --once --limit 20`。
- 修改：`backend/app/data_pipeline/scheduler.py`
  - 公告和互动易定时任务改为 enqueue job；新增队列 worker 定时 drain。
- 修改：`backend/app/data_pipeline/api/monitor.py`
  - 增加 job 队列概览、按类型查看失败和 dead job 的接口。
- 创建：`backend/tests/test_ingestion_job_queue.py`
  - 单元测试队列幂等、领取锁、失败退避、dead 转换。
- 创建：`backend/tests/test_ingestion_job_producers.py`
  - 单元测试默认 7 天公告 job 和互动易 job 生成。
- 创建：`backend/tests/test_ingestion_job_worker.py`
  - 单元测试 worker 成功、失败重试、超时处理。
- 修改：`backend/tests/test_phase31_scheduler.py`
  - 调整 scheduler 行为测试：定时任务只 enqueue，不直接同步外部源。

---

## 任务 1：数据库迁移与 ORM 模型

**文件：**
- 创建：`backend/alembic/versions/022_add_ingestion_jobs.py`
- 修改：`backend/app/models/models.py`
- 测试：`backend/tests/test_ingestion_job_queue.py`

- [ ] **步骤 1：编写失败的模型结构测试**

在 `backend/tests/test_ingestion_job_queue.py` 创建测试文件：

```python
"""Tests for durable ingestion job queue."""
from __future__ import annotations


def test_ingestion_job_model_declares_queue_contract() -> None:
    from app.models.models import IngestionJob

    columns = IngestionJob.__table__.columns

    assert "job_type" in columns
    assert "job_key" in columns
    assert "status" in columns
    assert "payload" in columns
    assert "priority" in columns
    assert "attempt_count" in columns
    assert "max_attempts" in columns
    assert "next_run_at" in columns
    assert "locked_at" in columns
    assert "locked_by" in columns
    assert "last_error" in columns
    assert "result_summary" in columns
    assert "created_at" in columns
    assert "updated_at" in columns
```

- [ ] **步骤 2：运行测试验证失败**

运行：

```bash
cd backend
pytest tests/test_ingestion_job_queue.py::test_ingestion_job_model_declares_queue_contract -q
```

预期：`ImportError` 或 `AttributeError`，因为 `IngestionJob` 尚不存在。

- [ ] **步骤 3：创建 Alembic 迁移**

创建 `backend/alembic/versions/022_add_ingestion_jobs.py`：

```python
"""add ingestion jobs queue

Revision ID: 022
Revises: 021
Create Date: 2026-05-23
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "022"
down_revision: Union[str, Sequence[str], None] = "021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ingestion_jobs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("job_type", sa.String(50), nullable=False),
        sa.Column("job_key", sa.String(200), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.String(100), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("result_summary", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_unique_constraint(
        "uq_ingestion_jobs_type_key",
        "ingestion_jobs",
        ["job_type", "job_key"],
    )
    op.create_index(
        "idx_ingestion_jobs_claim",
        "ingestion_jobs",
        ["status", "next_run_at", "priority", "id"],
    )
    op.create_index("idx_ingestion_jobs_type_status", "ingestion_jobs", ["job_type", "status"])
    op.create_index("idx_ingestion_jobs_locked_at", "ingestion_jobs", ["locked_at"])


def downgrade() -> None:
    op.drop_index("idx_ingestion_jobs_locked_at", table_name="ingestion_jobs")
    op.drop_index("idx_ingestion_jobs_type_status", table_name="ingestion_jobs")
    op.drop_index("idx_ingestion_jobs_claim", table_name="ingestion_jobs")
    op.drop_constraint("uq_ingestion_jobs_type_key", "ingestion_jobs", type_="unique")
    op.drop_table("ingestion_jobs")
```

- [ ] **步骤 4：添加 ORM 模型**

在 `backend/app/models/models.py` 的 `IngestionCheckpoint` 后追加：

```python
class IngestionJob(Base):
    """Durable queue job for data ingestion tasks."""
    __tablename__ = "ingestion_jobs"
    __table_args__ = (
        UniqueConstraint("job_type", "job_key", name="uq_ingestion_jobs_type_key"),
        Index("idx_ingestion_jobs_claim", "status", "next_run_at", "priority", "id"),
        Index("idx_ingestion_jobs_type_status", "job_type", "status"),
        Index("idx_ingestion_jobs_locked_at", "locked_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    job_type: Mapped[str] = mapped_column(String(50), nullable=False)
    job_key: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="pending")
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, server_default=text("'{}'::jsonb"))
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default="100")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="5")
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    locked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    locked_by: Mapped[Optional[str]] = mapped_column(String(100))
    last_error: Mapped[Optional[str]] = mapped_column(Text)
    result_summary: Mapped[Optional[dict]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

- [ ] **步骤 5：运行模型测试验证通过**

运行：

```bash
cd backend
pytest tests/test_ingestion_job_queue.py::test_ingestion_job_model_declares_queue_contract -q
```

预期：`1 passed`。

- [ ] **步骤 6：运行迁移语法检查**

运行：

```bash
cd backend
python -m py_compile alembic/versions/022_add_ingestion_jobs.py
```

预期：退出码 `0`。

- [ ] **步骤 7：Commit**

```bash
git add backend/alembic/versions/022_add_ingestion_jobs.py backend/app/models/models.py backend/tests/test_ingestion_job_queue.py
git commit -m "feat: add ingestion job queue schema"
```

---

## 任务 2：队列服务核心 API

**文件：**
- 创建：`backend/app/data_pipeline/job_queue.py`
- 修改：`backend/tests/test_ingestion_job_queue.py`

- [ ] **步骤 1：编写失败的 enqueue 幂等测试**

追加到 `backend/tests/test_ingestion_job_queue.py`：

```python
import asyncio
from datetime import datetime, timezone
from unittest.mock import MagicMock


def test_enqueue_job_uses_type_and_key_as_idempotency_boundary(monkeypatch) -> None:
    from app.data_pipeline.job_queue import IngestionJobQueue

    executed = []

    class FakeConn:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def execute(self, sql, params):
            executed.append((str(sql), params))

    fake_engine = MagicMock()
    fake_engine.begin.return_value = FakeConn()
    monkeypatch.setattr("app.data_pipeline.job_queue.engine", fake_engine)

    queue = IngestionJobQueue()
    asyncio.run(queue.enqueue_job(
        job_type="cninfo_announcement_date",
        job_key="20260523",
        payload={"date": "20260523"},
        priority=10,
        max_attempts=7,
    ))

    sql, params = executed[0]
    assert "ON CONFLICT (job_type, job_key) DO UPDATE" in sql
    assert params["job_type"] == "cninfo_announcement_date"
    assert params["job_key"] == "20260523"
    assert params["payload"] == '{"date": "20260523"}'
    assert params["priority"] == 10
    assert params["max_attempts"] == 7
```

- [ ] **步骤 2：运行测试验证失败**

运行：

```bash
cd backend
pytest tests/test_ingestion_job_queue.py::test_enqueue_job_uses_type_and_key_as_idempotency_boundary -q
```

预期：FAIL，`ModuleNotFoundError: No module named 'app.data_pipeline.job_queue'`。

- [ ] **步骤 3：实现队列服务最小 API**

创建 `backend/app/data_pipeline/job_queue.py`：

```python
"""Durable PostgreSQL-backed ingestion job queue."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text

from app.core.database import engine


JOB_PENDING = "pending"
JOB_RUNNING = "running"
JOB_SUCCESS = "success"
JOB_PARTIAL = "partial"
JOB_FAILED = "failed"
JOB_DEAD = "dead"

JOB_CNINFO_ANNOUNCEMENT_DATE = "cninfo_announcement_date"
JOB_IRM_COMPANY = "irm_company"


@dataclass(frozen=True)
class IngestionJobRecord:
    id: int
    job_type: str
    job_key: str
    status: str
    payload: dict[str, Any]
    priority: int
    attempt_count: int
    max_attempts: int


class IngestionJobQueue:
    async def enqueue_job(
        self,
        job_type: str,
        job_key: str,
        payload: dict[str, Any],
        priority: int = 100,
        max_attempts: int = 5,
        next_run_at: datetime | None = None,
    ) -> None:
        run_at = next_run_at or datetime.now(timezone.utc)
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    """
                    INSERT INTO ingestion_jobs (
                        job_type, job_key, status, payload, priority,
                        max_attempts, next_run_at, updated_at
                    ) VALUES (
                        :job_type, :job_key, 'pending', CAST(:payload AS jsonb), :priority,
                        :max_attempts, :next_run_at, NOW()
                    )
                    ON CONFLICT (job_type, job_key) DO UPDATE SET
                        payload = EXCLUDED.payload,
                        priority = LEAST(ingestion_jobs.priority, EXCLUDED.priority),
                        max_attempts = GREATEST(ingestion_jobs.max_attempts, EXCLUDED.max_attempts),
                        next_run_at = CASE
                            WHEN ingestion_jobs.status IN ('success', 'running') THEN ingestion_jobs.next_run_at
                            ELSE LEAST(ingestion_jobs.next_run_at, EXCLUDED.next_run_at)
                        END,
                        status = CASE
                            WHEN ingestion_jobs.status = 'dead' THEN 'pending'
                            ELSE ingestion_jobs.status
                        END,
                        updated_at = NOW()
                    """
                ),
                {
                    "job_type": job_type,
                    "job_key": job_key,
                    "payload": json.dumps(payload, ensure_ascii=False),
                    "priority": priority,
                    "max_attempts": max_attempts,
                    "next_run_at": run_at,
                },
            )

    async def claim_jobs(self, worker_id: str, limit: int = 20) -> list[IngestionJobRecord]:
        async with engine.begin() as conn:
            rows = (
                await conn.execute(
                    text(
                        """
                        WITH picked AS (
                            SELECT id
                            FROM ingestion_jobs
                            WHERE status IN ('pending', 'failed')
                              AND next_run_at <= NOW()
                            ORDER BY priority ASC, next_run_at ASC, id ASC
                            FOR UPDATE SKIP LOCKED
                            LIMIT :limit
                        )
                        UPDATE ingestion_jobs j
                        SET status = 'running',
                            locked_by = :worker_id,
                            locked_at = NOW(),
                            updated_at = NOW()
                        FROM picked
                        WHERE j.id = picked.id
                        RETURNING j.id, j.job_type, j.job_key, j.status, j.payload,
                                  j.priority, j.attempt_count, j.max_attempts
                        """
                    ),
                    {"worker_id": worker_id, "limit": limit},
                )
            ).mappings().all()
        return [
            IngestionJobRecord(
                id=row["id"],
                job_type=row["job_type"],
                job_key=row["job_key"],
                status=row["status"],
                payload=dict(row["payload"] or {}),
                priority=row["priority"],
                attempt_count=row["attempt_count"],
                max_attempts=row["max_attempts"],
            )
            for row in rows
        ]

    async def mark_success(self, job_id: int, result_summary: dict[str, Any]) -> None:
        await self._finish(job_id, JOB_SUCCESS, result_summary=result_summary, error=None)

    async def mark_partial(self, job_id: int, result_summary: dict[str, Any], error: str | None = None) -> None:
        await self._finish(job_id, JOB_PARTIAL, result_summary=result_summary, error=error)

    async def mark_failure(self, job_id: int, error: str, attempt_count: int, max_attempts: int) -> None:
        next_attempt = attempt_count + 1
        status = JOB_DEAD if next_attempt >= max_attempts else JOB_FAILED
        delay_minutes = min(60, 2 ** max(0, next_attempt - 1))
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    """
                    UPDATE ingestion_jobs
                    SET status = :status,
                        attempt_count = :attempt_count,
                        next_run_at = NOW() + (:delay_minutes * INTERVAL '1 minute'),
                        locked_at = NULL,
                        locked_by = NULL,
                        last_error = :error,
                        updated_at = NOW()
                    WHERE id = :job_id
                    """
                ),
                {
                    "job_id": job_id,
                    "status": status,
                    "attempt_count": next_attempt,
                    "delay_minutes": delay_minutes,
                    "error": error[:4000],
                },
            )

    async def _finish(
        self,
        job_id: int,
        status: str,
        result_summary: dict[str, Any],
        error: str | None,
    ) -> None:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    """
                    UPDATE ingestion_jobs
                    SET status = :status,
                        result_summary = CAST(:result_summary AS jsonb),
                        locked_at = NULL,
                        locked_by = NULL,
                        last_error = :error,
                        updated_at = NOW()
                    WHERE id = :job_id
                    """
                ),
                {
                    "job_id": job_id,
                    "status": status,
                    "result_summary": json.dumps(result_summary, ensure_ascii=False),
                    "error": error[:4000] if error else None,
                },
            )

    async def requeue_stale_running(self, older_than_minutes: int = 60) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=older_than_minutes)
        async with engine.begin() as conn:
            result = await conn.execute(
                text(
                    """
                    UPDATE ingestion_jobs
                    SET status = 'failed',
                        locked_at = NULL,
                        locked_by = NULL,
                        last_error = 'worker lock expired',
                        next_run_at = NOW(),
                        updated_at = NOW()
                    WHERE status = 'running'
                      AND locked_at < :cutoff
                    """
                ),
                {"cutoff": cutoff},
            )
        return int(result.rowcount or 0)
```

- [ ] **步骤 4：运行 enqueue 测试验证通过**

运行：

```bash
cd backend
pytest tests/test_ingestion_job_queue.py::test_enqueue_job_uses_type_and_key_as_idempotency_boundary -q
```

预期：`1 passed`。

- [ ] **步骤 5：编写 claim SQL 测试**

追加到 `backend/tests/test_ingestion_job_queue.py`：

```python
def test_claim_jobs_uses_skip_locked(monkeypatch) -> None:
    from app.data_pipeline.job_queue import IngestionJobQueue

    executed = []

    class FakeRows:
        def mappings(self):
            return self

        def all(self):
            return [{
                "id": 1,
                "job_type": "irm_company",
                "job_key": "600000.SH",
                "status": "running",
                "payload": {"ts_code": "600000.SH"},
                "priority": 50,
                "attempt_count": 0,
                "max_attempts": 5,
            }]

    class FakeConn:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def execute(self, sql, params):
            executed.append((str(sql), params))
            return FakeRows()

    fake_engine = MagicMock()
    fake_engine.begin.return_value = FakeConn()
    monkeypatch.setattr("app.data_pipeline.job_queue.engine", fake_engine)

    jobs = asyncio.run(IngestionJobQueue().claim_jobs("worker-a", limit=10))

    assert "FOR UPDATE SKIP LOCKED" in executed[0][0]
    assert executed[0][1] == {"worker_id": "worker-a", "limit": 10}
    assert jobs[0].job_type == "irm_company"
    assert jobs[0].payload == {"ts_code": "600000.SH"}
```

- [ ] **步骤 6：运行 claim 测试验证通过**

运行：

```bash
cd backend
pytest tests/test_ingestion_job_queue.py::test_claim_jobs_uses_skip_locked -q
```

预期：`1 passed`。

- [ ] **步骤 7：Commit**

```bash
git add backend/app/data_pipeline/job_queue.py backend/tests/test_ingestion_job_queue.py
git commit -m "feat: implement ingestion job queue service"
```

---

## 任务 3：公告与互动易 Job Producer

**文件：**
- 创建：`backend/app/data_pipeline/job_producers.py`
- 创建：`backend/tests/test_ingestion_job_producers.py`

- [ ] **步骤 1：编写公告最近 7 天 producer 红灯测试**

创建 `backend/tests/test_ingestion_job_producers.py`：

```python
"""Tests for ingestion job producers."""
from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytz


def test_enqueue_recent_cninfo_jobs_defaults_to_7_days(monkeypatch) -> None:
    from app.data_pipeline.job_producers import enqueue_recent_cninfo_jobs
    from app.data_pipeline.job_queue import JOB_CNINFO_ANNOUNCEMENT_DATE

    queue = MagicMock()
    queue.enqueue_job = AsyncMock()
    now = pytz.timezone("Asia/Shanghai").localize(datetime(2026, 5, 23, 14, 0, 0))

    asyncio.run(enqueue_recent_cninfo_jobs(queue=queue, now=now))

    keys = [call.kwargs["job_key"] for call in queue.enqueue_job.await_args_list]
    assert keys == [
        "20260517",
        "20260518",
        "20260519",
        "20260520",
        "20260521",
        "20260522",
        "20260523",
    ]
    assert all(call.kwargs["job_type"] == JOB_CNINFO_ANNOUNCEMENT_DATE for call in queue.enqueue_job.await_args_list)
    assert queue.enqueue_job.await_args_list[-1].kwargs["payload"] == {"date": "20260523"}
```

- [ ] **步骤 2：运行公告 producer 测试验证失败**

运行：

```bash
cd backend
pytest tests/test_ingestion_job_producers.py::test_enqueue_recent_cninfo_jobs_defaults_to_7_days -q
```

预期：FAIL，`ModuleNotFoundError`。

- [ ] **步骤 3：实现 producer**

创建 `backend/app/data_pipeline/job_producers.py`：

```python
"""Producers that enqueue ingestion jobs without doing external IO."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import pytz

from app.data_pipeline.data_source import DataSourceClient
from app.data_pipeline.job_queue import (
    JOB_CNINFO_ANNOUNCEMENT_DATE,
    JOB_IRM_COMPANY,
    IngestionJobQueue,
)


SH_TZ = pytz.timezone("Asia/Shanghai")


async def enqueue_recent_cninfo_jobs(
    queue: IngestionJobQueue | None = None,
    days: int = 7,
    now: datetime | None = None,
) -> dict[str, int]:
    queue = queue or IngestionJobQueue()
    current = now or datetime.now(SH_TZ)
    start = current.date() - timedelta(days=days - 1)
    count = 0
    for offset in range(days):
        day = start + timedelta(days=offset)
        date_key = day.strftime("%Y%m%d")
        await queue.enqueue_job(
            job_type=JOB_CNINFO_ANNOUNCEMENT_DATE,
            job_key=date_key,
            payload={"date": date_key},
            priority=10 + offset,
            max_attempts=8,
        )
        count += 1
    return {"enqueued": count}


async def enqueue_irm_company_jobs(
    queue: IngestionJobQueue | None = None,
    data_source: DataSourceClient | None = None,
    refresh_all: bool = True,
) -> dict[str, int]:
    queue = queue or IngestionJobQueue()
    data_source = data_source or DataSourceClient()
    stocks = await asyncio.to_thread(data_source.get_stocks_basic, "L")
    count = 0
    for stock in stocks:
        ts_code = stock.get("ts_code")
        if not ts_code:
            continue
        await queue.enqueue_job(
            job_type=JOB_IRM_COMPANY,
            job_key=ts_code,
            payload={"ts_code": ts_code, "refresh_all": refresh_all},
            priority=50,
            max_attempts=5,
        )
        count += 1
    return {"enqueued": count}
```

- [ ] **步骤 4：运行公告 producer 测试验证通过**

运行：

```bash
cd backend
pytest tests/test_ingestion_job_producers.py::test_enqueue_recent_cninfo_jobs_defaults_to_7_days -q
```

预期：`1 passed`。

- [ ] **步骤 5：编写互动易 producer 测试**

追加到 `backend/tests/test_ingestion_job_producers.py`：

```python
def test_enqueue_irm_company_jobs_uses_stock_list(monkeypatch) -> None:
    from app.data_pipeline.job_producers import enqueue_irm_company_jobs
    from app.data_pipeline.job_queue import JOB_IRM_COMPANY

    queue = MagicMock()
    queue.enqueue_job = AsyncMock()
    data_source = MagicMock()
    data_source.get_stocks_basic.return_value = [
        {"ts_code": "600000.SH"},
        {"ts_code": "000001.SZ"},
        {"ts_code": ""},
    ]

    result = asyncio.run(enqueue_irm_company_jobs(queue=queue, data_source=data_source))

    assert result == {"enqueued": 2}
    assert [call.kwargs["job_key"] for call in queue.enqueue_job.await_args_list] == ["600000.SH", "000001.SZ"]
    assert all(call.kwargs["job_type"] == JOB_IRM_COMPANY for call in queue.enqueue_job.await_args_list)
```

- [ ] **步骤 6：运行 producer 测试验证通过**

运行：

```bash
cd backend
pytest tests/test_ingestion_job_producers.py -q
```

预期：`2 passed`。

- [ ] **步骤 7：Commit**

```bash
git add backend/app/data_pipeline/job_producers.py backend/tests/test_ingestion_job_producers.py
git commit -m "feat: enqueue cninfo and irm ingestion jobs"
```

---

## 任务 4：Job Handler 派发执行

**文件：**
- 创建：`backend/app/data_pipeline/job_handlers.py`
- 创建：`backend/tests/test_ingestion_job_worker.py`

- [ ] **步骤 1：编写公告 handler 红灯测试**

创建 `backend/tests/test_ingestion_job_worker.py`：

```python
"""Tests for ingestion job handlers and worker."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock


def test_handler_runs_cninfo_date_job() -> None:
    from app.data_pipeline.job_handlers import execute_ingestion_job
    from app.data_pipeline.job_queue import (
        JOB_CNINFO_ANNOUNCEMENT_DATE,
        IngestionJobRecord,
    )

    fetcher = MagicMock()
    fetcher.fetch_announcements = AsyncMock(return_value={
        "total": 1831,
        "success": 1831,
        "skipped": 0,
        "downloaded": 10,
        "fail": 0,
    })
    job = IngestionJobRecord(
        id=1,
        job_type=JOB_CNINFO_ANNOUNCEMENT_DATE,
        job_key="20260523",
        status="running",
        payload={"date": "20260523"},
        priority=10,
        attempt_count=0,
        max_attempts=5,
    )

    result = asyncio.run(execute_ingestion_job(job, fetcher=fetcher))

    fetcher.fetch_announcements.assert_awaited_once_with(ann_date="20260523")
    assert result.status == "success"
    assert result.summary["success"] == 1831
```

- [ ] **步骤 2：运行公告 handler 测试验证失败**

运行：

```bash
cd backend
pytest tests/test_ingestion_job_worker.py::test_handler_runs_cninfo_date_job -q
```

预期：FAIL，`ModuleNotFoundError: No module named 'app.data_pipeline.job_handlers'`。

- [ ] **步骤 3：实现 handler**

创建 `backend/app/data_pipeline/job_handlers.py`：

```python
"""Execution handlers for durable ingestion jobs."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.data_pipeline.fetcher import DataFetcher
from app.data_pipeline.job_queue import (
    JOB_CNINFO_ANNOUNCEMENT_DATE,
    JOB_IRM_COMPANY,
    JOB_PARTIAL,
    JOB_SUCCESS,
    IngestionJobRecord,
)


@dataclass(frozen=True)
class JobExecutionResult:
    status: str
    summary: dict[str, Any]
    error: str | None = None


async def execute_ingestion_job(
    job: IngestionJobRecord,
    fetcher: DataFetcher | None = None,
) -> JobExecutionResult:
    fetcher = fetcher or DataFetcher()
    if job.job_type == JOB_CNINFO_ANNOUNCEMENT_DATE:
        date_key = str(job.payload["date"])
        result = await fetcher.fetch_announcements(ann_date=date_key)
        return _result_from_fetcher_result(result)
    if job.job_type == JOB_IRM_COMPANY:
        ts_code = str(job.payload["ts_code"])
        result = await fetcher.fetch_irm(ts_codes=[ts_code], extract_to_kg=False)
        return _result_from_fetcher_result(result)
    raise ValueError(f"unsupported ingestion job_type: {job.job_type}")


def _result_from_fetcher_result(result: dict[str, Any]) -> JobExecutionResult:
    fail = int(result.get("fail", 0) or 0)
    status = JOB_SUCCESS if fail == 0 else JOB_PARTIAL
    error = None if fail == 0 else f"fetcher returned fail={fail}"
    return JobExecutionResult(status=status, summary=result, error=error)
```

- [ ] **步骤 4：运行公告 handler 测试验证通过**

运行：

```bash
cd backend
pytest tests/test_ingestion_job_worker.py::test_handler_runs_cninfo_date_job -q
```

预期：`1 passed`。

- [ ] **步骤 5：编写互动易 handler 测试**

追加到 `backend/tests/test_ingestion_job_worker.py`：

```python
def test_handler_runs_irm_company_job() -> None:
    from app.data_pipeline.job_handlers import execute_ingestion_job
    from app.data_pipeline.job_queue import JOB_IRM_COMPANY, IngestionJobRecord

    fetcher = MagicMock()
    fetcher.fetch_irm = AsyncMock(return_value={
        "total": 1,
        "success": 2,
        "fail": 0,
        "skipped": 0,
        "duplicates": 1,
        "invalid": 0,
        "fetched_records": 3,
    })
    job = IngestionJobRecord(
        id=2,
        job_type=JOB_IRM_COMPANY,
        job_key="600000.SH",
        status="running",
        payload={"ts_code": "600000.SH"},
        priority=50,
        attempt_count=0,
        max_attempts=5,
    )

    result = asyncio.run(execute_ingestion_job(job, fetcher=fetcher))

    fetcher.fetch_irm.assert_awaited_once_with(ts_codes=["600000.SH"], extract_to_kg=False)
    assert result.status == "success"
    assert result.summary["fetched_records"] == 3
```

- [ ] **步骤 6：运行 handler 测试验证通过**

运行：

```bash
cd backend
pytest tests/test_ingestion_job_worker.py::test_handler_runs_cninfo_date_job tests/test_ingestion_job_worker.py::test_handler_runs_irm_company_job -q
```

预期：`2 passed`。

- [ ] **步骤 7：Commit**

```bash
git add backend/app/data_pipeline/job_handlers.py backend/tests/test_ingestion_job_worker.py
git commit -m "feat: execute ingestion jobs through handlers"
```

---

## 任务 5：Worker 领取、执行、重试

**文件：**
- 创建：`backend/app/data_pipeline/job_worker.py`
- 创建：`backend/scripts/ingestion_worker.py`
- 修改：`backend/tests/test_ingestion_job_worker.py`

- [ ] **步骤 1：编写 worker 成功路径测试**

追加到 `backend/tests/test_ingestion_job_worker.py`：

```python
def test_worker_marks_success(monkeypatch) -> None:
    from app.data_pipeline.job_queue import JOB_CNINFO_ANNOUNCEMENT_DATE, IngestionJobRecord
    from app.data_pipeline.job_worker import IngestionJobWorker

    job = IngestionJobRecord(
        id=1,
        job_type=JOB_CNINFO_ANNOUNCEMENT_DATE,
        job_key="20260523",
        status="running",
        payload={"date": "20260523"},
        priority=10,
        attempt_count=0,
        max_attempts=5,
    )
    queue = MagicMock()
    queue.claim_jobs = AsyncMock(return_value=[job])
    queue.mark_success = AsyncMock()
    queue.mark_partial = AsyncMock()
    queue.mark_failure = AsyncMock()

    async def fake_execute(job, fetcher=None):
        from app.data_pipeline.job_handlers import JobExecutionResult
        return JobExecutionResult(status="success", summary={"success": 1})

    monkeypatch.setattr("app.data_pipeline.job_worker.execute_ingestion_job", fake_execute)

    result = asyncio.run(IngestionJobWorker(queue=queue, worker_id="test-worker").run_once(limit=5))

    assert result == {"claimed": 1, "success": 1, "partial": 0, "failed": 0}
    queue.claim_jobs.assert_awaited_once_with("test-worker", limit=5)
    queue.mark_success.assert_awaited_once_with(1, {"success": 1})
```

- [ ] **步骤 2：运行 worker 测试验证失败**

运行：

```bash
cd backend
pytest tests/test_ingestion_job_worker.py::test_worker_marks_success -q
```

预期：FAIL，`ModuleNotFoundError: No module named 'app.data_pipeline.job_worker'`。

- [ ] **步骤 3：实现 worker**

创建 `backend/app/data_pipeline/job_worker.py`：

```python
"""Worker for durable ingestion jobs."""
from __future__ import annotations

import asyncio
import socket
import uuid

from app.data_pipeline.job_handlers import execute_ingestion_job
from app.data_pipeline.job_queue import (
    JOB_PARTIAL,
    JOB_SUCCESS,
    IngestionJobQueue,
    IngestionJobRecord,
)


class IngestionJobWorker:
    def __init__(
        self,
        queue: IngestionJobQueue | None = None,
        worker_id: str | None = None,
        job_timeout_seconds: int = 300,
    ) -> None:
        self.queue = queue or IngestionJobQueue()
        self.worker_id = worker_id or f"{socket.gethostname()}-{uuid.uuid4().hex[:8]}"
        self.job_timeout_seconds = job_timeout_seconds

    async def run_once(self, limit: int = 20) -> dict[str, int]:
        await self.queue.requeue_stale_running(older_than_minutes=60)
        jobs = await self.queue.claim_jobs(self.worker_id, limit=limit)
        counters = {"claimed": len(jobs), "success": 0, "partial": 0, "failed": 0}
        for job in jobs:
            await self._run_job(job, counters)
        return counters

    async def run_loop(self, limit: int = 20, interval_seconds: float = 5.0) -> None:
        while True:
            result = await self.run_once(limit=limit)
            if result["claimed"] == 0:
                await asyncio.sleep(interval_seconds)

    async def _run_job(self, job: IngestionJobRecord, counters: dict[str, int]) -> None:
        try:
            result = await asyncio.wait_for(
                execute_ingestion_job(job),
                timeout=self.job_timeout_seconds,
            )
            if result.status == JOB_SUCCESS:
                await self.queue.mark_success(job.id, result.summary)
                counters["success"] += 1
            elif result.status == JOB_PARTIAL:
                await self.queue.mark_partial(job.id, result.summary, result.error)
                counters["partial"] += 1
            else:
                await self.queue.mark_failure(job.id, result.error or result.status, job.attempt_count, job.max_attempts)
                counters["failed"] += 1
        except Exception as exc:
            await self.queue.mark_failure(job.id, str(exc), job.attempt_count, job.max_attempts)
            counters["failed"] += 1
```

- [ ] **步骤 4：创建 CLI 入口**

创建 `backend/scripts/ingestion_worker.py`：

```python
#!/usr/bin/env python3
"""Run durable ingestion job worker."""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.data_pipeline.job_worker import IngestionJobWorker


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--interval", type=float, default=5.0)
    parser.add_argument("--timeout", type=int, default=300)
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    worker = IngestionJobWorker(job_timeout_seconds=args.timeout)
    if args.once:
        result = await worker.run_once(limit=args.limit)
        print(result)
    else:
        await worker.run_loop(limit=args.limit, interval_seconds=args.interval)


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **步骤 5：运行 worker 测试验证通过**

运行：

```bash
cd backend
pytest tests/test_ingestion_job_worker.py::test_worker_marks_success -q
```

预期：`1 passed`。

- [ ] **步骤 6：编写 worker 失败重试测试**

追加到 `backend/tests/test_ingestion_job_worker.py`：

```python
def test_worker_marks_failure_on_exception(monkeypatch) -> None:
    from app.data_pipeline.job_queue import JOB_CNINFO_ANNOUNCEMENT_DATE, IngestionJobRecord
    from app.data_pipeline.job_worker import IngestionJobWorker

    job = IngestionJobRecord(
        id=3,
        job_type=JOB_CNINFO_ANNOUNCEMENT_DATE,
        job_key="20260522",
        status="running",
        payload={"date": "20260522"},
        priority=10,
        attempt_count=2,
        max_attempts=5,
    )
    queue = MagicMock()
    queue.claim_jobs = AsyncMock(return_value=[job])
    queue.mark_failure = AsyncMock()
    queue.requeue_stale_running = AsyncMock(return_value=0)

    async def fake_execute(job, fetcher=None):
        raise RuntimeError("cninfo 599")

    monkeypatch.setattr("app.data_pipeline.job_worker.execute_ingestion_job", fake_execute)

    result = asyncio.run(IngestionJobWorker(queue=queue, worker_id="test-worker").run_once(limit=1))

    assert result == {"claimed": 1, "success": 0, "partial": 0, "failed": 1}
    queue.mark_failure.assert_awaited_once_with(3, "cninfo 599", 2, 5)
```

- [ ] **步骤 7：运行 worker 全部测试**

运行：

```bash
cd backend
pytest tests/test_ingestion_job_worker.py -q
```

预期：`4 passed`。

- [ ] **步骤 8：Commit**

```bash
git add backend/app/data_pipeline/job_worker.py backend/scripts/ingestion_worker.py backend/tests/test_ingestion_job_worker.py
git commit -m "feat: add ingestion job worker"
```

---

## 任务 6：Scheduler 改为生产队列与 drain 队列

**文件：**
- 修改：`backend/app/data_pipeline/scheduler.py`
- 修改：`backend/tests/test_phase31_scheduler.py`

- [ ] **步骤 1：编写 scheduler 公告 enqueue 测试**

在 `backend/tests/test_phase31_scheduler.py` 追加或修改对应测试：

```python
def test_cninfo_scheduler_enqueues_recent_jobs(monkeypatch):
    import asyncio
    import app.data_pipeline.scheduler as scheduler_mod

    called = {}

    async def fake_enqueue(days=7):
        called["days"] = days
        return {"enqueued": days}

    monkeypatch.setattr(scheduler_mod, "enqueue_recent_cninfo_jobs", fake_enqueue)

    asyncio.run(scheduler_mod._run_cninfo_enqueue_job())

    assert called == {"days": 7}
```

- [ ] **步骤 2：运行 scheduler 测试验证失败**

运行：

```bash
cd backend
pytest tests/test_phase31_scheduler.py::test_cninfo_scheduler_enqueues_recent_jobs -q
```

预期：FAIL，`_run_cninfo_enqueue_job` 不存在。

- [ ] **步骤 3：修改 scheduler imports 和 job 函数**

在 `backend/app/data_pipeline/scheduler.py` 顶部普通 import 区域添加：

```python
from app.data_pipeline.job_producers import enqueue_irm_company_jobs, enqueue_recent_cninfo_jobs
from app.data_pipeline.job_worker import IngestionJobWorker
```

在 `_run_cninfo_job` 附近新增：

```python
async def _run_cninfo_enqueue_job() -> None:
    from app.data_pipeline.monitor import record_task_start, record_task_result, TaskStatus, init_monitor

    await init_monitor()
    await record_task_start("cninfo_enqueue")
    try:
        result = await enqueue_recent_cninfo_jobs(days=7)
        await record_task_result(
            "cninfo_enqueue",
            TaskStatus.SUCCESS,
            total=result.get("enqueued", 0),
            success=result.get("enqueued", 0),
            fail=0,
        )
    except Exception as exc:
        await record_task_result("cninfo_enqueue", TaskStatus.FAILED, error_message=str(exc))
        raise


async def _run_irm_enqueue_job() -> None:
    from app.data_pipeline.monitor import record_task_start, record_task_result, TaskStatus, init_monitor

    await init_monitor()
    await record_task_start("irm_enqueue")
    try:
        result = await enqueue_irm_company_jobs()
        await record_task_result(
            "irm_enqueue",
            TaskStatus.SUCCESS,
            total=result.get("enqueued", 0),
            success=result.get("enqueued", 0),
            fail=0,
        )
    except Exception as exc:
        await record_task_result("irm_enqueue", TaskStatus.FAILED, error_message=str(exc))
        raise


async def _run_ingestion_worker_job() -> None:
    result = await IngestionJobWorker(job_timeout_seconds=300).run_once(limit=20)
    logger.info("[ingestion_worker] drain result: %s", result)
```

In `Scheduler.start()`, replace cron registration for `_run_irm_job` and `_run_cninfo_job` with enqueue jobs:

```python
self._scheduler.add_job(
    _run_irm_enqueue_job,
    CronTrigger(hour=IRM_HOUR, minute=0, timezone=TIMEZONE),
    id="irm_enqueue_daily",
    replace_existing=True,
)
self._scheduler.add_job(
    _run_cninfo_enqueue_job,
    CronTrigger(hour=CNINFO_FETCH_HOUR, minute=0, timezone=TIMEZONE),
    id="cninfo_enqueue_daily",
    replace_existing=True,
)
self._scheduler.add_job(
    _run_ingestion_worker_job,
    CronTrigger(minute="*/5", timezone=TIMEZONE),
    id="ingestion_worker_drain",
    replace_existing=True,
)
```

Keep `_run_irm_job` and `_run_cninfo_job` in the file as manual compatibility functions; do not register them in scheduler cron.

- [ ] **步骤 4：运行 scheduler 测试验证通过**

运行：

```bash
cd backend
pytest tests/test_phase31_scheduler.py::test_cninfo_scheduler_enqueues_recent_jobs -q
```

预期：`1 passed`。

- [ ] **步骤 5：编写 worker drain 注册测试**

追加到 `backend/tests/test_phase31_scheduler.py`：

```python
def test_scheduler_registers_ingestion_worker_drain(monkeypatch):
    from app.data_pipeline.scheduler import Scheduler

    registered_ids = []

    class FakeScheduler:
        running = False

        def add_job(self, *args, **kwargs):
            registered_ids.append(kwargs["id"])

        def start(self):
            return None

    scheduler = Scheduler(run_now=False)
    scheduler._scheduler = FakeScheduler()
    scheduler.start()

    assert "cninfo_enqueue_daily" in registered_ids
    assert "irm_enqueue_daily" in registered_ids
    assert "ingestion_worker_drain" in registered_ids
    assert "cninfo_daily" not in registered_ids
    assert "irm_daily" not in registered_ids
```

- [ ] **步骤 6：运行 scheduler 队列测试**

运行：

```bash
cd backend
pytest tests/test_phase31_scheduler.py::test_scheduler_registers_ingestion_worker_drain -q
```

预期：`1 passed`。

- [ ] **步骤 7：Commit**

```bash
git add backend/app/data_pipeline/scheduler.py backend/tests/test_phase31_scheduler.py
git commit -m "feat: schedule ingestion queue producers and worker"
```

---

## 任务 7：监控 API 暴露队列状态

**文件：**
- 修改：`backend/app/data_pipeline/api/monitor.py`
- 创建：`backend/tests/test_ingestion_job_monitor.py`

- [ ] **步骤 1：编写队列状态查询测试**

创建 `backend/tests/test_ingestion_job_monitor.py`：

```python
"""Tests for ingestion job monitor queries."""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock


def test_get_ingestion_job_summary_groups_by_type_and_status(monkeypatch) -> None:
    from app.data_pipeline.api.monitor import get_ingestion_job_summary

    class FakeRows:
        def mappings(self):
            return self

        def all(self):
            return [
                {"job_type": "cninfo_announcement_date", "status": "pending", "count": 2},
                {"job_type": "cninfo_announcement_date", "status": "failed", "count": 1},
                {"job_type": "irm_company", "status": "success", "count": 100},
            ]

    class FakeConn:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def execute(self, *args, **kwargs):
            return FakeRows()

    fake_engine = MagicMock()
    fake_engine.connect.return_value = FakeConn()
    monkeypatch.setattr("app.data_pipeline.api.monitor.engine", fake_engine)

    result = asyncio.run(get_ingestion_job_summary())

    assert result == {
        "cninfo_announcement_date": {"pending": 2, "failed": 1},
        "irm_company": {"success": 100},
    }
```

- [ ] **步骤 2：运行监控测试验证失败**

运行：

```bash
cd backend
pytest tests/test_ingestion_job_monitor.py::test_get_ingestion_job_summary_groups_by_type_and_status -q
```

预期：FAIL，`ImportError` 或属性不存在。

- [ ] **步骤 3：实现监控函数和 API**

在 `backend/app/data_pipeline/api/monitor.py` 添加：

```python
@router.get("/sync/jobs/summary")
async def get_ingestion_job_summary():
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    """
                    SELECT job_type, status, COUNT(*) AS count
                    FROM ingestion_jobs
                    GROUP BY job_type, status
                    ORDER BY job_type, status
                    """
                )
            )
        ).mappings().all()
    summary: dict[str, dict[str, int]] = {}
    for row in rows:
        summary.setdefault(row["job_type"], {})[row["status"]] = int(row["count"])
    return summary


@router.get("/sync/jobs/failures")
async def list_ingestion_job_failures(limit: int = 100):
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    """
                    SELECT id, job_type, job_key, status, attempt_count, max_attempts,
                           next_run_at, last_error, result_summary, updated_at
                    FROM ingestion_jobs
                    WHERE status IN ('failed', 'dead')
                    ORDER BY updated_at DESC
                    LIMIT :limit
                    """
                ),
                {"limit": min(max(limit, 1), 500)},
            )
        ).mappings().all()
    return [dict(row) for row in rows]
```

- [ ] **步骤 4：运行监控测试验证通过**

运行：

```bash
cd backend
pytest tests/test_ingestion_job_monitor.py -q
```

预期：`1 passed`。

- [ ] **步骤 5：Commit**

```bash
git add backend/app/data_pipeline/api/monitor.py backend/tests/test_ingestion_job_monitor.py
git commit -m "feat: expose ingestion job queue status"
```

---

## 任务 8：端到端验证与首次补齐运行

**文件：**
- 修改：无固定代码文件；执行迁移、生产 job、消费 job、验证数据。

- [ ] **步骤 1：运行目标单元测试套件**

运行：

```bash
cd backend
pytest \
  tests/test_ingestion_job_queue.py \
  tests/test_ingestion_job_producers.py \
  tests/test_ingestion_job_worker.py \
  tests/test_ingestion_job_monitor.py \
  tests/test_phase31_scheduler.py \
  -q
```

预期：新增和相关 scheduler 测试全部通过；已有异步 marker 警告可以记录，但不能有失败。

- [ ] **步骤 2：运行迁移**

运行：

```bash
cd backend
alembic upgrade head
```

预期：退出码 `0`，`ingestion_jobs` 表存在。

- [ ] **步骤 3：生成默认 7 天公告 job 和互动易 job**

运行：

```bash
cd backend
python - <<'PY'
import asyncio
from app.data_pipeline.job_producers import enqueue_recent_cninfo_jobs, enqueue_irm_company_jobs

async def main():
    print(await enqueue_recent_cninfo_jobs(days=7))
    print(await enqueue_irm_company_jobs())

asyncio.run(main())
PY
```

预期：
- 第一行：`{'enqueued': 7}`
- 第二行：`{'enqueued': <上市标的数量>}`，数量应大于 `5000`。

- [ ] **步骤 4：查看队列汇总**

运行：

```bash
cd backend
python - <<'PY'
import asyncio
from sqlalchemy import text
from app.core.database import engine

async def main():
    async with engine.connect() as conn:
        rows = await conn.execute(text("""
            SELECT job_type, status, COUNT(*) AS count
            FROM ingestion_jobs
            GROUP BY job_type, status
            ORDER BY job_type, status
        """))
        for row in rows.mappings():
            print(dict(row))

asyncio.run(main())
PY
```

预期：出现 `cninfo_announcement_date` 的 `pending` 计数 `7`，以及 `irm_company` 的 `pending` 计数。

- [ ] **步骤 5：先消费公告日期 job**

运行：

```bash
cd backend
python scripts/ingestion_worker.py --once --limit 7 --timeout 900
```

预期：
- 输出字典包含 `claimed`。
- 巨潮 `599` 日期会变为 `failed` 或 `dead` 前的 `failed`，不会被标记为 `success`。
- 成功日期会进入 `success`。

- [ ] **步骤 6：消费一小批互动易 job**

运行：

```bash
cd backend
python scripts/ingestion_worker.py --once --limit 20 --timeout 300
```

预期：
- 输出字典包含 `claimed: 20` 或队列剩余不足时小于 `20`。
- 成功股票进入 `success`，接口异常股票进入 `failed` 并设置 `next_run_at`。

- [ ] **步骤 7：验证公告补齐状态**

运行：

```bash
cd backend
python - <<'PY'
import asyncio
from sqlalchemy import text
from app.core.database import engine

async def main():
    async with engine.connect() as conn:
        rows = await conn.execute(text("""
            SELECT job_key AS date, status, attempt_count, last_error, result_summary
            FROM ingestion_jobs
            WHERE job_type = 'cninfo_announcement_date'
            ORDER BY job_key
        """))
        for row in rows.mappings():
            print(dict(row))

asyncio.run(main())
PY
```

预期：最近 7 天每个日期都有独立状态；失败日期可见 `last_error`，不会被全局最大日期掩盖。

- [ ] **步骤 8：验证互动易队列状态**

运行：

```bash
cd backend
python - <<'PY'
import asyncio
from sqlalchemy import text
from app.core.database import engine

async def main():
    async with engine.connect() as conn:
        rows = await conn.execute(text("""
            SELECT status, COUNT(*) AS count
            FROM ingestion_jobs
            WHERE job_type = 'irm_company'
            GROUP BY status
            ORDER BY status
        """))
        for row in rows.mappings():
            print(dict(row))

asyncio.run(main())
PY
```

预期：可以看到 `success/pending/failed` 分布；失败股票不再表现为永久 `running`。

- [ ] **步骤 9：Commit 验证脚本或文档调整**

如果执行过程中只产生数据库数据，不提交数据库状态。若新增了验证脚本或文档，运行：

```bash
git add <changed-files>
git commit -m "test: document ingestion queue verification"
```

---

## 自检

**规格覆盖度：**
- 队列表：任务 1、任务 2 覆盖。
- 公告默认 7 天 producer：任务 3 覆盖。
- 公告按日期独立状态和 599 重试：任务 4、任务 5、任务 8 覆盖。
- 互动易按股票 job：任务 3、任务 4、任务 5、任务 8 覆盖。
- worker 锁、重试、dead 状态：任务 2、任务 5 覆盖。
- scheduler 改为 enqueue 和 drain：任务 6 覆盖。
- 监控 API：任务 7 覆盖。

**占位符扫描：**
- 计划中没有未定义的函数名；所有新增函数和类在对应任务中定义。
- 计划中没有要求工程师自行补全的错误处理语句；失败、重试、dead、超时均有具体实现路径。

**类型一致性：**
- job 类型常量统一来自 `app.data_pipeline.job_queue`。
- `IngestionJobRecord` 字段在队列、handler、worker 测试中一致。
- handler 返回 `JobExecutionResult(status, summary, error)`，worker 按该接口处理。

---

## 2026-05-23 执行记录

**已完成：**
- 新增持久化 `ingestion_jobs` 队列表、ORM、producer、handler、worker、scheduler drain 和监控 API。
- 公告 producer 默认滚动生成最近 7 天日期 job。
- 互动易 producer 按公司股票代码生成 job，并过滤指数代码。
- K 线补齐逻辑按每只个股自身最新日期追赶，不再使用数据库全局最新日期。
- worker 使用 `FOR UPDATE SKIP LOCKED` 领取任务，完成/失败更新都校验 `locked_by`，避免旧 worker 覆盖新状态。
- `DataSourceClient.get_irm()` 遇到接口异常重新抛出，handler 将 `success=0, fail>0` 归类为 job failure，避免假成功。
- 修复 `AsyncAuditLogger` 的 asyncpg JSONB 参数绑定：使用 `CAST(:extra_data AS jsonb)`，不再使用 `:extra_data::jsonb`。

**验证命令：**

```bash
cd backend
pytest tests/test_ingestion_job_queue.py tests/test_ingestion_job_producers.py tests/test_ingestion_job_worker.py tests/test_ingestion_job_monitor.py tests/test_phase31_scheduler.py tests/test_phase31_fetcher.py::TestPerStockKlineCatchup::test_fetch_all_stocks_uses_per_stock_latest_date tests/test_phase31_fetcher.py::TestAkshareThrottleApplied::test_fetch_irm_counts_data_source_exception_as_failure tests/test_phase31_fetcher.py::TestAkshareThrottleApplied::test_data_source_get_irm_raises_on_fetch_error -q
pytest tests/test_reported_bugs.py::test_async_audit_logger_uses_asyncpg_safe_jsonb_cast -q
python -m py_compile app/data_pipeline/job_queue.py app/data_pipeline/job_producers.py app/data_pipeline/job_handlers.py app/data_pipeline/job_worker.py app/data_pipeline/scheduler.py app/data_pipeline/api/monitor.py scripts/ingestion_worker.py alembic/versions/022_add_ingestion_jobs.py
```

**当前数据库队列状态：**
- `cninfo_announcement_date`: `success=1`, `failed=6`。
- `irm_company`: `pending=5206`, `failed=1`。

**当前阻塞：**
- 6 个公告日期 job 失败原因是公告后处理触发 Hunyuan embedding API repeated `400 Bad Request`。
- 当前配置为 `HUNYUAN_EMBEDDING_URL=https://api.hunyuan.cloud.tencent.com/v1/embeddings`、`HUNYUAN_MODEL=hunyuan-embedding`、`EMBEDDING_DIMENSION=2560`。腾讯云公开文档中的原生混元 `GetEmbedding` 接口是 TencentCloud API 协议，返回 1024 维，和当前 OpenAI 风格 `/v1/embeddings` 代码路径不一致；需要单独修复 embedding provider 配置/适配后再重新 drain 公告队列。
- Alembic 当前数据库已有业务表但缺少 `alembic_version`，直接 `alembic upgrade head` 会从 `001` 重放并遇到 `stocks` duplicate table。未执行 `stamp` 或 reset，避免破坏现有数据库。
