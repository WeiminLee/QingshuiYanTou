# IRM 数据统一与修复实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 IRM 数据统一为单一数据库，通过 CSV 导入历史数据 + minishare 回补增量，删除多余的 source_type 和冗余代码。

**Architecture:**
- **单一 IRM 数据源**: 所有 IRM 数据使用 `source_type = "minishare"`（因为 minishare 是实时增量数据源）
- **数据入口**:
  1. CSV 导入历史数据（2026-05-22 之前）
  2. minishare 回补增量（2026-05-23 至今）
- **去重策略**: `ON CONFLICT (cninfo_id) DO NOTHING` 基于唯一 cninfo_id

**Tech Stack:** Python async, SQLAlchemy, pandas, minishare API

---

## 任务概览

| 任务 | 描述 | 风险 |
|------|------|------|
| T1 | 数据分析：确定 CSV 覆盖范围和缺失日期 | 低 |
| T2 | 清理数据库：统一 source_type 为 `minishare` | 中 |
| T3 | 重写 CSV 导入脚本（统一 cninfo_id 生成逻辑） | 中 |
| T4 | 清理冗余脚本和代码 | 低 |
| T5 | 验证数据完整性 | 低 |

---

## Task 1: 数据分析与范围确定

**Files:** 无

- [ ] **Step 1: 检查 CSV 文件覆盖范围**

```bash
cd /home/lwm/code/QingshuiYanTou/backend
PYTHONPATH=/home/lwm/code/QingshuiYanTou/backend /home/lwm/code/QingshuiYanTou/backend/.venv/bin/python3 -c "
import pandas as pd

csv_path = '/home/lwm/irm-_new_data/tushare_irm_qa_all.csv'
df = pd.read_csv(csv_path)
df['trade_date'] = pd.to_datetime(df['trade_date'].astype(str), format='%Y%m%d')

print('=== CSV 覆盖范围 ===')
print(f'总行数: {len(df):,}')
print(f'日期范围: {df[\"trade_date\"].min().date()} ~ {df[\"trade_date\"].max().date()}')
print(f'唯一日期数: {df[\"trade_date\"].nunique()}')
print()
print('=== 按月统计（最近12个月）===')
recent = df[df['trade_date'] >= '2025-06-01']
print(recent.groupby(recent['trade_date'].dt.to_period('M')).size())
"
```

- [ ] **Step 2: 确定 minishare 回补范围**

```bash
# 数据库最新日期 vs CSV 最新日期 → 确定需要 minishare 回补的日期
# CSV 最新: 2026-05-22
# 数据库最新: 2026-06-22
# 回补范围: 2026-05-23 ~ 2026-06-22
```

- [ ] **Step 3: 记录分析结果到 MEMORY**

更新 `irm-data-source-strategy.md`：
- CSV 覆盖: 2010-10-10 ~ 2026-05-22
- minishare 回补: 2026-05-23 ~ today
- 统一 source_type: `minishare`

---

## Task 2: 清理数据库，统一 source_type

**Files:** 无（直接 SQL 操作）

- [ ] **Step 1: 备份当前数据（创建临时表）**

```sql
-- 创建备份表
CREATE TABLE IF NOT EXISTS announcements_irm_backup AS
SELECT * FROM announcements WHERE source_type LIKE 'irm%';

-- 记录备份数量
SELECT COUNT(*) FROM announcements_irm_backup;
```

- [ ] **Step 2: 统一所有 IRM source_type 为 `minishare`**

```sql
-- 更新所有 IRM 数据 source_type
UPDATE announcements 
SET source_type = 'minishare' 
WHERE source_type LIKE 'irm%';

-- 验证更新结果
SELECT source_type, COUNT(*) FROM announcements WHERE source_type LIKE 'irm%' GROUP BY source_type;
```

- [ ] **Step 3: 验证 cninfo_id 唯一性**

```sql
-- 检查重复 cninfo_id
SELECT cninfo_id, COUNT(*) as cnt 
FROM announcements 
WHERE cninfo_id LIKE 'irm_%' OR cninfo_id LIKE 'minishare_%'
GROUP BY cninfo_id 
HAVING COUNT(*) > 1
LIMIT 10;

-- 统计总记录数和唯一 cninfo_id 数
SELECT 
  COUNT(*) as total,
  COUNT(DISTINCT cninfo_id) as unique_ids
FROM announcements 
WHERE source_type = 'minishare';
```

