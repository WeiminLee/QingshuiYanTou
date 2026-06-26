# Evidence 构建设计

**日期**: 2026-06-23
**状态**: Approved

## 1. 背景

MongoDB kg_evidence 集合为空（0条），需要从 PostgreSQL 公告表构建 Evidence 记录，为后续 LLM 抽取做准备。

### 1.1 问题定位

| 问题 | 现状 |
|------|------|
| 配置路径错误 | `minishare_data_root = /home/lwm/qingshui_data`（不存在） |
| 数据库路径前缀错误 | `file_path` 存的是旧路径 `/home/lwm/qingshui_data/notices/` |
| PDF 文件位置 | 实际在 `/run/media/lwm/0E27099B0E27099B/qingshui_data/notices/` |
| 路径存在率 | 旧路径 0%，新路径 ~29%（抽样100条） |
| content 字段 | 全为空，PDF 未解析入库 |
| builder 字段名错误 | `build_announcement_evidence` 用 `source_url`（不存在），应用 `pdf_url` |

### 1.2 数据规模

- 公告总数（minishare，非IRM）: **128,856 条**
- IRM 数据: 通过 minishare 接口回补（见 IRM 数据源分层策略）

---

## 2. 目标

1. 修复配置路径，使 FileStorage 能正确访问 PDF
2. 修复 evidence_builders_simple.py，解析正确路径
3. 批量构建公告 Evidence 入 MongoDB kg_evidence
4. 批量构建 IRM Evidence 入 MongoDB kg_evidence
5. 批量 enqueue extraction jobs

---

## 3. 实现方案

### 3.1 修复配置路径

**文件**: `backend/app/config.py`

```python
# 旧值
minishare_data_root: Path = Path("/home/lwm/qingshui_data")

# 新值
minishare_data_root: Path = Path("/run/media/lwm/0E27099B0E27099B/qingshui_data")
```

### 3.2 修复 Evidence Builder

**文件**: `backend/app/knowledge/evidence_builders_simple.py`

#### 路径映射

```python
# 旧路径前缀 → 新路径前缀
PATH_PREFIX_MAP = {
    "/home/lwm/qingshui_data": "/run/media/lwm/0E27099B0E27099B/qingshui_data"
}

def _map_path(file_path: str | None) -> str | None:
    """将旧路径映射到新路径"""
    if not file_path:
        return None
    for old_prefix, new_prefix in PATH_PREFIX_MAP.items():
        if file_path.startswith(old_prefix):
            return file_path.replace(old_prefix, new_prefix)
    return file_path
```

#### 修复 build_announcement_evidence

```python
def build_announcement_evidence(
    record: dict[str, Any],
    chapters: list[dict] | None = None,
) -> list[EvidenceInput]:
    """
    从 announcements 记录构建 EvidenceInput。

    PDF 路径优先级：
    1. 本地 file_path（映射到新路径后检查是否存在）
    2. 直接使用 title 作为 text_excerpt

    每章节（chapter）为一个 Evidence。
    """
    ann_id = record.get("id") or ""
    ts_code = (record.get("ts_code") or "").strip()
    name = (record.get("name") or "").strip()
    title = (record.get("title") or "").strip()
    ann_date = record.get("ann_date")
    ann_type = (record.get("announcement_type") or "").strip()
    source_id = str(ann_id)

    # 解析 PDF 路径
    file_path = record.get("file_path")
    mapped_path = _map_path(file_path)
    has_pdf = mapped_path and os.path.exists(mapped_path)

    # 读取 PDF 内容并解析章节
    if has_pdf and chapters is None:
        chapters = _parse_pdf_chapters(mapped_path)

    if chapters:
        # 有章节，按章节构建 Evidence
        evidence_list = []
        for i, ch in enumerate(chapters):
            chunk_text = f"# {ch['heading']}\n\n{ch['body']}" if ch["heading"] else ch["body"]
            evidence_list.append(_make_evidence(
                source_type="announcement",
                source_id=source_id,
                text_excerpt=chunk_text,
                ts_code=ts_code,
                company_name=name,
                ann_type=ann_type,
                title=title,
                ann_date=ann_date,
                pdf_path=mapped_path,
                chapter_index=i,
            ))
        return evidence_list
    else:
        # 无章节，用 title 构建 Evidence
        return [_make_evidence(
            source_type="announcement",
            source_id=source_id,
            text_excerpt=title,
            ts_code=ts_code,
            company_name=name,
            ann_type=ann_type,
            title=title,
            ann_date=ann_date,
            pdf_path=mapped_path,
            chapter_index=0,
        )]
```

#### 修复 build_irm_evidence

```python
def build_irm_evidence(record: dict[str, Any]) -> EvidenceInput:
    """从 announcements (irm:*) 记录构建 EvidenceInput。

    每条互动易 Q&A 作为一个 Evidence，不分块。

    IRM 数据结构：
    - title: 问题内容
    - content: 回答内容
    """
    ann_id = record.get("id") or ""
    question = (record.get("title") or "").strip()
    answer = (record.get("content") or "").strip()
    ts_code = (record.get("ts_code") or "").strip()
    ann_date = record.get("ann_date")
    company_name = (record.get("name") or "").strip()

    text_excerpt = f"问：{question}\n答：{answer}" if answer else question

    return EvidenceInput(
        source_type="irm",
        source_name=f"互动易:{ts_code}" if ts_code else "互动易",
        source_id=str(ann_id),
        text_excerpt=text_excerpt,
        subject_hint={
            "ts_code": ts_code,
            "name": company_name,
        },
        publish_date=ann_date,
        observed_at=_utc_now(),
        source_ref={
            "source_table": "announcements",
            "ann_id": ann_id,
            "ann_date": ann_date,
        },
        confidence=default_source_confidence("irm"),
    )
```

