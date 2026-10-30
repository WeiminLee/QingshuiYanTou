#!/usr/bin/env python3
"""海外核心股日线回填（美股 / 台股 / 韩股）。

用法：
    python -m scripts.backfill_overseas --range 2y
    python -m scripts.backfill_overseas --markets US,TW --range 1y
"""

from __future__ import annotations

import argparse
import asyncio
import json

from app.data_pipeline.overseas_client import sync_markets


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--markets", default="US,TW,KR", help="逗号分隔：US,TW,KR")
    ap.add_argument("--range", default="2y", help="Yahoo range，如 1mo/6mo/1y/2y")
    args = ap.parse_args()
    markets = [m.strip().upper() for m in args.markets.split(",") if m.strip()]
    summary = asyncio.run(sync_markets(markets, range_=args.range))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
