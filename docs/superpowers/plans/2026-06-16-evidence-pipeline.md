# Evidence Pipeline 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 PostgreSQL 中的公告（下载 PDF + 按章节分块）和互动易数据转为 MongoDB Evidence，建立追踪表，由 Worker 消费抽取到知识图谱

**Architecture:** 新增 `evidence_tracking` PostgreSQL 表；新增 PDF 下载器 + 章节切分器处理公告正文；新增 builder 函数；通过 EvidenceService 写入 MongoDB 并同步更新追踪表

**Tech Stack:** PostgreSQL (async SQLAlchemy), MongoDB (motor), pymupdf (PDF 解析), requests (PDF 下载), Neo4j, existing EvidenceService/EvidenceExtractionWorker

**Spec:** `docs/superpowers/specs/2026-06-16-evidence-pipeline-design.md`

---

### Task 1: 添加 evidence_tracking 表

**Files:**
- Modify: `backend/scripts/init_database.py`

- [ ] **Step 1: 在 init_database.py 添加 evidence_tracking 建表语句**

找到 `DDL_STATEMENTS` 列表末尾的 `]`，在其前一行添加：

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

- [ ] **Step 2: 执行建表并验证**

```bash
cd backend && .venv/bin/python scripts/init_database.py
.venv/bin/python - <<'EOF'
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

- [ ] **Step 3: Commit**

```bash
git add backend/scripts/init_database.py
git commit -m "feat(db): add evidence_tracking table for source-to-evidence mapping"
```

---

### Task 2: 创建公告 PDF 下载 + 章节切分模块

**Files:**
- Create: `backend/app/knowledge/ingestion/announcement_parser.py`

- [ ] **Step 1: 创建 announcement_parser.py**

```python
"""公告 PDF 下载与章节切分模块。

公告 PDF 来自 cninfo（无频率限制），通过 pymupdf 解析正文，
按中文序号标题（一、二、三）切分为章节。
"""
from __future__ import annotations

import logging
import re
from typing import Optional

import fitz  # pymupdf
import requests

logger = logging.getLogger(__name__)

HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

# 匹配 "一、标题" 或 "一.标题" 或 "一 标题" 格式的章节标题行
# 标题长度 2-50 字符，避免匹配页码中的单个数字
_HEADING_PATTERN = re.compile(
    r'(?:^|\n)\s*([一二三四五六七八九十]+)[、，。．\.\s]+([^\n]{2,50})\s*\n'
)


def download_announcement_pdf(url: str, timeout: int = 15) -> Optional[bytes]:
    """从 cninfo 下载公告 PDF。

    Returns:
        PDF 二进制内容，失败返回 None
    """
    if not url:
        return None
    try:
        resp = requests.get(url, timeout=timeout, headers=HTTP_HEADERS)
        resp.raise_for_status()
        content = resp.content
        if content[:5] != b"%PDF-":
            logger.warning(f"下载内容不是 PDF: {url[:80]}")
            return None
        return content
    except Exception as e:
        logger.warning(f"下载公告 PDF 失败 [{url[:80]}]: {e}")
        return None


def parse_pdf_text(pdf_content: bytes) -> str:
    """用 pymupdf 解析 PDF 正文。

    Returns:
        全文文本（多页合并，保留换行）
    """
    try:
        doc = fitz.open(stream=pdf_content, filetype="pdf")
        text_parts = []
        for page in doc:
            t = page.get_text()
            if t.strip():
                text_parts.append(t)
        doc.close()
        return "\n".join(text_parts)
    except Exception as e:
        logger.warning(f"PDF 解析失败: {e}")
        return ""


def split_by_chapters(text: str) -> list[dict]:
    """按中文序号标题切分章节。

    公告通常以"一、标题\n内容\n二、标题\n内容"格式组织。
    如果正文没有章节标题（如纯文本公告），则将全文作为一个 chunk。

    Returns:
        list of {"heading": str, "body": str}
        - heading: 章节标题（如 "一、股东会审议通过的权益分派方案等情况"），preamble 为空字符串
        - body: 该章节的正文文本
    """
    if not text.strip():
        return []

    matches = list(_HEADING_PATTERN.finditer(text))
    if not matches:
        # 无章节标题，全文作为一个 chunk
        return [{"heading": "", "body": text.strip()}]

    sections = []

    # Preamble：第一个标题之前的内容（如公司名称、公告编号等元信息）
    if matches[0].start() > 0:
        preamble = text[:matches[0].start()].strip()
        if preamble:
            sections.append({"heading": "", "body": preamble})

    # 各章节
    for i, m in enumerate(matches):
        start = m.start() + len(m.group(0))
        next_start = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        heading = f"{m.group(1)}、{m.group(2)}"
        body = text[start:next_start].strip()
        if body:
            sections.append({"heading": heading, "body": body})

    return sections
