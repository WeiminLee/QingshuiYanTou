# Evidence Pipeline 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 PostgreSQL 中的公告和互动易数据转为 MongoDB Evidence，建立追踪表，由 Worker 消费抽取到知识图谱

**Architecture:** 新增 `evidence_tracking` PostgreSQL 表追踪源数据 → Evidence 映射关系；新增 builder 函数从 `minishare_announcements` 和 `announcements`(irm) 构造 EvidenceInput；通过 EvidenceService 写入 MongoDB 并同步更新追踪表

**Tech Stack:** PostgreSQL (async SQLAlchemy), MongoDB (motor), Neo4j, existing EvidenceService/EvidenceExtractionWorker

**Spec:** `docs/superpowers/specs/2026-06-16-evidence-pipeline-design.md`

---

### Task 1: 添加 evidence_tracking 表

**Files:**
- Modify: `backend/scripts/init_database.py`

- [ ] **Step 1: 在 init_database.py 添加 evidence_tracking 建表语句**

在 `DDL_STATEMENTS` 列表末尾、`]` 之前添加：

```python
    """
    CREATE TABLE IF NOT EXISTS evidence_tracking (
        id SERIAL PRIMARY KEY,
        source_table VARCHAR(100) NOT NULL,
        source_id INTEGER NOT NULL,
        evidence_id VARCHAR(100) NOT NULL,
        chunk_index INTEGER DEFAULT 0,
        extraction_status VARCHAR(20) DEFAULT 'pending',
        created_at TIMESTAMP DEFAULT now(),
        updated_at TIMESTAMP DEFAULT now(),
        UNIQUE(source_table, source_id, chunk_index),
        UNIQUE(evidence_id)
    );
    CREATE INDEX IF NOT EXISTS idx_et_status ON evidence_tracking(extraction_status);
    CREATE INDEX IF NOT EXISTS idx_et_source ON evidence_tracking(source_table, source_id);
    """,
```

- [ ] **Step 2: 执行建表**

```bash
cd backend && .venv/bin/python scripts/init_database.py
```

- [ ] **Step 3: 验证表已创建**

```bash
cd backend && .venv/bin/python - <<'EOF'
import asyncio
from sqlalchemy import text
from app.core.database import engine

async def verify():
    async with engine.connect() as conn:
        r = await conn.execute(text("""
            SELECT column_name, data_type FROM information_schema.columns
            WHERE table_name='evidence_tracking' ORDER BY ordinal_position
        """))
        for row in r.fetchall():
            print(f"  {row[0]} ({row[1]})")

asyncio.run(verify())
EOF
```

- [ ] **Step 4: Commit**

```bash
git add backend/scripts/init_database.py
git commit -m "feat(db): add evidence_tracking table for source-to-evidence mapping"
```

---

### Task 2: 创建公告和互动易的 Evidence Builder

**Files:**
- Create: `backend/app/knowledge/evidence_builders_simple.py`

- [ ] **Step 1: 创建 evidence_builders_simple.py**

```python
"""Simple Evidence builders for short-text sources (announcements, IRM).

These builders do NOT chunk — each source record maps to exactly one Evidence.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.knowledge.evidence import EvidenceInput, default_source_confidence


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def build_announcement_evidence(
    record: dict[str, Any],
) -> EvidenceInput:
    """Build a single EvidenceInput from a minishare_announcements row.

    Each announcement title is treated as one complete semantic unit.
    """
    ann_id = record.get("id") or ""
    title = (record.get("title") or "").strip()
    ts_code = (record.get("ts_code") or "").strip()
    ann_date = record.get("ann_date")

    # 将 title 直接作为 text_excerpt（不分块）
    text = title
    source_id = str(ann_id)

    return EvidenceInput(
        source_type="announcement",
        source_name=f"公告:{ts_code}" if ts_code else "公告",
        source_id=source_id,
        text_excerpt=text,
        subject_hint={
            "ts_code": ts_code,
            "name": (record.get("name") or "").strip(),
            "ann_type": (record.get("type") or record.get("ann_types") or ""),
        },
        publish_date=ann_date,
        observed_at=_utc_now(),
        source_ref={
            "source_table": "minishare_announcements",
            "source_id": ann_id,
            "ann_date": ann_date,
            "source_url": (record.get("source_url") or ""),
        },
        confidence=default_source_confidence("announcement"),
        metadata={},
    )


def build_irm_evidence(
    record: dict[str, Any],
) -> EvidenceInput:
    """Build a single EvidenceInput from an announcements row (irm: type).

    Each Q&A is treated as one complete semantic unit.
    """
    ann_id = record.get("id") or ""
    question = (record.get("title") or "").strip()  # IRM stores question in title
    ts_code = (record.get("ts_code") or "").strip()
    ann_date = record.get("ann_date")
    ann_type = (record.get("announcement_type") or "")

    text = f"问题：{question}"
    source_id = str(ann_id)

    return EvidenceInput(
        source_type="irm",
        source_name=f"互动易:{ts_code}" if ts_code else "互动易",
        source_id=source_id,
        text_excerpt=text,
        subject_hint={
            "ts_code": ts_code,
            "name": (record.get("name") or "").strip(),
        },
        publish_date=ann_date,
        observed_at=_utc_now(),
        source_ref={
            "source_table": "announcements",
            "source_id": ann_id,
            "ann_date": ann_date,
            "ann_type": ann_type,
        },
        confidence=default_source_confidence("irm"),
        metadata={},
    )
```

