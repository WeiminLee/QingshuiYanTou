"""一次性迁移：为缺失 description 的实体，从关联关系文本派生一句描述。

不改抽取（避免全量重抽），仅用已有 RELATES 的 text 作为实体描述种子。
用法（云端 venv，cwd=backend）：
    python -m scripts.backfill_entity_descriptions --dry-run
    python -m scripts.backfill_entity_descriptions
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("backfill_desc")

from app.core.neo4j_client import run  # noqa: E402

_LABELS = ("Company", "Product", "Metric")

# 每个缺失描述的节点，取一条关联关系的 text 作为描述（CALL 子查询内 LIMIT 1，避免 collect 膨胀）
_BACKFILL_TMPL = """
MATCH (n:{label})
WHERE n.description IS NULL OR n.description = ''
CALL {{
  WITH n
  MATCH (n)-[r:RELATES]-()
  RETURN r.text AS t
  LIMIT 1
}}
SET n.description = left(coalesce(t, ''), 200)
RETURN count(n) AS updated
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    for label in _LABELS:
        miss = run(
            f"MATCH (n:{label}) WHERE n.description IS NULL OR n.description = '' RETURN count(n) AS c"
        )[0]["c"]
        logger.info("%s 缺描述: %d", label, miss)
        if args.dry_run:
            continue
        res = run(_BACKFILL_TMPL.format(label=label))
        logger.info("%s 回填: %s", label, res)

    if not args.dry_run:
        for label in _LABELS:
            miss = run(
                f"MATCH (n:{label}) WHERE n.description IS NULL OR n.description = '' RETURN count(n) AS c"
            )[0]["c"]
            logger.info("%s 回填后仍缺描述: %d", label, miss)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
