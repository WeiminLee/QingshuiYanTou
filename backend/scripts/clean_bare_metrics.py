"""一次性迁移：删除 Neo4j 中"无主体"的裸值 Metric 节点（如 5000万元、0.59%）。

判定复用 rag_extractor._is_bare_metric。
用法（云端 venv，cwd=backend）：
    python -m scripts.clean_bare_metrics --dry-run
    python -m scripts.clean_bare_metrics
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("clean_bare_metric")

from app.core.neo4j_client import run  # noqa: E402
from app.knowledge.extraction.rag_extractor import _is_bare_metric  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    total = run("MATCH (n:Metric) RETURN count(n) AS c")[0]["c"]
    rows = run("MATCH (n:Metric) RETURN n.entity_id AS eid, n.name AS name")
    bare = [r["eid"] for r in rows if _is_bare_metric(r.get("name") or "")]
    logger.info("Metric 总数=%d  裸值(无主体)=%d", total, len(bare))
    sample = [r.get("name") for r in rows if _is_bare_metric(r.get("name") or "")][:10]
    logger.info("样例: %s", sample)

    if args.dry_run:
        print(f"RESULT bare={len(bare)} total={total}")
        return 0

    if args.limit:
        bare = bare[: args.limit]
    for i in range(0, len(bare), 500):
        run("MATCH (n:Metric) WHERE n.entity_id IN $ids DETACH DELETE n", {"ids": bare[i : i + 500]})
    left = run("MATCH (n:Metric) RETURN count(n) AS c")[0]["c"]
    logger.info("删除完成: 删除 %d，Metric 剩余 %d", len(bare), left)
    print(f"RESULT deleted={len(bare)} remaining={left}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