```

- [ ] **Step 2: 语法检查**

```bash
cd backend && .venv/bin/python -m py_compile app/knowledge/ingestion/announcement_parser.py && echo "OK"
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/knowledge/ingestion/announcement_parser.py
git commit -m "feat(ingestion): add announcement PDF downloader + chapter splitter"
```

---

### Task 3: 创建 Evidence Builder（公告章节版 + 互动易）

**Files:**
- Create: `backend/app/knowledge/evidence_builders_simple.py`

- [ ] **Step 1: 创建 evidence_builders_simple.py**

```python
"""Evidence builders for announcements (chapter-chunked) and IRM (unchunked).

公告: 下载 PDF → 按章节分块 → 每个章节一个 EvidenceInput
互动易: 每条 Q&A → 一个 EvidenceInput（不分块）
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.knowledge.evidence import EvidenceInput, default_source_confidence
from app.knowledge.ingestion.announcement_parser import (
    download_announcement_pdf,
    parse_pdf_text,
    split_by_chapters,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def build_announcement_evidence(
    record: dict[str, Any],
    download_pdf: bool = True,
) -> list[EvidenceInput]:
    """从 minishare_announcements 记录构建 EvidenceInput 列表。

    每个章节作为一个独立的 Evidence，通过 chunk_index 区分。

    Args:
        record: 数据库行（含 id, ann_date, ts_code, name, title, type, source_url 等）
        download_pdf: 是否下载 PDF（默认 True，失败时回退到 title-only）

    Returns:
        list[EvidenceInput]: 每个章节一个 EvidenceInput
    """
    ann_id = record.get("id") or ""
    title = (record.get("title") or "").strip()
    ts_code = (record.get("ts_code") or "").strip()
    ann_date = record.get("ann_date")
    ann_type = (record.get("type") or record.get("ann_types") or "")
    source_url = (record.get("source_url") or "")
    company_name = (record.get("name") or "").strip()

    source_id = str(ann_id)
    chapters: list[dict] = []

    # 尝试下载 PDF 并按章节分块
    if download_pdf and source_url:
        pdf_content = download_announcement_pdf(source_url)
        if pdf_content:
            full_text = parse_pdf_text(pdf_content)
            if full_text.strip():
                chapters = split_by_chapters(full_text)

    # 回退：PDF 不可用时只用 title
    if not chapters:
        chapters = [{"heading": "", "body": title}]

    evidence_list: list[EvidenceInput] = []
    for i, ch in enumerate(chapters):
        chunk_text = f"# {ch['heading']}\n\n{ch['body']}" if ch["heading"] else ch["body"]
        evidence_list.append(EvidenceInput(
            source_type="announcement",
            source_name=f"公告:{ts_code}" if ts_code else "公告",
            source_id=source_id,
            text_excerpt=chunk_text,
            subject_hint={
                "ts_code": ts_code,
                "name": company_name,
                "ann_type": ann_type,
                "title": title,
            },
            publish_date=ann_date,
            observed_at=_utc_now(),
            source_ref={
                "source_table": "minishare_announcements",
                "source_id": ann_id,
                "ann_date": ann_date,
                "source_url": source_url,
                "chapter_heading": ch["heading"],
            },
            confidence=default_source_confidence("announcement"),
            metadata={"title": title, "chapter_count": len(chapters)},
        ))

    return evidence_list


def build_irm_evidence(
    record: dict[str, Any],
) -> EvidenceInput:
    """从 announcements (irm:*) 记录构建 EvidenceInput。

    每条互动易 Q&A 作为一个 Evidence，不分块。
    """
    ann_id = record.get("id") or ""
    question = (record.get("title") or "").strip()
    ts_code = (record.get("ts_code") or "").strip()
    ann_date = record.get("ann_date")
    ann_type = (record.get("announcement_type") or "")
    company_name = (record.get("name") or "").strip()

    return EvidenceInput(
        source_type="irm",
        source_name=f"互动易:{ts_code}" if ts_code else "互动易",
        source_id=str(ann_id),
        text_excerpt=f"问题：{question}",
        subject_hint={
            "ts_code": ts_code,
            "name": company_name,
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
git commit -m "feat(evidence): add builders for announcements (chapter-chunked) and IRM"
```

---

### Task 4: 创建 Evidence Pipeline 核心函数

**Files:**
- Create: `backend/app/data_pipeline/evidence_pipeline.py`

- [ ] **Step 1: 创建 evidence_pipeline.py**

```python
"""Evidence Pipeline — 将 PostgreSQL 源数据转为 MongoDB Evidence + 追踪"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from app.core.database import engine
from app.knowledge.evidence_service import EvidenceService
from app.knowledge.evidence_builders_simple import (
    build_announcement_evidence,
    build_irm_evidence,
)

