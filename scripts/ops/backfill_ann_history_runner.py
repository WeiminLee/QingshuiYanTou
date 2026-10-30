#!/usr/bin/env python3
"""公告历史回补 runner（chemagent 容器内一次性任务）。

走每日采集同一路径 DataFetcher.fetch_minishare_announcements：
- 写 minishare_announcements（evidence 管线读这张表）
- 入队 pdf_download，由 qingshui-pdf-worker 下载并就地构建 evidence

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
LOG = os.path.join(OPS_DIR, "backfill_ann_history.log")
CURSOR = os.path.join(OPS_DIR, "backfill_ann_history.cursor")
MAX_QUEUE = 300
SLEEP = 30


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
    totals = {"days": 0, "new": 0, "skip": 0, "fail": 0, "errors": 0}
    d = start
    while d <= END:
        while True:
            q = await pending_pdf()
            if q < MAX_QUEUE:
                break
            log(f"throttle pdf_queue={q} >= {MAX_QUEUE}, sleep {SLEEP}s")
            await asyncio.sleep(SLEEP)

        ds = d.strftime("%Y%m%d")
        r = None
        for attempt in range(3):
            try:
                r = await fetcher.fetch_minishare_announcements(ann_date=ds)
                break
            except Exception as exc:  # noqa: BLE001
                log(f"{ds} ERROR attempt={attempt + 1} {type(exc).__name__}: {str(exc)[:200]}")
                await asyncio.sleep(5)

        if r is None:
            totals["errors"] += 1
            log(f"{ds} GIVE UP")
        else:
            totals["days"] += 1
            totals["new"] += int(r.get("success", 0) or 0)
            totals["skip"] += int(r.get("skipped", 0) or 0)
            totals["fail"] += int(r.get("fail", 0) or 0)
            if int(r.get("success", 0) or 0) > 0 or d.weekday() == 4:
                log(
                    f"{ds} new={r.get('success')} skip={r.get('skipped')} "
                    f"fail={r.get('fail')} q={q}"
                )

        with open(CURSOR, "w", encoding="utf-8") as f:
            f.write(d.isoformat())
        d += timedelta(days=1)

    log(f"DONE {totals}")


if __name__ == "__main__":
    asyncio.run(main())