- [ ] **Step 2: 语法检查**

```bash
cd backend && .venv/bin/python -m py_compile app/knowledge/evidence_builders_simple.py && echo "OK"
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/knowledge/evidence_builders_simple.py
git commit -m "feat(evidence): add simple builders for announcements and IRM (no chunking)"
```

---

### Task 3: 创建 Evidence Pipeline 核心函数

**Files:**
- Create: `backend/app/data_pipeline/evidence_pipeline.py`

- [ ] **Step 1: 创建 evidence_pipeline.py**

```python
"""Evidence Pipeline — 将 PostgreSQL 源数据转为 MongoDB Evidence + 追踪"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from app.core.database import engine
from app.knowledge.evidence import EVIDENCE_COLLECTION
from app.knowledge.evidence_service import EvidenceService
from app.knowledge.evidence_builders_simple import (
    build_announcement_evidence,
    build_irm_evidence,
)

logger = logging.getLogger(__name__)


async def _utc_now_str() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _upsert_tracking(
    source_table: str,
    source_id: int,
    evidence_id: str,
    chunk_index: int = 0,
) -> None:
    """写入/更新 evidence_tracking 表."""
    async with engine.begin() as conn:
        await conn.execute(
            text("""
                INSERT INTO evidence_tracking
                    (source_table, source_id, evidence_id, chunk_index, extraction_status, updated_at)
                VALUES
                    (:source_table, :source_id, :evidence_id, :chunk_index, 'pending', now())
                ON CONFLICT (source_table, source_id, chunk_index)
                DO UPDATE SET evidence_id = EXCLUDED.evidence_id,
                              updated_at = now()
            """),
            {
                "source_table": source_table,
                "source_id": source_id,
                "evidence_id": evidence_id,
                "chunk_index": chunk_index,
            },
        )


async def build_announcement_evidence_pipeline(
    limit: int | None = None,
    offset: int = 0,
) -> dict[str, int]:
    """从 minishare_announcements 构建 Evidence.

    Args:
        limit: 最大处理条数，None 表示全部
        offset: 起始偏移

    Returns:
        {"total": N, "created": N, "skipped": N, "failed": N}
    """
    service = EvidenceService()
    await service.ensure_indexes()

    async with engine.connect() as conn:
        # 查询未处理的记录（不在 evidence_tracking 中）
        query = """
            SELECT a.id, a.ann_date, a.ts_code, a.name, a.title, a.type, a.ann_types, a.source_url
            FROM minishare_announcements a
            WHERE a.id NOT IN (
                SELECT source_id FROM evidence_tracking WHERE source_table = 'minishare_announcements'
            )
            ORDER BY a.ann_date DESC
        """
        if limit is not None:
            query += f" LIMIT {int(limit)}"
        if offset:
            query += f" OFFSET {int(offset)}"

        rows = await conn.execute(text(query))
        records = [dict(r._mapping) for r in rows.fetchall()]

    total = len(records)
    created = skipped = failed = 0

    for rec in records:
        try:
            evidence_input = build_announcement_evidence(rec)
            result = await service.upsert_evidence(evidence_input, chunk_index=0)
            evidence_id = result.get("evidence_id") or ""

            await _upsert_tracking(
                source_table="minishare_announcements",
                source_id=int(rec["id"]),
                evidence_id=evidence_id,
                chunk_index=0,
            )

            # enqueue 两个默认 job: combined + vector
            await service.enqueue_default_jobs(evidence_id)

            # 检查是否为新创建（非 upsert 覆盖）
            created_at = result.get("created_at")
            if created_at and _is_recent(created_at):
                created += 1
            else:
                skipped += 1
        except Exception as e:
            failed += 1
            logger.warning(f"公告 Evidence 构建失败 [id={rec.get('id')}]: {e}")

    logger.info(f"公告 Evidence pipeline: total={total} created={created} skipped={skipped} failed={failed}")
    return {"total": total, "created": created, "skipped": skipped, "failed": failed}


async def build_irm_evidence_pipeline(
    limit: int | None = None,
    offset: int = 0,
) -> dict[str, int]:
    """从 announcements (irm:*) 构建 Evidence.

    Args:
        limit: 最大处理条数，None 表示全部
        offset: 起始偏移

    Returns:
        {"total": N, "created": N, "skipped": N, "failed": N}
    """
    service = EvidenceService()
    await service.ensure_indexes()

    async with engine.connect() as conn:
        query = """
            SELECT a.id, a.ann_date, a.ts_code, a.name, a.title, a.announcement_type
            FROM announcements a
            WHERE a.announcement_type LIKE 'irm:%'
              AND a.id NOT IN (
                  SELECT source_id FROM evidence_tracking WHERE source_table = 'announcements'
              )
            ORDER BY a.ann_date DESC
        """
        if limit is not None:
            query += f" LIMIT {int(limit)}"
        if offset:
            query += f" OFFSET {int(offset)}"

        rows = await conn.execute(text(query))
        records = [dict(r._mapping) for r in rows.fetchall()]

    total = len(records)
    created = skipped = failed = 0

    for rec in records:
        try:
            evidence_input = build_irm_evidence(rec)
            result = await service.upsert_evidence(evidence_input, chunk_index=0)
            evidence_id = result.get("evidence_id") or ""

            await _upsert_tracking(
                source_table="announcements",
                source_id=int(rec["id"]),
                evidence_id=evidence_id,
                chunk_index=0,
            )

            await service.enqueue_default_jobs(evidence_id)

            created_at = result.get("created_at")
            if created_at and _is_recent(created_at):
                created += 1
            else:
                skipped += 1
        except Exception as e:
            failed += 1
            logger.warning(f"互动易 Evidence 构建失败 [id={rec.get('id')}]: {e}")

    logger.info(f"互动易 Evidence pipeline: total={total} created={created} skipped={skipped} failed={failed}")
    return {"total": total, "created": created, "skipped": skipped, "failed": failed}


def _is_recent(created_at: Any) -> bool:
    """判断 evidence 是否刚刚创建（用于区分 insert vs upsert 覆盖）."""
    if created_at is None:
        return False
    if isinstance(created_at, datetime):
        delta = datetime.now(timezone.utc) - created_at
        return delta.total_seconds() < 5
    return True


async def get_pipeline_stats() -> dict[str, Any]:
    """查询 pipeline 进度统计."""
    async with engine.connect() as conn:
        r = await conn.execute(text("""
            SELECT
                source_table,
                count(*) as total,
                count(*) FILTER (WHERE extraction_status = 'pending') as pending,
                count(*) FILTER (WHERE extraction_status = 'running') as running,
                count(*) FILTER (WHERE extraction_status = 'done') as done,
                count(*) FILTER (WHERE extraction_status = 'failed') as failed
            FROM evidence_tracking
            GROUP BY source_table
        """))
        rows = [dict(r2._mapping) for r2 in r.fetchall()]

    evidence_service = EvidenceService()
    mongo_stats = await evidence_service.get_stats()

    return {
        "tracking": rows,
        "mongo": mongo_stats,
    }
```