logger = logging.getLogger(__name__)


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
    download_pdf: bool = True,
) -> dict[str, int]:
    """从 minishare_announcements 构建 Evidence（下载 PDF + 章节分块）。

    Args:
        limit: 最大处理条数（公告条数，非 chunk 数），None 表示全部
        offset: 起始偏移
        download_pdf: 是否下载 PDF（默认 True）

    Returns:
        {"total": N, "chunks": N, "created": N, "skipped": N, "failed": N}
    """
    service = EvidenceService()
    await service.ensure_indexes()

    async with engine.connect() as conn:
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
    total_chunks = created = skipped = failed = 0

    for rec in records:
        try:
            evidence_list = build_announcement_evidence(rec, download_pdf=download_pdf)
            for chunk_idx, evidence_input in enumerate(evidence_list):
                total_chunks += 1
                result = await service.upsert_evidence(evidence_input, chunk_index=chunk_idx)
                evidence_id = result.get("evidence_id") or ""

                await _upsert_tracking(
                    source_table="minishare_announcements",
                    source_id=int(rec["id"]),
                    evidence_id=evidence_id,
                    chunk_index=chunk_idx,
                )

                await service.enqueue_default_jobs(evidence_id)

                created_at = result.get("created_at")
                if created_at and _is_recent(created_at):
                    created += 1
                else:
                    skipped += 1
        except Exception as e:
            failed += 1
            logger.warning(f"公告 Evidence 构建失败 [id={rec.get('id')}]: {e}")

    logger.info(
        "公告 Evidence pipeline: records=%d chunks=%d created=%d skipped=%d failed=%d",
        total, total_chunks, created, skipped, failed,
    )
    return {"total": total, "chunks": total_chunks, "created": created, "skipped": skipped, "failed": failed}


