#!/usr/bin/env python3
"""Unified entry point for cloud knowledge workers."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
try:
    from dotenv import load_dotenv
except ModuleNotFoundError:  # pragma: no cover - optional in minimal smoke images
    def load_dotenv() -> bool:
        return False

load_dotenv()

from app.ops.worker_config import WorkerSettings

logger = logging.getLogger(__name__)


async def run_evidence(settings: WorkerSettings, once: bool, limit: int | None, job_type: str) -> None:
    from app.knowledge.evidence_worker import EvidenceExtractionWorker

    worker = EvidenceExtractionWorker(max_concurrency=settings.concurrency)
    if once:
        result = await worker.run_once(limit=limit, job_type=job_type)
        logger.info("Evidence worker result: %s", result)
        return
    await worker.run_loop(interval_seconds=settings.poll_interval, limit_per_loop=limit, job_type=job_type)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="QingShui cloud knowledge worker")
    parser.add_argument("--role", default=None, choices=["evidence-extraction", "ingestion"])
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--job-type", default="combined")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--preflight", action="store_true", help="Check cloud dependencies before starting")
    args = parser.parse_args(argv)
    env = dict(os.environ)
    if args.role:
        env["WORKER_ROLE"] = args.role
    settings = WorkerSettings.from_environment(env)
    print(json.dumps({"role": settings.role, "concurrency": settings.concurrency,
                      "poll_interval": settings.poll_interval,
                      "job_timeout": settings.job_timeout,
                      "pdf_storage_root": settings.pdf_storage_root}, ensure_ascii=False))
    if args.dry_run:
        return 0
    if args.preflight:
        from scripts.worker_preflight import main as preflight_main
        if preflight_main([]) != 0:
            return 1
    if settings.role == "evidence-extraction":
        asyncio.run(run_evidence(settings, args.once, args.limit, args.job_type))
        return 0
    raise SystemExit("ingestion role must use scripts/ingestion_worker.py until unified dispatch is added")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    raise SystemExit(main())