- [ ] **Step 2: 语法检查**

```bash
cd backend && .venv/bin/python -m py_compile app/data_pipeline/evidence_pipeline.py && echo "OK"
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/data_pipeline/evidence_pipeline.py
git commit -m "feat(evidence): add pipeline to feed PostgreSQL data into MongoDB Evidence"
```

---

### Task 4: 试跑验证 — 10 条公告

**Files:**
- No new files; test via Python REPL

- [ ] **Step 1: 确保 uvicorn 运行中**

```bash
ps aux | grep uvicorn | grep -v grep || (cd backend && .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8080 > /tmp/uvicorn.log 2>&1 & sleep 4)
```

- [ ] **Step 2: 运行公告 pipeline（10 条）**

```bash
cd backend && .venv/bin/python - <<'EOF'
import asyncio
from app.data_pipeline.evidence_pipeline import build_announcement_evidence_pipeline

result = asyncio.run(build_announcement_evidence_pipeline(limit=10))
print(result)
EOF
```

Expected: `{"total": 10, "created": 10, "skipped": 0, "failed": 0}`

- [ ] **Step 3: 验证 MongoDB evidence**

```bash
cd backend && .venv/bin/python - <<'EOF'
import asyncio
from app.knowledge.evidence_service import EvidenceService

async def verify():
    svc = EvidenceService()
    stats = await svc.get_stats()
    print(f"Evidence: {stats['evidence']}, Jobs: {stats['jobs']}")
    print(f"Jobs by status: {stats['jobs_by_status']}")

asyncio.run(verify())
EOF
```