### 3.3 PDF 解析工具

**文件**: `backend/app/knowledge/ingestion/announcement_parser.py`（已存在）

使用已有的 `parse_pdf_text()` 和 `split_by_chapters()` 函数。

### 3.4 批量构建脚本

**文件**: `backend/scripts/build_evidence_batch.py`

```python
#!/usr/bin/env python3
"""
批量构建 Evidence 脚本

流程：
1. 从 PostgreSQL announcements 表读取公告数据
2. 对每条公告调用 build_announcement_evidence / build_irm_evidence
3. 批量 upsert 到 MongoDB kg_evidence
4. 批量 enqueue extraction jobs

用法:
    python -m scripts.build_evidence_batch --type announcement
    python -m scripts.build_evidence_batch --type irm
    python -m scripts.build_evidence_batch --type all
"""
import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.database import engine
from app.core.mongodb import get_mongo_db
from app.knowledge.evidence_service import EvidenceService
from app.knowledge.evidence_builders_simple import (
    build_announcement_evidence,
    build_irm_evidence,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger(__name__)

BATCH_SIZE = 100


async def build_announcement_evidence_batch(start_id: int = 0, limit: int | None = None):
    """批量构建公告 Evidence"""
    service = EvidenceService()
    query = """
        SELECT id, ts_code, name, title, ann_date, announcement_type,
               pdf_url, file_path, content
        FROM announcements
        WHERE source_type = 'minishare'
        AND announcement_type NOT LIKE 'irm:%'
        AND id > :start_id
        ORDER BY id
        LIMIT :limit
    """
    total = 0
    async with engine.connect() as conn:
        while True:
            result = await conn.execute(
                text(query),
                {"start_id": start_id, "limit": BATCH_SIZE}
            )
            rows = result.fetchall()
            if not rows:
                break

            for row in rows:
                record = {
                    "id": row[0], "ts_code": row[1], "name": row[2],
                    "title": row[3], "ann_date": row[4],
                    "announcement_type": row[5], "pdf_url": row[6],
                    "file_path": row[7], "content": row[8],
                }

                # IRM 直接构建
                if record["announcement_type"] and record["announcement_type"].startswith("irm:"):
                    evidence_input = build_irm_evidence(record)
                    await service.upsert_evidence(evidence_input)
                else:
                    # 公告按章节构建
                    evidence_list = build_announcement_evidence(record)
                    for ei in evidence_list:
                        await service.upsert_evidence(ei)

                total += 1

            start_id = row[0]
            logger.info(f"已处理 {total} 条")

            if limit and total >= limit:
                break

    return total


async def build_irm_evidence_batch(start_id: int = 0, limit: int | None = None):
    """批量构建 IRM Evidence"""
    service = EvidenceService()
    query = """
        SELECT id, ts_code, name, title, ann_date, announcement_type, content
        FROM announcements
        WHERE source_type = 'minishare'
        AND announcement_type LIKE 'irm:%'
        AND id > :start_id
        ORDER BY id
        LIMIT :limit
    """
    total = 0
    async with engine.connect() as conn:
        while True:
            result = await conn.execute(
                text(query),
                {"start_id": start_id, "limit": BATCH_SIZE}
            )
            rows = result.fetchall()
            if not rows:
                break

            for row in rows:
                record = {
                    "id": row[0], "ts_code": row[1], "name": row[2],
                    "title": row[3], "ann_date": row[4],
                    "announcement_type": row[5], "content": row[6],
                }
                evidence_input = build_irm_evidence(record)
                await service.upsert_evidence(evidence_input)
                total += 1

            start_id = row[0]
            logger.info(f"已处理 {total} 条 IRM")

            if limit and total >= limit:
                break

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
    parser = argparse.ArgumentParser()
    parser.add_argument("--type", choices=["announcement", "irm", "all"], default="all")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    if args.type in ["announcement", "all"]:
        logger.info("开始构建公告 Evidence...")
        total = await build_announcement_evidence_batch(limit=args.limit)
        logger.info(f"公告 Evidence 构建完成: {total} 条")

    if args.type in ["irm", "all"]:
        logger.info("开始构建 IRM Evidence...")
        total = await build_irm_evidence_batch(limit=args.limit)
        logger.info(f"IRM Evidence 构建完成: {total} 条")

    logger.info("开始 enqueue extraction jobs...")
    await enqueue_all_jobs()
    logger.info("全部完成")


if __name__ == "__main__":
    asyncio.run(main())
```

---

## 4. 风险与限制

| 风险 | 说明 | 缓解 |
|------|------|------|
| PDF 解析慢 | 12.8万条 PDF 逐个解析耗时 | 使用 asyncio 并发，限制并发数 |
| PDF 缺失 | ~71% 公告无本地 PDF | 用 title 作为 fallback text_excerpt |
| MongoDB 写入慢 | 批量写入需优化 | 使用 bulk_write |

---

## 5. 后续步骤

1. [ ] 修复 config.py 路径
2. [ ] 修复 evidence_builders_simple.py
3. [ ] 创建 build_evidence_batch.py 脚本
4. [ ] 运行脚本构建 Evidence
5. [ ] 运行 extraction worker 测试

---

## 6. 依赖

- PostgreSQL announcements 表已有数据
- MongoDB kg_evidence, kg_extraction_jobs 集合
- FileStorage 能访问 PDF（需 config.py 修复）
- announcement_parser.py 已有 PDF 解析函数