async def build_irm_evidence_pipeline(
    limit: int | None = None,
    offset: int = 0,
) -> dict[str, int]:
    """从 announcements (irm:*) 构建 Evidence。

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
git commit -m "feat(evidence): add pipeline with PDF download + chapter chunking"
```

---

### Task 5: 试跑验证 — 5 条公告

- [ ] **Step 1: 确保 uvicorn 运行中**

```bash
ps aux | grep uvicorn | grep -v grep || (cd backend && .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8080 > /tmp/uvicorn.log 2>&1 & sleep 4)
```

- [ ] **Step 2: 运行公告 pipeline（5 条）**

```bash
cd backend && .venv/bin/python - <<'EOF'
import asyncio
from app.data_pipeline.evidence_pipeline import build_announcement_evidence_pipeline

result = asyncio.run(build_announcement_evidence_pipeline(limit=5))
print(result)
EOF
```

Expected: `total=5`, `chunks` > 5（每个公告可能分多个章节）

- [ ] **Step 3: 验证 MongoDB evidence 内容**

```bash
cd backend && .venv/bin/python - <<'EOF'
import asyncio
from app.knowledge.evidence_service import EvidenceService

async def verify():
    svc = EvidenceService()
    stats = await svc.get_stats()
    print(f"Evidence: {stats['evidence']}, Jobs: {stats['jobs']}")
    print(f"Jobs by status: {stats['jobs_by_status']}")
    # 查看一条 evidence 样例
    doc = await svc._evidence.find_one({"source_type": "announcement"})
    if doc:
        print(f"\nSample evidence:")
        print(f"  source_id: {doc.get('source_id')}")
        print(f"  text_excerpt: {doc.get('text_excerpt','')[:200]}")
        print(f"  source_ref: {doc.get('source_ref',{})}")

asyncio.run(verify())
EOF
```

- [ ] **Step 4: 验证 PostgreSQL tracking**

```bash
cd backend && .venv/bin/python - <<'EOF'
import asyncio
from sqlalchemy import text
from app.core.database import engine

async def verify():
    async with engine.connect() as conn:
        r = await conn.execute(text("""
            SELECT source_table, count(*) as cnt, 
                   count(*) FILTER (WHERE extraction_status='pending') as pending
            FROM evidence_tracking GROUP BY source_table
        """))
        for row in r.fetchall():
            print(f"  {row[0]}: {row[1]} rows, {row[2]} pending")

asyncio.run(verify())
EOF
```

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "test: evidence pipeline verified with 5 announcements (PDF + chapter chunking)"
```

---

### Task 6: 试跑互动易 + 幂等性验证

- [ ] **Step 1: 运行 IRM pipeline**

```bash
cd backend && .venv/bin/python - <<'EOF'
import asyncio
from app.data_pipeline.evidence_pipeline import build_irm_evidence_pipeline
result = asyncio.run(build_irm_evidence_pipeline())
print(result)
EOF
```

- [ ] **Step 2: 验证幂等性 — 重复运行应返回 total=0**

```bash
cd backend && .venv/bin/python - <<'EOF'
import asyncio
from app.data_pipeline.evidence_pipeline import build_announcement_evidence_pipeline, build_irm_evidence_pipeline

# 已处理的不会被重复查询
r1 = asyncio.run(build_announcement_evidence_pipeline(limit=5))
print(f"Announcements re-run: {r1}")  # total 应为 0

r2 = asyncio.run(build_irm_evidence_pipeline())
print(f"IRM re-run: {r2}")  # total 应为 0
EOF
```

- [ ] **Step 3: 验证总体统计**

```bash
cd backend && .venv/bin/python - <<'EOF'
import asyncio
from app.data_pipeline.evidence_pipeline import get_pipeline_stats
result = asyncio.run(get_pipeline_stats())
print("=== Tracking ===")
for row in result['tracking']:
    print(f"  {row['source_table']}: total={row['total']} pending={row['pending']} done={row['done']} failed={row['failed']}")
print(f"\n=== MongoDB ===")
print(f"  evidence={result['mongo']['evidence']}, jobs={result['mongo']['jobs']}")
print(f"  jobs_by_status={result['mongo']['jobs_by_status']}")
EOF
```

- [ ] **Step 4: Commit**

```bash
git add -A && git commit -m "test: IRM pipeline + idempotency confirmed"
```

---

### Task 7: 启动 Worker 消费 Evidence Job → KG

- [ ] **Step 1: 运行 Worker 处理 4 个 combined job**

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

- [ ] **Step 2: 验证 Neo4j 有实体/关系生成**

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
    print(f"  {row['source_table']}: total={row['total']} pending={row['pending']} done={row['done']}")
EOF
```

Expected: `done` 计数 > 0

- [ ] **Step 4: Commit**

```bash
git add -A && git commit -m "test: worker consumed evidence jobs, KG entities created in Neo4j"
```

---

### Task 8: 添加 API 端点

**Files:**
- Modify: `backend/app/data_pipeline/api/data_sync.py`

- [ ] **Step 1: 在 data_sync.py 文件末尾添加 evidence 端点**

```python
# ── Evidence Pipeline ─────────────────────────────────────

@router.post("/evidence/build/announcements", response_model=SyncResponse)
async def build_announcement_evidence(
    limit: int = Query(default=100, description="单次处理条数（公告条数，非 chunk 数）"),
    offset: int = Query(default=0, description="偏移量"),
    download_pdf: bool = Query(default=True, description="是否下载 PDF"),
) -> SyncResponse:
    """从 minishare_announcements 构建 Evidence（下载 PDF + 章节分块）"""
    from app.data_pipeline.evidence_pipeline import build_announcement_evidence_pipeline

    result = await build_announcement_evidence_pipeline(
        limit=limit, offset=offset, download_pdf=download_pdf,
    )
    return SyncResponse(
        task_id="sync",
        status="completed",
        message=f"公告 Evidence: records={result['total']} chunks={result['chunks']} created={result['created']}",
        details=result,
    )


@router.post("/evidence/build/irm", response_model=SyncResponse)
async def build_irm_evidence(
    limit: int = Query(default=100, description="单次处理条数"),
    offset: int = Query(default=0, description="偏移量"),
) -> SyncResponse:
    """从 announcements (irm:*) 构建 Evidence"""
    from app.data_pipeline.evidence_pipeline import build_irm_evidence_pipeline

    result = await build_irm_evidence_pipeline(limit=limit, offset=offset)
    return SyncResponse(
        task_id="sync",
        status="completed",
        message=f"互动易 Evidence: total={result['total']} created={result['created']}",
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
        message=f"Worker: claimed={result['claimed']} success={result['success']}",
        details=result,
    )
```

- [ ] **Step 2: 重启 uvicorn 并测试 stats 端点**

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
