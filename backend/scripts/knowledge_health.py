#!/usr/bin/env python3
"""Print queue health and optionally recover stale running jobs."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
try:
    from dotenv import load_dotenv
except ModuleNotFoundError:  # pragma: no cover - optional in minimal smoke images
    def load_dotenv() -> bool:
        return False

load_dotenv()


async def run(recover_minutes: int | None = None) -> dict:
    from app.knowledge.evidence_service import EvidenceService

    service = EvidenceService()
    recovered = 0
    if recover_minutes is not None:
        recovered = await service.heal_running_jobs(older_than_minutes=recover_minutes)
    stats = await service.get_stats()
    stats["recovered_stale_jobs"] = recovered
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="QingShui knowledge queue health")
    parser.add_argument("--recover-stale-minutes", type=int, default=None)
    args = parser.parse_args(argv)
    print(json.dumps(asyncio.run(run(args.recover_stale_minutes)), ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
