"""一次性迁移：把可解析到 A 股的 CO: Company 节点合并进 C:{ts_code} 节点。

- 依据 StockNameResolver（已含法名归一化/短名兜底）解析节点名 → ts_code
- 将 CO 节点的全部 RELATES 关系重挂到目标 C:{ts_code} 节点，然后删除该 CO 节点

用法（云端 venv，cwd=backend）：
    python -m scripts.merge_duplicate_companies --dry-run
    python -m scripts.merge_duplicate_companies
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("merge_dup_co")

from app.core.neo4j_client import run  # noqa: E402
from app.knowledge.entity_service import upsert_entity  # noqa: E402
from app.knowledge.stock_name_resolver import get_stock_name_resolver  # noqa: E402

_MOVE_OUT = """
MATCH (old:Company {entity_id: $old})-[r:RELATES]->(m)
MATCH (tgt:Company {entity_id: $tgt})
MERGE (tgt)-[nr:RELATES {valid_from: r.valid_from}]->(m)
SET nr += properties(r)
DELETE r
"""
_MOVE_IN = """
MATCH (m)-[r:RELATES]->(old:Company {entity_id: $old})
MATCH (tgt:Company {entity_id: $tgt})
MERGE (m)-[nr:RELATES {valid_from: r.valid_from}]->(tgt)
SET nr += properties(r)
DELETE r
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    resolver = get_stock_name_resolver()
    asyncio.run(resolver.warm_cache())

    cos = run(
        "MATCH (n:Company) WHERE n.entity_id STARTS WITH 'CO' RETURN n.entity_id AS eid, n.name AS name"
    )
    logger.info("CO: Company 节点: %d", len(cos))
    if args.limit:
        cos = cos[: args.limit]

    # 目标 C:{ts_code} → [(old_eid, canonical_name), ...]
    plan: dict[str, list] = {}
    for c in cos:
        eid = c.get("eid")
        name = c.get("name") or ""
        tgt, canonical = resolver.resolve_entity_id(name)
        if not tgt.startswith("C:"):
            continue
        if tgt == eid:
            continue
        plan.setdefault(tgt, []).append((eid, canonical or name))

    total = sum(len(v) for v in plan.values())
    logger.info("可合并 CO 节点: %d，覆盖 %d 个 A 股目标", total, len(plan))
    if args.dry_run:
        for tgt, items in list(plan.items())[:8]:
            logger.info("  %s <- %s", tgt, [it[0] for it in items][:4])
        print(f"RESULT dry_run mergeable={total} targets={len(plan)}")
        return 0

    merged = failed = 0
    for tgt, items in plan.items():
        ts_code = tgt[2:]
        try:
            upsert_entity(
                entity_id=tgt, entity_type="Company",
                name=items[0][1], ts_code=ts_code, confidence=0.9,
            )
            for old_eid, _ in items:
                try:
                    run(_MOVE_OUT, {"old": old_eid, "tgt": tgt})
                    run(_MOVE_IN, {"old": old_eid, "tgt": tgt})
                    run("MATCH (n:Company {entity_id: $old}) DETACH DELETE n", {"old": old_eid})
                    merged += 1
                except Exception as e:  # noqa: BLE001
                    failed += 1
                    logger.warning("合并失败 [%s -> %s]: %s", old_eid, tgt, e)
            if merged and merged % 2000 == 0:
                logger.info("已合并 %d ...", merged)
        except Exception as e:  # noqa: BLE001
            failed += 1
            logger.warning("目标节点创建失败 [%s]: %s", tgt, e)

    # 清理可能产生的自环（同一公司自己指向自己）
    run("MATCH (a:Company)-[r:RELATES]->(a) DELETE r", {})

    logger.info("完成: merged=%d failed=%d", merged, failed)
    print(f"RESULT merged={merged} failed={failed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
