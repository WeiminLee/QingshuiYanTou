"""
KG V1.2 Migration Script

执行策略：全部重建
  1. DELETE all old-label nodes (Tech/Industry/Capacity/Event) and their relationships
  2. DELETE all old typed relationships (PRODUCES/SUPPLIES_TO/etc.)
  3. Re-extract from cloud API documents (research_report + announcement)
  4. Verify node counts per industry

Usage:
  uv run --directory backend python scripts/migrate_kg_v1_2.py --help
  uv run --directory backend python scripts/migrate_kg_v1_2.py --dry-run
  uv run --directory backend python scripts/migrate_kg_v1_2.py --industries 半导体 --industries 新能源
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import datetime

import httpx
import sys
BACKEND_DIR = r"/home/10241671/code/LocalProjects/QingShuiTouYan/backend"
sys.path.insert(0, BACKEND_DIR)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

CLOUD_API_BASE = "http://124.221.188.38:8080/api/v1"

# 5 target industries and their THS concept codes (TI format)
INDUSTRIES = {
    "半导体": "885806.TI",
    "新能源": "885126.TI",
    "医药": "885542.TI",
    "消费": "885600.TI",
    "软件": "885451.TI",
}


# ── Step 1: Delete old nodes ───────────────────────────────────────────

def delete_old_nodes(dry_run: bool = False) -> dict:
    """DELETE all Tech/Industry/Capacity/Event nodes and their typed relationships."""
    from app.core.neo4j_client import run_write, run

    old_labels = ["Tech", "Industry", "Capacity", "Event"]
    stats = {}

    for label in old_labels:
        count_result = run(f"MATCH (n:{label}) RETURN count(n) AS cnt", {})
        cnt = count_result[0]["cnt"] if count_result else 0
        if dry_run:
            logger.info("[DRY RUN] Would delete %d nodes with label :%s", cnt, label)
        else:
            run_write(f"MATCH (n:{label}) DETACH DELETE n")
            logger.info("Deleted %d nodes with label :%s", cnt, label)
        stats[label] = cnt

    # Delete all old typed relationships (keep RELATES)
    old_rel_types = [
        "PRODUCES", "SUPPLIES_TO", "DIRECTLY_SUPPLIES_TO", "BELONGS_TO",
        "USES", "APPLIES_TO", "COMPETES_WITH", "STATE_TRANSITION",
        "DISCLOSES", "CATALYZES", "CONSTRAINS", "SUBSTITUTES",
    ]
    rel_stats = {}
    for rel_type in old_rel_types:
        result = run(f"MATCH ()-[r:`{rel_type}`]->() RETURN count(r) AS cnt", {})
        cnt = result[0]["cnt"] if result else 0
        if dry_run:
            logger.info("[DRY RUN] Would delete %d relationships of type %s", cnt, rel_type)
        else:
            run_write(f"MATCH ()-[r:`{rel_type}`]->() DELETE r")
            logger.info("Deleted %d relationships of type %s", cnt, rel_type)
        rel_stats[rel_type] = cnt

    return {"nodes": stats, "relationships": rel_stats}


# ── Step 2: Fetch documents from cloud API ─────────────────────────────

async def fetch_industry_documents(
    industry_name: str,
    ths_code: str,
    limit_per_type: int = 30,
) -> list[dict]:
    """
    Fetch research_report + announcement documents for an industry from cloud API.

    Cloud API pattern:
      GET /api/v1/ann_ids?industry=885806.TI&source_type=research_report&limit=N
      GET /api/v1/data/{ann_id}  (to get full document content)
    """
    results = []
    # Use HTTP proxy explicitly (scheme= from URL, not SOCKS) for cloud API access
    explicit_proxy = httpx.Proxy("http://proxyhk.zte.com.cn:80")
    async with httpx.AsyncClient(timeout=60.0, proxy=explicit_proxy) as client:
        for source_type in ["research_report", "announcement"]:
            try:
                # Step A: get ann_id list for this industry+type
                ids_resp = await client.get(
                    f"{CLOUD_API_BASE}/ann_ids",
                    params={
                        "industry": ths_code,
                        "source_type": source_type,
                        "limit": limit_per_type,
                    },
                )
                if ids_resp.status_code != 200:
                    logger.warning(
                        "Cloud API /ann_ids returned %d for %s %s",
                        ids_resp.status_code, industry_name, source_type,
                    )
                    continue

                ids_data = ids_resp.json()
                ann_id_list = ids_data.get("ann_ids", [])
                if not ann_id_list:
                    logger.info("No %s ann_ids found for %s", source_type, industry_name)
                    continue

                logger.info(
                    "Found %d %s ann_ids for %s",
                    len(ann_id_list), source_type, industry_name,
                )

                # Step B: fetch each document's content
                for ann_id in ann_id_list:
                    try:
                        detail_resp = await client.get(
                            f"{CLOUD_API_BASE}/data/{ann_id}",
                            timeout=30.0,
                        )
                        if detail_resp.status_code == 200:
                            item = detail_resp.json()
                            item["_industry"] = industry_name
                            item["_source_type"] = source_type
                            item["ann_id"] = ann_id
                            results.append(item)
                        else:
                            logger.debug(
                                "Failed to fetch detail for %s: %d",
                                ann_id, detail_resp.status_code,
                            )
                    except Exception as e:
                        logger.debug("Error fetching ann_id %s: %s", ann_id, e)

            except Exception as e:
                logger.warning("Failed to fetch %s %s: %s", industry_name, source_type, e)

    return results


# ── Step 3: Re-extract documents via kg_extractor ──────────────────────

def extract_document_for_migration(doc: dict) -> dict:
    """Call kg_extractor.extract_text_async for a cloud API document."""
    from app.knowledge.kg_extractor import extract_text_async

    text = doc.get("content", "") or doc.get("text", "") or ""
    if not text:
        return {"error": "empty text", "ann_id": doc.get("ann_id", "unknown")}

    result = asyncio.run(extract_text_async(
        text=text[:50000],  # cap at 50k chars
        ts_code=doc.get("ts_code", ""),
        source_name=doc.get("title", "") or doc.get("source_name", ""),
        source_type=doc.get("_source_type", "research_report"),
        article_ref=doc.get("ann_id", ""),
    ))
    result["ann_id"] = doc.get("ann_id", "unknown")
    result["industry"] = doc.get("_industry")
    return result


# ── Step 4: Verify node counts ─────────────────────────────────────────

def verify_node_counts() -> dict:
    """
    Verify V1.2 node counts.

    Since Industry nodes are deleted in V1.2, per-industry coverage is verified
    by checking total Company + Product counts and logging a warning if totals
    suggest insufficient coverage across the 5 target industries.
    """
    from app.core.neo4j_client import run

    company_rows = run("MATCH (c:Company) RETURN count(c) AS cnt", {})
    product_rows = run("MATCH (p:Product) RETURN count(p) AS cnt", {})
    metric_rows = run("MATCH (m:Metric) RETURN count(m) AS cnt", {})

    total_company = company_rows[0]["cnt"] if company_rows else 0
    total_product = product_rows[0]["cnt"] if product_rows else 0
    total_metric = metric_rows[0]["cnt"] if metric_rows else 0

    # Check for any remaining old-label nodes (should be 0)
    old_label_counts = {}
    for label in ["Tech", "Industry", "Capacity", "Event"]:
        rows = run(f"MATCH (n:{label}) RETURN count(n) AS cnt", {})
        old_label_counts[label] = rows[0]["cnt"] if rows else 0

    return {
        "total_company": total_company,
        "total_product": total_product,
        "total_metric": total_metric,
        "old_label_counts": old_label_counts,
    }


# ── Main ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="KG V1.2 Migration Script")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--industries",
        nargs="+",
        choices=list(INDUSTRIES.keys()),
        default=list(INDUSTRIES.keys()),
    )
    parser.add_argument(
        "--skip-delete",
        action="store_true",
        help="Skip old node deletion (use when graph is already clean)",
    )
    parser.add_argument(
        "--docs-per-type",
        type=int,
        default=30,
        help="Number of documents per source type per industry (default: 30)",
    )
    args = parser.parse_args()

    logger.info("=== KG V1.2 Migration ===")
    logger.info("Industries: %s", args.industries)
    logger.info("Dry run: %s", args.dry_run)

    # Step 1: Delete old nodes
    if not args.skip_delete:
        logger.info("--- Step 1: Deleting old nodes ---")
        stats = delete_old_nodes(dry_run=args.dry_run)
        logger.info("Deletion complete: %s", stats)
    else:
        logger.info("--- Step 1: Skipped (--skip-delete) ---")

    # Step 2: Fetch documents and extract
    logger.info("--- Step 2: Fetching and re-extracting documents ---")
    total_docs = 0
    total_entities = 0
    total_relations = 0

    for industry in args.industries:
        ths_code = INDUSTRIES[industry]
        docs = asyncio.run(fetch_industry_documents(
            industry, ths_code, limit_per_type=args.docs_per_type,
        ))
        logger.info(
            "Fetched %d documents for %s (%s)",
            len(docs), industry, ths_code,
        )
        for doc in docs:
            total_docs += 1
            if not args.dry_run:
                result = extract_document_for_migration(doc)
                ent_count = result.get("entities_created", 0)
                rel_count = result.get("relations_created", 0)
                total_entities += ent_count
                total_relations += rel_count
                logger.info(
                    "Extracted ann_id=%s: entities=%d, relations=%d",
                    doc.get("ann_id", "unknown"),
                    ent_count,
                    rel_count,
                )

    logger.info(
        "Total: docs=%d, entities=%d, relations=%d",
        total_docs, total_entities, total_relations,
    )

    # Step 3: Verify
    if not args.dry_run:
        logger.info("--- Step 3: Verifying node counts ---")
        counts = verify_node_counts()
        logger.info(
            "Company nodes: %d  Product nodes: %d  Metric nodes: %d",
            counts["total_company"],
            counts["total_product"],
            counts["total_metric"],
        )
        logger.info("Old-label node counts (should all be 0): %s", counts["old_label_counts"])

        # Overall target: 5 industries x 50 = 250 Company+Product minimum
        total_viable = counts["total_company"] + counts["total_product"]
        if total_viable < 250:
            logger.warning(
                "WARNING: Total Company+Product = %d (target: >=250 for 5 industries)",
                total_viable,
            )
        else:
            logger.info("OK: Total Company+Product >= 250")

        return counts

    return {}


if __name__ == "__main__":
    main()
