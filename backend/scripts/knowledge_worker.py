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

EVIDENCE_JOB_TYPES = ("combined", "vector", "signal", "link")


async def run_evidence(settings: WorkerSettings, once: bool, limit: int | None, job_type: str) -> None:
    from app.knowledge.evidence_worker import EvidenceExtractionWorker

    worker = EvidenceExtractionWorker(max_concurrency=settings.concurrency)
    job_types = EVIDENCE_JOB_TYPES if job_type == "all" else (job_type,)
    while True:
        for jt in job_types:
            try:
                result = await worker.run_once(limit=limit, job_type=jt)
                if once or result.get("claimed", 0) > 0:
                    logger.info("Evidence worker result [%s]: %s", jt, result)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — 单类异常不应终止常驻 worker
                if once:
                    raise
                logger.warning("Evidence worker loop 异常，%ss 后继续: %s", settings.poll_interval, exc)
        if once:
            return
        await asyncio.sleep(settings.poll_interval)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="QingShui cloud knowledge worker")
    parser.add_argument("--role", default=None, choices=["evidence-extraction", "ingestion"])
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--job-type",
        default="all",
        choices=["combined", "vector", "signal", "link", "all"],
        help="Job type to process ('all' rotates combined/vector/signal/link)",
    )
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
