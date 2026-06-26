# Evidence 构建设计实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复配置路径 + 修复 Evidence Builder + 创建批量构建脚本

**Architecture:** 
1. 修复 `config.py` 中的 `minishare_data_root` 路径
2. 修复 `evidence_builders_simple.py` 中的路径映射和字段名
3. 创建 `build_evidence_batch.py` 批量构建脚本

**Tech Stack:** Python, asyncio, PostgreSQL, MongoDB, FileStorage

---

## 1. 文件变更概览

| 文件 | 操作 | 职责 |
|------|------|------|
| `backend/app/config.py` | 修改 | 修复 minishare_data_root 路径 |
| `backend/app/knowledge/evidence_builders_simple.py` | 修改 | 路径映射 + 字段修复 |
| `backend/scripts/build_evidence_batch.py` | 创建 | 批量构建 Evidence 脚本 |

---

## 2. 任务列表

### Task 1: 修复 config.py 路径配置

**文件:**
- Modify: `backend/app/config.py`

**步骤:**

- [ ] **Step 1: 修改 minishare_data_root 配置**

```python
# backend/app/config.py
# 找到 Settings 类中的 minishare_data_root 字段

# 旧值 (约 line 35-36):
minishare_data_root: Path = Path("/home/lwm/qingshui_data")

# 新值:
minishare_data_root: Path = Path("/run/media/lwm/0E27099B0E27099B/qingshui_data")
```

- [ ] **Step 2: 验证配置读取正确**

```bash
cd /home/lwm/code/QingshuiYanTou/backend
source .venv/bin/activate
python -c "from app.config import settings; print(settings.minishare_data_root)"
# 预期输出: /run/media/lwm/0E27099B0E27099B/qingshui_data
```

---

### Task 2: 修复 evidence_builders_simple.py 路径映射

**文件:**
- Modify: `backend/app/knowledge/evidence_builders_simple.py`
- Test: `backend/tests/test_evidence_builders_simple.py` (创建)

**步骤:**

- [ ] **Step 1: 添加路径映射和 os import**

```python
# backend/app/knowledge/evidence_builders_simple.py
# 文件顶部添加 os import (如果已有则跳过)
import os

# 在模块顶部（常量定义区域）添加路径映射
PATH_PREFIX_MAP = {
    "/home/lwm/qingshui_data": "/run/media/lwm/0E27099B0E27099B/qingshui_data"
}


def _map_file_path(file_path: str | None) -> str | None:
    """将旧路径映射到新路径"""
    if not file_path:
        return None
    for old_prefix, new_prefix in PATH_PREFIX_MAP.items():
        if file_path.startswith(old_prefix):
            return file_path.replace(old_prefix, new_prefix)
    return file_path


def _file_exists(file_path: str | None) -> bool:
    """检查文件是否存在"""
    return file_path and os.path.exists(file_path)
```

- [ ] **Step 2: 修复 build_announcement_evidence 函数**

找到现有的 `build_announcement_evidence` 函数，替换为：