Expected: 10 evidence + 20 jobs (10 combined + 10 vector)

- [ ] **Step 4: 验证 PostgreSQL tracking**

```bash
cd backend && .venv/bin/python - <<'EOF'
import asyncio
from sqlalchemy import text
from app.core.database import engine

async def verify():
    async with engine.connect() as conn:
        r = await conn.execute(text("""
            SELECT source_table, count(*), 
                   count(*) FILTER (WHERE extraction_status='pending') as pending
            FROM evidence_tracking GROUP BY source_table
        """))
        for row in r.fetchall():
            print(f"  {row[0]}: {row[1]} rows, {row[2]} pending")

asyncio.run(verify())
EOF
```

- [ ] **Step 5: Commit 验证通过后的 checkpoint**

```bash
git add -A && git commit -m "test: evidence pipeline verified with 10 announcements"
```

---

### Task 5: 试跑验证 — 互动易（全部）

- [ ] **Step 1: 运行 IRM pipeline**

```bash
cd backend && .venv/bin/python - <<'EOF'
import asyncio
from app.data_pipeline.evidence_pipeline import build_irm_evidence_pipeline

result = asyncio.run(build_irm_evidence_pipeline())
print(result)
EOF
```

Expected: `total` 匹配数据库中 irm 记录数（约 23）

- [ ] **Step 2: 验证追踪和 MongoDB**

```bash
cd backend && .venv/bin/python - <<'EOF'
import asyncio
from app.data_pipeline.evidence_pipeline import get_pipeline_stats
result = asyncio.run(get_pipeline_stats())
print("=== Tracking ===")
for row in result['tracking']:
    print(f"  {row}")
print("\n=== MongoDB ===")
print(f"  evidence={result['mongo']['evidence']}, jobs={result['mongo']['jobs']}")
print(f"  jobs_by_status={result['mongo']['jobs_by_status']}")
EOF
```

- [ ] **Step 3: 重复运行公告 pipeline 验证幂等性**

```bash
cd backend && .venv/bin/python - <<'EOF'
import asyncio
from app.data_pipeline.evidence_pipeline import build_announcement_evidence_pipeline

# 再跑一次同样的 10 条 — 应该全部 skipped
result = asyncio.run(build_announcement_evidence_pipeline(limit=10))
print(result)
EOF
```

Expected: `total=0` (已经处理过的不会被重复查询)

- [ ] **Step 4: Commit**

```bash
git add -A && git commit -m "test: evidence pipeline verified for IRM, idempotency confirmed"
```

---

### Task 6: 启动 Worker 消费 Evidence Job

- [ ] **Step 1: 运行 EvidenceExtractionWorker 处理 pending jobs**

```bash
cd backend && .venv/bin/python - <<'EOF'
import asyncio
from app.knowledge.evidence_worker import EvidenceExtractionWorker

async def run():
    worker = EvidenceExtractionWorker(batch_size=2, max_concurrency=2)
    result = await worker.run_once(limit=4, job_type="combined")
    print(result)

asyncio.run(run())
EOF
```

- [ ] **Step 2: 验证 KG 抽取结果**

```bash
cd backend && .venv/bin/python - <<'EOF'
from app.core.neo4j_client import run

r = run("MATCH (n) RETURN labels(n)[0] as label, count(*) as cnt")
print("=== Neo4j 节点 ===")
for row in r:
    print(f"  {row['label']}: {row['cnt']}")

r2 = run("MATCH ()-[r]->() RETURN type(r) as rel, count(*) as cnt")
print("=== Neo4j 关系 ===")
for row in r2:
    print(f"  {row['rel']}: {row['cnt']}")
EOF
```

- [ ] **Step 3: 验证 tracking 状态已更新**

```bash
cd backend && .venv/bin/python - <<'EOF'
import asyncio
from app.data_pipeline.evidence_pipeline import get_pipeline_stats
result = asyncio.run(get_pipeline_stats())
for row in result['tracking']:
    print(f"  {row['source_table']}: total={row['total']} pending={row['pending']} running={row['running']} done={row['done']} failed={row['failed']}")
EOF
```

