"""一次性迁移：重算 Neo4j 全部 RELATES 的 relation_subtype。

修复历史「无命中默认 SUPPLIES_TO」导致 98% 关系被误标为供应链的问题。
规则单一来源：直接复用 relation_service._ORDERED_RULES 生成 Cypher CASE。

用法（云端 venv，cwd=backend）：
    python -m scripts.reclassify_relation_subtypes
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("reclassify_rel")

from app.core.neo4j_client import run  # noqa: E402
from app.knowledge.relation_service import _ORDERED_RULES  # noqa: E402


def _dist() -> dict:
    return {r["sub"]: r["c"] for r in run(
        "MATCH ()-[r:RELATES]->() RETURN r.relation_subtype AS sub, count(*) AS c"
    )}


def main() -> int:
    before = _dist()
    logger.info("重算前分布: %s", before)

    # 1) 指向 Metric 的关系 → HAS_METRIC（指标关系，非供应链）
    run("MATCH ()-[r:RELATES]->(b:Metric) SET r.relation_subtype = 'HAS_METRIC'")

    # 2) 其余：有序规则 CASE（与 Python infer_relation_type 一致）
    lines = ["CASE", "  WHEN r.text IS NULL OR r.text = '' THEN 'RELATED'"]
    for name, pat in _ORDERED_RULES:
        lines.append(f"  WHEN r.text =~ '.*({pat.pattern}).*' THEN '{name}'")
    lines.append("  ELSE 'RELATED' END")
    case_expr = "\n".join(lines)
    run(f"MATCH (a)-[r:RELATES]->(b) WHERE NOT b:Metric SET r.relation_subtype = {case_expr}")

    after = _dist()
    logger.info("重算后分布: %s", after)
    print("RESULT", after)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
