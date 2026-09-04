#!/usr/bin/env python3
"""Run the durable PDF download worker."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from dotenv import load_dotenv

load_dotenv()

from app.knowledge.pdf_download_service import PdfDownloadWorker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _install_signal_handlers(stop_event: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            signal.signal(sig, lambda *_: stop_event.set())


async def _run_daemon(worker: PdfDownloadWorker, interval: float, limit: int | None) -> None:
    stop_event = asyncio.Event()
    _install_signal_handlers(stop_event)
    await worker.run_loop(interval_seconds=interval, limit_per_loop=limit, stop_event=stop_event)


def main() -> int:
    parser = argparse.ArgumentParser(description="PDF download worker")
    parser.add_argument("--once", action="store_true", help="Run one bounded pass")
    parser.add_argument("--daemon", action="store_true", help="Run until SIGINT/SIGTERM")
    parser.add_argument("--interval", type=float, default=30.0, help="Sleep seconds between daemon passes")
    parser.add_argument("--limit", type=int, default=None, help="Max jobs to process per pass")
    parser.add_argument("--concurrency", type=int, default=1, help="Max concurrent jobs")
    parser.add_argument("--timeout", type=int, default=180, help="PDF download timeout seconds")
    args = parser.parse_args()

    worker = PdfDownloadWorker(max_concurrency=args.concurrency, request_timeout_seconds=args.timeout)
    if args.daemon:
        asyncio.run(_run_daemon(worker, args.interval, args.limit))
        return 0

    result = asyncio.run(worker.run_once(limit=args.limit))
    logger.info("pdf download worker result: %s", result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