Expected: `done` 计数 > 0

- [ ] **Step 4: Commit**

```bash
git add -A && git commit -m "test: worker consumed evidence jobs, KG entities created in Neo4j"
```

---

### Task 7: 添加 API 端点触发 Pipeline

**Files:**
- Modify: `backend/app/data_pipeline/api/data_sync.py`

- [ ] **Step 1: 在 data_sync.py 添加 evidence 端点**

在文件末尾添加：

```python
# ── Evidence Pipeline ─────────────────────────────────────

@router.post("/evidence/build/announcements", response_model=SyncResponse)
async def build_announcement_evidence(
    limit: int = Query(default=100, description="单次处理条数"),
    offset: int = Query(default=0, description="偏移量"),
) -> SyncResponse:
    """从 minishare_announcements 构建 Evidence（只处理未追踪的记录）"""
    from app.data_pipeline.evidence_pipeline import build_announcement_evidence_pipeline

    result = await build_announcement_evidence_pipeline(limit=limit, offset=offset)
    return SyncResponse(
        task_id="sync",
        status="completed",
        message=f"公告 Evidence 构建完成: total={result['total']} created={result['created']} skipped={result['skipped']}",
        details=result,
    )


@router.post("/evidence/build/irm", response_model=SyncResponse)
async def build_irm_evidence(
    limit: int = Query(default=100, description="单次处理条数"),
    offset: int = Query(default=0, description="偏移量"),
) -> SyncResponse:
    """从 announcements (irm:*) 构建 Evidence（只处理未追踪的记录）"""
    from app.data_pipeline.evidence_pipeline import build_irm_evidence_pipeline

    result = await build_irm_evidence_pipeline(limit=limit, offset=offset)
    return SyncResponse(
        task_id="sync",
        status="completed",
        message=f"互动易 Evidence 构建完成: total={result['total']} created={result['created']} skipped={result['skipped']}",
        details=result,
    )


@router.get("/evidence/stats", response_model=dict)
async def get_evidence_stats() -> dict:
    """查询 Evidence pipeline 进度"""
    from app.data_pipeline.evidence_pipeline import get_pipeline_stats

    return await get_pipeline_stats()


@router.post("/evidence/worker/run", response_model=SyncResponse)
async def run_evidence_worker(
    limit: int = Query(default=10, description="最大处理 job 数"),
    job_type: str = Query(default="combined", description="combined | vector"),
) -> SyncResponse:
    """运行 EvidenceExtractionWorker 消费 pending jobs"""
    from app.knowledge.evidence_worker import EvidenceExtractionWorker

    worker = EvidenceExtractionWorker(batch_size=2, max_concurrency=2)
    result = await worker.run_once(limit=limit, job_type=job_type)
    return SyncResponse(
        task_id="sync",
        status="completed",
        message=f"Worker 完成: claimed={result['claimed']} success={result['success']}",
        details=result,
    )
```

- [ ] **Step 2: 重启 uvicorn 并测试端点**

```bash
pkill -f "uvicorn.*8080"; sleep 2
cd backend && .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8080 > /tmp/uvicorn.log 2>&1 &
sleep 5

source backend/.env 2>/dev/null
curl -s "http://localhost:8080/api/v1/sync/evidence/stats" -H "X-API-Key: ${API_KEY}" | python3 -m json.tool
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/data_pipeline/api/data_sync.py
git commit -m "feat(api): add evidence pipeline and worker endpoints"
```

---

### Task 8: 全量公告批量处理

- [ ] **Step 1: 逐批处理公告（每批 500 条）**

```bash
cd backend && .venv/bin/python - <<'EOF'
import asyncio
from app.data_pipeline.evidence_pipeline import build_announcement_evidence_pipeline

async def batch_all(batch_size=500):
    total = 0
    while True:
        result = await build_announcement_evidence_pipeline(limit=batch_size)
        total += result["total"]
        print(f"Batch: {result} | Cumulative: {total}")
        if result["total"] == 0:
            break

asyncio.run(batch_all())
EOF
```

- [ ] **Step 2: 验证最终统计**

```bash
curl -s "http://localhost:8080/api/v1/sync/evidence/stats" -H "X-API-Key: ${API_KEY}" | python3 -m json.tool
```

- [ ] **Step 3: Commit**

```bash
git add -A && git commit -m "feat: full announcement evidence pipeline completed"
```