```python
def build_announcement_evidence(
    record: dict[str, Any],
) -> list[EvidenceInput]:
    """从 announcements 记录构建 EvidenceInput。

    每章节（chapter）为一个 Evidence。
    如果本地有 PDF，则解析章节；否则用 title 作为 fallback。

    Args:
        record: 包含 id, ts_code, name, title, ann_date, announcement_type,
                pdf_url, file_path, content 的字典

    Returns:
        EvidenceInput 列表
    """
    ann_id = record.get("id") or ""
    ts_code = (record.get("ts_code") or "").strip()
    name = (record.get("name") or "").strip()
    title = (record.get("title") or "").strip()
    ann_date = record.get("ann_date")
    ann_type = (record.get("announcement_type") or "").strip()
    source_id = str(ann_id)

    # 解析 PDF 路径
    raw_path = record.get("file_path")
    local_pdf = _map_file_path(raw_path)
    has_local_pdf = _file_exists(local_pdf)

    # 解析章节
    chapters = None
    if has_local_pdf:
        chapters = _split_pdf_chapters(local_pdf)

    if chapters:
        # 有章节，按章节构建 Evidence
        evidence_list = []
        for i, ch in enumerate(chapters):
            chunk_text = f"# {ch['heading']}\n\n{ch['body']}" if ch["heading"] else ch["body"]
            evidence_list.append(EvidenceInput(
                source_type="announcement",
                source_name=f"公告:{ts_code}" if ts_code else "公告",
                source_id=source_id,
                text_excerpt=chunk_text,
                subject_hint={
                    "ts_code": ts_code,
                    "name": name,
                    "ann_type": ann_type,
                    "title": title,
                },
                publish_date=ann_date,
                observed_at=_utc_now(),
                source_ref={
                    "source_table": "announcements",
                    "ann_id": ann_id,
                    "ann_date": ann_date,
                    "local_pdf": local_pdf,
                    "pdf_url": record.get("pdf_url"),
                    "chapter_index": i,
                    "chapter_heading": ch["heading"],
                },
                confidence=default_source_confidence("announcement"),
                metadata={"title": title, "chapter_count": len(chapters)},
            ))
        return evidence_list
    else:
        # 无 PDF 或解析失败，用 title 构建 Evidence
        return [EvidenceInput(
            source_type="announcement",
            source_name=f"公告:{ts_code}" if ts_code else "公告",
            source_id=source_id,
            text_excerpt=title,
            subject_hint={
                "ts_code": ts_code,
                "name": name,
                "ann_type": ann_type,
                "title": title,
            },
            publish_date=ann_date,
            observed_at=_utc_now(),
            source_ref={
                "source_table": "announcements",
                "ann_id": ann_id,
                "ann_date": ann_date,
                "local_pdf": local_pdf if has_local_pdf else None,
                "pdf_url": record.get("pdf_url"),
                "chapter_index": 0,
                "has_pdf": has_local_pdf,
            },
            confidence=default_source_confidence("announcement"),
            metadata={"title": title, "has_pdf": has_local_pdf},
        )]
```

- [ ] **Step 3: 添加 PDF 解析辅助函数**

在 `_map_file_path` 函数附近添加：

```python
def _split_pdf_chapters(file_path: str) -> list[dict]:
    """解析 PDF 并按章节切分，返回章节列表"""
    try:
        from app.knowledge.ingestion.announcement_parser import (
            download_announcement_pdf,
            parse_pdf_text,
            split_by_chapters,
        )
        # 注意：这里 file_path 是本地路径，不是 URL
        # 需要直接读取文件
        with open(file_path, 'rb') as f:
            content = f.read()
        text = parse_pdf_text(content)
        return split_by_chapters(text)
    except Exception as e:
        logger.warning(f"PDF 解析失败 [{file_path}]: {e}")
        return None
```

- [ ] **Step 4: 修复 build_irm_evidence 函数**

找到现有的 `build_irm_evidence` 函数，替换为：

```python
def build_irm_evidence(record: dict[str, Any]) -> EvidenceInput:
    """从 announcements (irm:*) 记录构建 EvidenceInput。

    每条互动易 Q&A 作为一个 Evidence，不分块。

    IRM 数据结构：
    - title: 问题内容
    - content: 回答内容
    """
    ann_id = record.get("id") or ""
    question = (record.get("title") or "").strip()  # IRM 问题在 title 字段
    answer = (record.get("content") or "").strip()   # IRM 回答在 content 字段
    ts_code = (record.get("ts_code") or "").strip()
    ann_date = record.get("ann_date")
    company_name = (record.get("name") or "").strip()
    ann_type = (record.get("announcement_type") or "").strip()

    # 构造 text_excerpt
    if answer:
        text_excerpt = f"问：{question}\n答：{answer}"
    else:
        text_excerpt = question

    return EvidenceInput(
        source_type="irm",
        source_name=f"互动易:{ts_code}" if ts_code else "互动易",
        source_id=str(ann_id),
        text_excerpt=text_excerpt,
        subject_hint={
            "ts_code": ts_code,
            "name": company_name,
            "irm_type": ann_type,
        },
        publish_date=ann_date,
        observed_at=_utc_now(),
        source_ref={
            "source_table": "announcements",
            "ann_id": ann_id,
            "ann_date": ann_date,
            "ann_type": ann_type,
        },
        confidence=default_source_confidence("irm"),
        metadata={
            "question": question,
            "answer": answer,
            "irm_type": ann_type,
        },
    )
```

- [ ] **Step 5: 创建测试文件**