- [ ] **Step 4: 删除冗余的 source_type 记录（如果有）**

```sql
-- 检查是否还有非 minishare 的 irm_* 记录
SELECT DISTINCT source_type FROM announcements WHERE source_type LIKE 'irm%';
-- 应该返回空
```

---

## Task 3: 重写 CSV 导入脚本

**Files:**
- Modify: `backend/scripts/sync_irm_tushare.py` → 改为 `backend/scripts/import_irm_csv.py`

- [ ] **Step 1: 创建新的统一导入脚本**

新文件: `backend/scripts/import_irm_csv.py`

```python
#!/usr/bin/env python3
"""
IRM CSV 数据导入脚本

从 tushare CSV 文件导入 IRM 历史数据到 announcements 表。
导入后所有数据使用统一的 source_type = "minishare"。

数据格式：source, ts_code, name, trade_date, pub_time, industry, q, a, row_hash
日期范围：2010-10-10 ~ 2026-05-22

去重策略：
- 基于 cninfo_id（irm_{exchange}_{ts_code}_{trade_date}_{row_hash[:16]}）
- ON CONFLICT (cninfo_id) DO NOTHING

用法:
    python -m scripts.import_irm_csv --dry-run
    python -m scripts.import_irm_csv --scope all
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.database import engine
from app.data_pipeline.irm_filter import should_save as should_save_irm
from app.data_pipeline.progress import (
    PARTIAL,
    SUCCESS,
    IngestionProgressTracker,
)
from app.models.models import Announcement
from app.data_pipeline.backfill_config import load_backfill_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

CHUNK_SIZE = 10_000
BATCH_SIZE = 500
DEFAULT_CSV_FILE = "/home/lwm/irm-_new_data/tushare_irm_qa_all.csv"


def _source_to_exchange(source: str) -> str:
    """source 字段 → 交易所代码"""
    if not source:
        return "SZ"
    if "sh" in source.lower():
        return "SH"
    return "SZ"


def _parse_trade_date(trade_date) -> datetime.date | None:
    """解析 trade_date（YYYYMMDD）为 date 对象"""
    if not trade_date:
        return None
    s = str(trade_date).strip()
    try:
        return datetime.strptime(s[:8], "%Y%m%d").date()
    except ValueError:
        return None


def _generate_cninfo_id(ts_code: str, trade_date: str, row_hash: str, exchange: str) -> str:
    """生成唯一 cninfo_id"""
    hash_part = row_hash[:16] if row_hash else "unknown"
    return f"irm_{exchange}_{ts_code}_{trade_date}_{hash_part}"


async def _batch_insert(records: list[dict]) -> tuple[int, int]:
    """批量 INSERT，返回 (saved, dup_skipped)"""
    if not records:
        return 0, 0

    stmt = pg_insert(Announcement.__table__).values(records)
    stmt = stmt.on_conflict_do_nothing(index_elements=["cninfo_id"])

    try:
        async with engine.begin() as conn:
            result = await conn.execute(stmt)
            saved = result.rowcount if result.rowcount else 0
            return saved, len(records) - saved
    except Exception as e:
        logger.warning(f"批量插入失败: {e}")
        return 0, len(records)


async def sync_csv(
    csv_path: str,
    whitelist: frozenset[str] | None,
    batch_size: int,
    dry_run: bool,
) -> dict[str, int]:
    """同步 CSV 格式的 IRM 数据"""
    import pandas as pd

    counters = {
        "total": 0,
        "replied": 0,
        "filtered_irm": 0,
        "whitelist_skip": 0,
        "saved": 0,
        "dup_skip": 0,
    }
    pending: list[dict] = []

    logger.info(f"读取: {csv_path}")

    for chunk_idx, chunk in enumerate(pd.read_csv(csv_path, chunksize=CHUNK_SIZE)):
        chunk_len = len(chunk)
        counters["total"] += chunk_len

        for _, row in chunk.iterrows():
            question = str(row.get("q", "")).strip()
            answer = str(row.get("a", "")).strip()
            if not question or not answer or question == "nan" or answer == "nan":
                continue

            counters["replied"] += 1

            if not should_save_irm(question, answer):
                counters["filtered_irm"] += 1
                continue

            ts_code = str(row.get("ts_code", "")).strip()
            if not ts_code or "." not in ts_code:
                continue

            if whitelist is not None and ts_code not in whitelist:
                counters["whitelist_skip"] += 1
                continue

            source = str(row.get("source", "")).strip()
            exchange = _source_to_exchange(source)

            trade_date = row.get("trade_date")
            ann_date = _parse_trade_date(trade_date)
            if ann_date is None:
                continue

            trade_date_str = str(trade_date).strip()
            row_hash = str(row.get("row_hash", "")).strip()
            cninfo_id = _generate_cninfo_id(ts_code, trade_date_str, row_hash, exchange)

            source_name = "上证e互动" if exchange == "SH" else "深证互动易"

            pending.append({
                "ann_date": ann_date,
                "ts_code": ts_code,
                "name": str(row.get("name", "")).strip() or None,
                "title": question[:500],
                "type": answer,
                "cninfo_id": cninfo_id,
                "announcement_type": f"irm:{exchange}",
                "source_type": "minishare",  # 统一使用 minishare
                "source_name": source_name,
                "confidence_tier": "Tier2",
            })

        if not dry_run and pending:
            for i in range(0, len(pending), batch_size):
                batch = pending[i : i + batch_size]
                saved, dup = await _batch_insert(batch)
                counters["saved"] += saved
                counters["dup_skip"] += dup
            pending.clear()
        elif dry_run:
            counters["saved"] += len(pending)
            pending.clear()

        if chunk_idx % 10 == 0:
            logger.info(f"  chunk {chunk_idx}: total={counters['total']}, saved={counters['saved']}")

    if not dry_run and pending:
        for i in range(0, len(pending), batch_size):
            batch = pending[i : i + batch_size]
            saved, dup = await _batch_insert(batch)
            counters["saved"] += saved
            counters["dup_skip"] += dup

    return counters


async def main(
    csv_file: str = DEFAULT_CSV_FILE,
    scope: str | None = None,
    batch_size: int = BATCH_SIZE,
    dry_run: bool = False,
) -> dict[str, Any]:
    """主函数"""
    if scope:
        os.environ["BACKFILL_SCOPE"] = scope
    from app.data_pipeline.backfill_config import reset_settings_cache
    reset_settings_cache()
    cfg = load_backfill_settings()

    whitelist: frozenset[str] | None = None
    if cfg.scope == "tech_mvp" and cfg.ts_codes:
        whitelist = cfg.ts_codes

    print(f"{'=' * 65}")
    print(f"  IRM CSV 数据导入")
    print(f"{'=' * 65}")
    print(f"  CSV 文件: {csv_file}")
    print(f"  白名单:   {'tech_mvp (%d 只)' % len(whitelist) if whitelist else '全市场'}")
    print(f"  模式:     {'试运行' if dry_run else '正式写入'}")
    print()

    start_time = time.time()
    result = await sync_csv(csv_file, whitelist, batch_size, dry_run)
    elapsed = int(time.time() - start_time)

    print()
    print(f"{'=' * 65}")
    print(f"  导入完成!")
    print(f"  总行数: {result['total']:,}")
    print(f"  已回复: {result['replied']:,}")
    print(f"  过滤:   {result['filtered_irm']:,}")
    print(f"  白名单跳过: {result['whitelist_skip']:,}")
    print(f"  新增入库: {result['saved']:,}")
    print(f"  重复跳过: {result['dup_skip']:,}")
    print(f"  耗时:   {elapsed}s")
    print()

    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="IRM CSV 导入")
    parser.add_argument("--csv-file", default=DEFAULT_CSV_FILE)
    parser.add_argument("--scope", choices=["tech_mvp", "all"], default=None)
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    asyncio.run(main(
        csv_file=args.csv_file,
        scope=args.scope,
        batch_size=args.batch_size,
        dry_run=args.dry_run,
    ))
```

