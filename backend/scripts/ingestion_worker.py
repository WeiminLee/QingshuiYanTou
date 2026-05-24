#!/usr/bin/env python3
"""Run the durable ingestion job worker."""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.data_pipeline.job_worker import IngestionJobWorker


async def main() -> None:
    parser = argparse.ArgumentParser(description="Run ingestion jobs.")
    parser.add_argument("--once", action="store_true", help="Run one claim cycle and exit.")
    parser.add_argument("--limit", type=int, default=20, help="Maximum jobs to claim.")
    parser.add_argument(
        "--interval",
        type=float,
        default=5.0,
        help="Sleep interval when no jobs are claimed.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Per-job execution timeout in seconds.",
    )
    args = parser.parse_args()

    worker = IngestionJobWorker(job_timeout_seconds=args.timeout)
    if args.once:
        print(await worker.run_once(limit=args.limit))
    else:
        await worker.run_loop(limit=args.limit, interval_seconds=args.interval)


if __name__ == "__main__":
    asyncio.run(main())