```python
# backend/tests/test_evidence_builders_simple.py
import pytest
import os
from app.knowledge.evidence_builders_simple import (
    _map_file_path,
    _file_exists,
)


class TestPathMapping:
    """路径映射测试"""

    def test_map_old_path_to_new(self):
        """旧路径应映射到新路径"""
        old_path = "/home/lwm/qingshui_data/notices/000001.SZ/2024-01/test.pdf"
        result = _map_file_path(old_path)
        assert result == "/run/media/lwm/0E27099B0E27099B/qingshui_data/notices/000001.SZ/2024-01/test.pdf"

    def test_map_new_path_unchanged(self):
        """新路径保持不变"""
        new_path = "/run/media/lwm/0E27099B0E27099B/qingshui_data/notices/000001.SZ/2024-01/test.pdf"
        result = _map_file_path(new_path)
        assert result == new_path

    def test_map_none_returns_none(self):
        """None 输入返回 None"""
        assert _map_file_path(None) is None

    def test_file_exists_returns_false_for_none(self):
        """None 返回 False"""
        assert _file_exists(None) is False
```

- [ ] **Step 6: 运行测试验证**

```bash
cd /home/lwm/code/QingshuiYanTou/backend
source .venv/bin/activate
pytest tests/test_evidence_builders_simple.py -v
```

---

### Task 3: 创建批量构建脚本

**文件:**
- Create: `backend/scripts/build_evidence_batch.py`

**步骤:**

- [ ] **Step 1: 创建脚本文件**

```python
#!/usr/bin/env python3
"""
批量构建 Evidence 脚本

从 PostgreSQL announcements 表读取数据，批量构建 Evidence 入 MongoDB。

用法:
    python -m scripts.build_evidence_batch --type announcement
    python -m scripts.build_evidence_batch --type irm
    python -m scripts.build_evidence_batch --type all
    python -m scripts.build_evidence_batch --type all --limit 1000  # 限制条数
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from pathlib import Path
from typing import Any

# 添加 backend 到 path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text

from app.core.database import engine
from app.core.mongodb import get_mongo_db
from app.knowledge.evidence_service import EvidenceService
from app.knowledge.evidence_builders_simple import (
    build_announcement_evidence,
    build_irm_evidence,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

BATCH_SIZE = 100


async def fetch_announcements_batch(
    conn,
    start_id: int,
    batch_size: int,
    filter_type: str = "announcement",  # "announcement" | "irm" | "all"
):
    """批量获取公告数据"""
    if filter_type == "announcement":
        where_clause = "source_type = 'minishare' AND announcement_type NOT LIKE 'irm:%'"
    elif filter_type == "irm":
        where_clause = "source_type = 'minishare' AND announcement_type LIKE 'irm:%'"
    else:
        where_clause = "source_type = 'minishare'"

    query = text(f"""
        SELECT id, ts_code, name, title, ann_date, announcement_type,
               pdf_url, file_path, content
        FROM announcements
        WHERE {where_clause}
        AND id > :start_id
        ORDER BY id
        LIMIT :limit
    """)
    result = await conn.execute(query, {"start_id": start_id, "limit": batch_size})
    return result.fetchall()


async def build_announcement_evidence_batch(limit: int | None = None):
    """批量构建公告 Evidence"""
    service = EvidenceService()
    total = 0
    start_id = 0

    logger.info("开始构建公告 Evidence...")

    async with engine.connect() as conn:
        while True:
            rows = await fetch_announcements_batch(
                conn, start_id, BATCH_SIZE, "announcement"
            )
            if not rows:
                break

            for row in rows:
                record = {
                    "id": row[0],
                    "ts_code": row[1],
                    "name": row[2],
                    "title": row[3],
                    "ann_date": row[4],
                    "announcement_type": row[5],
                    "pdf_url": row[6],
                    "file_path": row[7],
                    "content": row[8],
                }

                evidence_list = build_announcement_evidence(record)
                for ei in evidence_list:
                    await service.upsert_evidence(ei)

                total += 1

            start_id = rows[-1][0]
            logger.info(f"已处理公告 {total} 条 (last_id={start_id})")

            if limit and total >= limit:
                break

    logger.info(f"公告 Evidence 构建完成: {total} 条")
    return total


async def build_irm_evidence_batch(limit: int | None = None):
    """批量构建 IRM Evidence"""
    service = EvidenceService()
    total = 0
    start_id = 0

    logger.info("开始构建 IRM Evidence...")

    async with engine.connect() as conn:
        while True:
            rows = await fetch_announcements_batch(
                conn, start_id, BATCH_SIZE, "irm"
            )
            if not rows:
                break

            for row in rows:
                record = {
                    "id": row[0],
                    "ts_code": row[1],
                    "name": row[2],
                    "title": row[3],
                    "ann_date": row[4],
                    "announcement_type": row[5],
                    "content": row[8],
                }

                evidence_input = build_irm_evidence(record)
                await service.upsert_evidence(evidence_input)
                total += 1

            start_id = rows[-1][0]
            logger.info(f"已处理 IRM {total} 条 (last_id={start_id})")

            if limit and total >= limit:
                break

    logger.info(f"IRM Evidence 构建完成: {total} 条")
    return total


async def enqueue_all_jobs():
    """为所有 pending evidence enqueue jobs"""
    db = get_mongo_db()
    service = EvidenceService()

    count = 0
    async for doc in db.kg_evidence.find({"extraction_status": None}):
        await service.enqueue_default_jobs(doc["evidence_id"])
        count += 1
        if count % 1000 == 0:
            logger.info(f"已 enqueue {count} jobs")

    logger.info(f"共 enqueue {count} jobs")
    return count


async def main():
    parser = argparse.ArgumentParser(description="批量构建 Evidence")
    parser.add_argument(
        "--type",
        choices=["announcement", "irm", "all"],
        default="all",
        help="构建类型: announcement(非IRM公告) | irm(IRM问答) | all(全部)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="限制条数（用于测试）",
    )
    args = parser.parse_args()

    start_time = time.time()

    if args.type in ["announcement", "all"]:
        await build_announcement_evidence_batch(limit=args.limit)

    if args.type in ["irm", "all"]:
        await build_irm_evidence_batch(limit=args.limit)

    logger.info("开始 enqueue extraction jobs...")
    await enqueue_all_jobs()

    elapsed = time.time() - start_time
    logger.info(f"全部完成，耗时 {elapsed:.1f}s")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: 运行测试（限制100条）**

```bash
cd /home/lwm/code/QingshuiYanTou/backend
source .venv/bin/activate
python -m scripts.build_evidence_batch --type all --limit 100
```

- [ ] **Step 3: 检查 MongoDB 结果**

```bash
cd /home/lwm/code/QingshuiYanTou/backend
source .venv/bin/activate
python << 'EOF'
import asyncio
from app.core.mongodb import get_mongo_db

