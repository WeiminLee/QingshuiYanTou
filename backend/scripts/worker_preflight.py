#!/usr/bin/env python3
"""Check TCP reachability of cloud services before starting a worker."""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from app.ops.preflight import check_tcp


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Remote worker dependency preflight")
    parser.add_argument("--mongo", default=os.getenv("MONGODB_URL", "mongodb://10.20.0.1:27018/qingshui"))
    parser.add_argument(
        "--postgres",
        default=os.getenv("DATABASE_URL", "postgresql://10.20.0.1:5433/qingshui"),
    )
    parser.add_argument("--qdrant", default=os.getenv("QDRANT_URL", "http://10.20.0.1:6333"))
    parser.add_argument("--api-only", action="store_true", default=bool(os.getenv("KNOWLEDGE_API_URL")))
    args = parser.parse_args(argv)
    if args.api_only:
        import pathlib, urllib.request
        api = os.getenv("KNOWLEDGE_API_URL", "").rstrip("/")
        key = os.getenv("KNOWLEDGE_API_KEY", "")
        checks = []
        try:
            with urllib.request.urlopen(api + "/health", timeout=5) as response:
                checks.append({"name": "knowledge_api", "target": api, "ok": response.status == 200, "error": None})
        except Exception as exc:
            checks.append({"name": "knowledge_api", "target": api, "ok": False, "error": str(exc)})
        root = pathlib.Path(os.getenv("PDF_STORAGE_ROOT", "/data/qingshui-pdfs"))
        checks.append({"name": "pdf_storage", "target": str(root), "ok": root.is_dir() and os.access(root, os.W_OK), "error": None})
        checks.append({"name": "api_key", "target": "X-API-Key", "ok": bool(key), "error": None if key else "KNOWLEDGE_API_KEY is empty"})
    else:
        checks = [
        check_tcp("mongo", args.mongo),
        check_tcp("postgres", args.postgres),
        check_tcp("qdrant", args.qdrant),
        ]
    print(json.dumps([c if isinstance(c, dict) else c.__dict__ for c in checks], ensure_ascii=False))
    return 0 if all(c["ok"] if isinstance(c, dict) else c.ok for c in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