- [ ] **Step 2: 更新 sync_minishare_irm_history.py**

修改 `source_type` 为 `minishare`：

```python
# 在 _batch_insert 和 sync_day 函数中，将 source_type 改为 "minishare"
"source_type": "minishare",  # 原来是 "irm_minishare"
```

---

## Task 4: 清理冗余脚本和代码

**Files:**
- Delete: `backend/scripts/sync_irm_local.py`
- Delete: `backend/scripts/sync_irm_tushare.py`
- Delete: `backend/scripts/sync_irm_history.py`

- [ ] **Step 1: 确认哪些脚本可以安全删除**

保留：
- `sync_minishare_irm_history.py` - minishare 增量同步（需修改 source_type）
- `sync_minishare_ann_history.py` - 公告同步（不相关）

删除：
- `sync_irm_local.py` - 使用 irm_local source_type，逻辑已被 import_irm_csv.py 替代
- `sync_irm_tushare.py` - 使用 irm_tushare source_type，逻辑已被 import_irm_csv.py 替代
- `sync_irm_history.py` - 调用 minishare_irm_history，冗余包装

- [ ] **Step 2: 删除冗余脚本**

```bash
cd /home/lwm/code/QingshuiYanTou
git rm backend/scripts/sync_irm_local.py
git rm backend/scripts/sync_irm_tushare.py
git rm backend/scripts/sync_irm_history.py
```

