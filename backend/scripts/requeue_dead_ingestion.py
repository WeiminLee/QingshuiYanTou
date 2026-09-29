"""把 dead 状态的 ingestion job 重新入队（修复处理器后回补）。

场景：pdf_download 曾被通用 ingestion worker 误判 dead（unsupported job_type），
修复（专用 PdfDownloadWorker + 通用 worker 类型白名单）上线后，用本脚本把存量
dead 重新消费。

用法（云端容器）：
  python -m scripts.requeue_dead_ingestion --dry-run
  python -m scripts.requeue_dead_ingestion --apply --job-type pdf_download
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--job-type", action="append", default=None)
    args = ap.parse_args()

    from sqlalchemy import text

    from app.core.database import engine
    from app.data_pipeline.job_queue import IngestionJobQueue

    types = args.job_type
    clause = "AND job_type = ANY(:types)" if types else ""
    params = {"types": types} if types else {}
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    f"SELECT job_type, count(*) FROM ingestion_jobs "
                    f"WHERE status='dead' {clause} GROUP BY job_type ORDER BY 2 DESC"
                ),
                params,
            )
        ).all()
    print("dead by type:", {r[0]: r[1] for r in rows})

    if not args.apply:
        print("dry-run：加 --apply 执行 requeue")
        return

    n = await IngestionJobQueue().requeue_dead(job_types=types)
    print(f"requeued = {n}")


if __name__ == "__main__":
    asyncio.run(main())
