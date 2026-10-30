#!/usr/bin/env python3
"""公告历史回补 runner v2（chemagent 容器内一次性任务）。

走每日采集同一路径 DataFetcher.fetch_minishare_announcements：
- 写 minishare_announcements（evidence 管线读这张表）
- 入队 pdf_download，由 qingshui-pdf-worker 下载并就地构建 evidence

v2 修复：
- 日期之间 2s 节流（v1 跑太快被接口限流，部分交易日返回空）
- 工作日返回 0 条时重试 3 次（10s 间隔），仍为空则记 SUSPECT
- 每天都记日志（含 raw 总数），便于审计

带队列限流：待处理 PDF 任务超过 MAX_QUEUE 时暂停拉取，
避免把每日 23:00 的新公告堵在历史任务后面。

断点续跑：每完成一天写 cursor 文件，重启后从下一天继续。
"""

from __future__ import annotations

import asyncio
import os
import time
from datetime import date, timedelta

from sqlalchemy import text

from app.core.database import engine
from app.data_pipeline.fetcher import DataFetcher

START = date(2024, 8, 28)
END = date(2026, 9, 29)  # 2026-09-30 起已由 30 天回补覆盖
OPS_DIR = "/data/qingshui/pdf/_ops"
LOG = os.path.join(OPS_DIR, "backfill_ann_history_v2.log")
CURSOR = os.path.join(OPS_DIR, "backfill_ann_history_v2.cursor")
MAX_QUEUE = 300
SLEEP_QUEUE = 30
MIN_INTERVAL = 2.0
EMPTY_RETRIES = 3
EMPTY_RETRY_SLEEP = 10


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


async def pending_pdf() -> int:
    async with engine.connect() as conn:
        r = await conn.execute(
            text(
                "SELECT count(*) FROM ingestion_jobs "
                "WHERE job_type='pdf_download' AND status IN ('pending','running','claimed')"
            )
        )
        return int(r.scalar() or 0)


async def fetch_day(fetcher: DataFetcher, ds: str, weekday: bool) -> dict | None:
    """抓一天；工作日空结果重试，避免限流把空响应当成"当天无公告"。"""
    r: dict | None = None
    for attempt in range(EMPTY_RETRIES + 1):
        try:
            r = await fetcher.fetch_minishare_announcements(ann_date=ds)
        except Exception as exc:  # noqa: BLE001
            log(f"{ds} ERROR attempt={attempt + 1} {type(exc).__name__}: {str(exc)[:200]}")
            await asyncio.sleep(EMPTY_RETRY_SLEEP)
            continue
        total = int(r.get("success", 0) or 0) + int(r.get("skipped", 0) or 0) + int(r.get("fail", 0) or 0)
        if total > 0 or not weekday:
            return r
        log(f"{ds} empty on weekday, retry {attempt + 1}/{EMPTY_RETRIES}")
        await asyncio.sleep(EMPTY_RETRY_SLEEP)
    log(f"{ds} SUSPECT still empty after retries")
    return r


async def main() -> None:
    os.makedirs(OPS_DIR, exist_ok=True)
    start = START
    if os.path.exists(CURSOR):
        try:
            with open(CURSOR, encoding="utf-8") as f:
                start = date.fromisoformat(f.read().strip()) + timedelta(days=1)
        except Exception:
            pass
    log(f"START {start.isoformat()} ~ {END.isoformat()}")
    fetcher = DataFetcher()
    totals = {"days": 0, "new": 0, "skip": 0, "fail": 0, "errors": 0, "suspect": 0}
    d = start
    while d <= END:
        while True:
            q = await pending_pdf()
            if q < MAX_QUEUE:
                break
            log(f"throttle pdf_queue={q} >= {MAX_QUEUE}, sleep {SLEEP_QUEUE}s")
            await asyncio.sleep(SLEEP_QUEUE)

        t0 = time.time()
        ds = d.strftime("%Y%m%d")
        r = await fetch_day(fetcher, ds, d.weekday() < 5)
        if r is None:
            totals["errors"] += 1
        else:
            totals["days"] += 1
            totals["new"] += int(r.get("success", 0) or 0)
            totals["skip"] += int(r.get("skipped", 0) or 0)
            totals["fail"] += int(r.get("fail", 0) or 0)
            total = int(r.get("success", 0) or 0) + int(r.get("skipped", 0) or 0) + int(r.get("fail", 0) or 0)
            if total == 0 and d.weekday() < 5:
                totals["suspect"] += 1
            log(
                f"{ds} total={total} new={r.get('success')} skip={r.get('skipped')} "
                f"fail={r.get('fail')} q={q} {time.time() - t0:.1f}s"
            )

        with open(CURSOR, "w", encoding="utf-8") as f:
            f.write(d.isoformat())
        d += timedelta(days=1)
        await asyncio.sleep(MIN_INTERVAL)

    log(f"DONE {totals}")


if __name__ == "__main__":
    asyncio.run(main())