- [ ] **Step 3: 更新 shell 脚本**

检查 `backend/scripts/sync_irm.sh`：
- 如果调用被删除的脚本，需要更新
- 应该调用 `import_irm_csv.py` 和 `sync_minishare_irm_history.py`

---

## Task 5: 验证数据完整性

**Files:** 无（验证查询）

- [ ] **Step 1: 验证 source_type 统一**

```sql
SELECT source_type, COUNT(*) 
FROM announcements 
WHERE announcement_type LIKE 'irm:%'
GROUP BY source_type;
```

预期结果：只有 `minishare`

- [ ] **Step 2: 验证日期覆盖**

```sql
SELECT 
  MIN(ann_date) as earliest,
  MAX(ann_date) as latest,
  COUNT(*) as total,
  COUNT(DISTINCT ann_date) as trading_days
FROM announcements 
WHERE source_type = 'minishare'
  AND announcement_type LIKE 'irm:%';
```

预期：
- earliest: 2024-01-01（或 CSV 中最早日期）
- latest: 今天
- total: > 400,000

- [ ] **Step 3: 检查缺失日期**

```sql
-- 找出数据量异常少的日期
SELECT ann_date, COUNT(*) as cnt
FROM announcements 
WHERE source_type = 'minishare'
  AND announcement_type LIKE 'irm:%'
GROUP BY ann_date
HAVING COUNT(*) < 100
ORDER BY ann_date DESC
LIMIT 20;
```

- [ ] **Step 4: 运行 minishare 回补**

```bash
cd /home/lwm/code/QingshuiYanTou/backend

# 干跑测试
python -m scripts.sync_minishare_irm_history --dry-run --start-date 20260523 --end-date 20260622

# 正式回补（如果干跑结果正常）
python -m scripts.sync_minishare_irm_history --start-date 20260523 --end-date 20260622
```

- [ ] **Step 5: 最终验证**

```sql
-- 确认最新日期有足够数据
SELECT ann_date, COUNT(*) as cnt
FROM announcements 
WHERE source_type = 'minishare'
  AND announcement_type LIKE 'irm:%'
  AND ann_date >= '2026-06-01'
GROUP BY ann_date
ORDER BY ann_date DESC
LIMIT 10;
```

---

## 执行顺序

1. **Task 1**: 数据分析（确认覆盖范围）
2. **Task 2**: 清理数据库（统一 source_type）
3. **Task 3**: 创建/修改导入脚本
4. **Task 4**: 删除冗余脚本
5. **Task 5**: 验证和回补

---

## 风险与回滚

| 风险 | 缓解措施 |
|------|---------|
| 数据丢失 | Task 2 前创建备份表 |
| cninfo_id 冲突 | 使用 `ON CONFLICT DO NOTHING`，幂等 |
| 回补数据量过大 | 分批回补，观察进度 |

**回滚方案**：
```sql
-- 如果需要回滚，恢复备份
DELETE FROM announcements WHERE source_type = 'minishare' AND announcement_type LIKE 'irm:%';
INSERT INTO announcements SELECT * FROM announcements_irm_backup;
```