async def check():
    db = get_mongo_db()
    
    # 统计 evidence
    total = await db.kg_evidence.count_documents({})
    print(f"kg_evidence 总数: {total}")
    
    # 按 source_type 分布
    pipeline = [
        {"$group": {"_id": "$source_type", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}}
    ]
    async for doc in db.kg_evidence.aggregate(pipeline):
        print(f"  {doc['_id']}: {doc['count']}")
    
    # 统计 jobs
    jobs_total = await db.kg_extraction_jobs.count_documents({})
    pending = await db.kg_extraction_jobs.count_documents({"status": "pending"})
    print(f"\nkg_extraction_jobs: {jobs_total} (pending: {pending})")

asyncio.run(check())
EOF
```

---

### Task 4: 验证完整流程

**步骤:**

- [ ] **Step 1: 运行完整构建（无限制）**

```bash
cd /home/lwm/code/QingshuiYanTou/backend
source .venv/bin/activate
python -m scripts.build_evidence_batch --type all
```

- [ ] **Step 2: 验证结果**

```bash
source .venv/bin/activate
python << 'EOF'
import asyncio
from app.core.mongodb import get_mongo_db

async def check():
    db = get_mongo_db()
    
    # 统计 evidence
    total = await db.kg_evidence.count_documents({})
    print(f"kg_evidence 总数: {total:,}")
    
    # 按 source_type 分布
    pipeline = [
        {"$group": {"_id": "$source_type", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}}
    ]
    async for doc in db.kg_evidence.aggregate(pipeline):
        print(f"  {doc['_id']}: {doc['count']:,}")
    
    # 统计 jobs
    jobs_total = await db.kg_extraction_jobs.count_documents({})
    pending = await db.kg_extraction_jobs.count_documents({"status": "pending"})
    done = await db.kg_extraction_jobs.count_documents({"status": "done"})
    print(f"\nkg_extraction_jobs: {jobs_total:,} (pending: {pending:,}, done: {done:,})")

asyncio.run(check())
EOF
```

---

## 3. 自检清单

- [x] Spec 覆盖检查：config.py 修复、evidence_builders_simple.py 修复、批量脚本
- [x] Placeholder 检查：无 TBD/TODO
- [x] 类型一致性：EvidenceInput 字段名与 evidence_builders_simple.py 一致
