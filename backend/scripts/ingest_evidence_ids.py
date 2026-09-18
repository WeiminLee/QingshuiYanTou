"""按 evidence_id 精准回填链接层（运维工具）。

用法:
  python -m scripts.ingest_evidence_ids EV:xxx EV:yyy ...
  echo -e "EV:xxx\nEV:yyy" | python -m scripts.ingest_evidence_ids -   # 从 stdin 读

精确补链指定证据（gold set 回填、单条修复），与 backfill_keyword_links 的
全量游标互不干扰；幂等（link PK 冲突 do-nothing）。
"""
from __future__ import annotations

import argparse
import asyncio
import sys

from app.core.database import async_session
from app.knowledge.linklayer.ingest import ingest_evidence


async def main() -> None:
    parser = argparse.ArgumentParser(description="按 evidence_id 精准回填链接层")
    parser.add_argument("evidence_ids", nargs="*", default=[])
    parser.add_argument("-", dest="stdin", action="store_true", help="从 stdin 读 ID 列表")
    args = parser.parse_args()

    ids = list(args.evidence_ids)
    if args.stdin:
        ids += [line.strip() for line in sys.stdin if line.strip()]
    if not ids:
        parser.error("需要至少一个 evidence_id（或 - 从 stdin 读）")

    done = failed = 0
    async with async_session() as session:
        for evidence_id in ids:
            try:
                result = await ingest_evidence(evidence_id, _session=session)
                done += 1
                print(f"{evidence_id[:20]}…: {result}")
            except Exception as exc:  # noqa: BLE001 — 单条失败不中断
                await session.rollback()
                failed += 1
                print(f"FAIL {evidence_id[:20]}…: {exc}")
    print(f"done={done} failed={failed}")


if __name__ == "__main__":
    asyncio.run(main())
