"""
Build A-share company alias table from cloud API.

[DEPRECATED 2026-05-09 — P1 Entity Resolution refactor]
The `company_aliases.json` file is no longer the primary source of truth.
PostgreSQL `stocks` + `company_profiles` tables are now authoritative,
loaded into memory via `StockNameResolver.warm_cache()` at app startup.

The 51 manually-curated entries (40 domestic with sector_tags + 11 overseas)
have been moved to `backend/data/supplemental_aliases.json`.

This script remains for backward compatibility but should not be run
unless you specifically need to regenerate the legacy `company_aliases.json`.

Fetches the full stock list from CloudDataClient.fetch_stocks(),
transforms each entry into company_aliases.json format, merges with
existing entries (preserving manual overrides), and writes the result.

Usage:
    # Incremental mode - add new entries only
    uv run --directory backend -- python scripts/build_alias_table.py

    # Full rebuild - replace cloud-sourced entries, keep manual ones
    uv run --directory backend -- python scripts/build_alias_table.py --full
"""

import argparse
import json
import logging
import sys
from pathlib import Path

# Ensure backend/ is on sys.path so app modules are importable
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

try:
    from app.core.data.cloud_api_client import (
        CloudDataClient,  # type: ignore[import-not-found]  # noqa: E402
    )
except ModuleNotFoundError:  # pragma: no cover - compatibility path for deprecated script
    from app.data_pipeline.data_source import DataSourceClient  # noqa: E402

    class CloudDataClient:  # type: ignore[no-redef]
        """Compatibility adapter for the deprecated alias-table script."""

        def __init__(self, base_url: str | None = None) -> None:
            self._client = DataSourceClient()

        def get_stocks(self) -> list[dict]:
            return self._client.get_stocks_basic("L")


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

ALIAS_FILE = BACKEND_DIR / "data" / "company_aliases.json"

CLOUD_API_BASE_URL = "http://124.221.188.38:8080/api/v1"

# Keys that indicate an entry was manually curated (has richer data than
# cloud can provide).  If any of these fields has a non-empty value, the
# entry is treated as manual and preserved during --full rebuild.
_MANUAL_INDICATOR_KEYS = ("sector_tags", "notes")


# ── Core Functions ──────────────────────────────────────────────────────────


def fetch_and_transform() -> dict[str, dict]:
    """Fetch all A-share stocks from cloud API and transform to alias format.

    Returns:
        Dict keyed by company name, each value is an alias entry dict.
    """
    client = CloudDataClient(base_url=CLOUD_API_BASE_URL)
    # get_stocks() correctly parses {"stocks": [...]} response format
    # (fetch_stocks() looks for "data"/"items" keys which don't match)
    stocks = client.get_stocks()

    if not stocks:
        logger.warning("fetch_stocks() returned 0 entries")
        return {}

    logger.info("Fetched %d stocks from cloud API", len(stocks))

    cloud_entries: dict[str, dict] = {}
    for stock in stocks:
        name = stock.get("name", "").strip()
        if not name:
            continue

        ts_code = stock.get("ts_code", "")
        industry = stock.get("industry", "")

        cloud_entries[name] = {
            "names": [name],
            "listing": True,
            "ts_code": ts_code,
            "industry_tags": [industry] if industry else [],
            "notes": "",
        }

    logger.info("Transformed %d cloud entries", len(cloud_entries))
    return cloud_entries


def _is_manual_entry(entry: dict) -> bool:
    """Return True if the entry appears to be manually curated."""
    for key in _MANUAL_INDICATOR_KEYS:
        val = entry.get(key)
        if isinstance(val, str) and val.strip():
            return True
        if isinstance(val, list) and len(val) > 0:
            return True
    return False


def merge_aliases(
    existing: dict[str, dict],
    cloud_entries: dict[str, dict],
    full_rebuild: bool = False,
) -> dict[str, dict]:
    """Merge cloud entries into existing aliases.

    Rules:
      - Incremental mode (full_rebuild=False):
          Existing entries are NEVER overwritten.
          New cloud entries are added.
      - Full rebuild mode (full_rebuild=True):
          Existing MANUAL entries are preserved.
          Existing CLOUD-SOURCED entries are replaced by fresh cloud data.
          New cloud entries are added.

    Args:
        existing: Current alias dict loaded from file.
        cloud_entries: Fresh entries from cloud API.
        full_rebuild: If True, replace cloud-sourced entries with fresh data.

    Returns:
        New merged dict (existing is not mutated).
    """
    # Start with a copy to preserve immutability
    merged: dict[str, dict] = {}

    if full_rebuild:
        # Keep only manual entries from existing
        for key, entry in existing.items():
            if _is_manual_entry(entry):
                merged[key] = entry
    else:
        # Incremental: keep all existing entries
        merged.update(existing)

    # Add cloud entries (do not overwrite anything already in merged)
    new_count = 0
    for key, entry in cloud_entries.items():
        if key not in merged:
            merged[key] = entry
            new_count += 1

    logger.info(
        "Merged: %d existing kept + %d new cloud entries = %d total",
        len(merged) - new_count,
        new_count,
        len(merged),
    )
    return merged


# ── I/O Helpers ─────────────────────────────────────────────────────────────


def load_aliases(path: Path) -> dict[str, dict]:
    """Load existing aliases from JSON file, return empty dict if missing."""
    if not path.exists():
        logger.info("No existing alias file at %s, starting fresh", path)
        return {}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    logger.info("Loaded %d existing aliases", len(data))
    return data


def save_aliases(path: Path, aliases: dict[str, dict]) -> None:
    """Write aliases dict to JSON file with sorted keys."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(aliases, f, ensure_ascii=False, indent=2)
        f.write("\n")
    logger.info("Saved %d aliases to %s", len(aliases), path)


# ── CLI ─────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Build A-share company alias table from cloud API")
    parser.add_argument(
        "--full",
        action="store_true",
        default=False,
        help="Full rebuild: replace cloud-sourced entries, keep manual ones",
    )
    args = parser.parse_args()

    mode = "FULL REBUILD" if args.full else "INCREMENTAL"
    logger.info("=== build_alias_table.py [%s] ===", mode)

    # Step 1: Fetch and transform cloud data
    cloud_entries = fetch_and_transform()
    if not cloud_entries:
        logger.error("No cloud data fetched, aborting")
        sys.exit(1)

    # Step 2: Load existing aliases
    existing = load_aliases(ALIAS_FILE)

    # Step 3: Merge
    merged = merge_aliases(existing, cloud_entries, full_rebuild=args.full)

    # Step 4: Save
    save_aliases(ALIAS_FILE, merged)

    # Step 5: Summary
    entry_count = len(merged)
    logger.info("Result: %d total entries in %s", entry_count, ALIAS_FILE)
    if entry_count < 5000:
        logger.warning(
            "Entry count (%d) is below 5000 target. Cloud API may have returned a partial list.",
            entry_count,
        )


if __name__ == "__main__":
    main()
