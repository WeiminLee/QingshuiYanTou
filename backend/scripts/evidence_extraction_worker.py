#!/usr/bin/env python3
"""CLI for Evidence extraction worker."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ.setdefault("UV_RUN", "1")

from dotenv import load_dotenv

load_dotenv()

from app.knowledge.evidence_worker import EvidenceExtractionWorker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description="Evidence extraction worker")
    parser.add_argument("--once", action="store_true", help="Run one bounded pass")
    parser.add_argument("--daemon", action="store_true", help="Run forever")
    parser.add_argument("--interval", type=int, default=30, help="Sleep seconds between daemon loops")
    parser.add_argument("--limit", type=int, default=None, help="Max jobs per once/loop pass")
    parser.add_argument("--job-type", type=str, default="combined", help="Job type to process")
    parser.add_argument("--max-concurrency", type=int, default=2, help="Max concurrent job handlers")
    args = parser.parse_args()

    worker = EvidenceExtractionWorker(max_concurrency=args.max_concurrency)
    if args.daemon:
        asyncio.run(worker.run_loop(interval_seconds=args.interval, limit_per_loop=args.limit, job_type=args.job_type))
        return 0
    result = asyncio.run(worker.run_once(limit=args.limit, job_type=args.job_type))
    logger.info("Evidence worker result: %s", result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
