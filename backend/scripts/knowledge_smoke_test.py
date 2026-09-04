#!/usr/bin/env python3
"""Run bounded Evidence worker smoke stages and emit machine-readable results."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


async def run_stage(limit: int, job_type: str, concurrency: int) -> dict:
    from app.knowledge.evidence_service import EvidenceService
    from app.knowledge.evidence_worker import EvidenceExtractionWorker

    service = EvidenceService()
    before = await service.get_stats()
    started = time.monotonic()
    worker = EvidenceExtractionWorker(batch_size=max(1, min(concurrency, 5)), max_concurrency=concurrency)
    result = await worker.run_once(limit=limit, job_type=job_type)
    elapsed = time.monotonic() - started
    after = await service.get_stats()
    return {
        "limit": limit,
        "job_type": job_type,
        "concurrency": concurrency,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": round(elapsed, 3),
        "result": result,
        "before": before,
        "after": after,
    }


async def run(limits: list[int], job_type: str, concurrency: int, repeat: int) -> list[dict]:
    rows = []
    for iteration in range(1, repeat + 1):
        for limit in limits:
            row = await run_stage(limit, job_type, concurrency)
            row["iteration"] = iteration
            rows.append(row)
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bounded 10/100/1000 Evidence smoke test")
    parser.add_argument("--limits", default="10,100,1000", help="comma-separated stage limits")
    parser.add_argument("--job-type", default="combined", choices=("combined", "vector", "signal"))
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--output", help="optional JSON output path")
    args = parser.parse_args(argv)
    limits = [int(value) for value in args.limits.split(",") if value.strip()]
    if not limits or any(value <= 0 for value in limits) or args.concurrency <= 0 or args.repeat <= 0:
        parser.error("limits, concurrency and repeat must be positive")
    rows = asyncio.run(run(limits, args.job_type, args.concurrency, args.repeat))
    payload = json.dumps(rows, ensure_ascii=False, default=str, indent=2)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(payload + "\n")
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
