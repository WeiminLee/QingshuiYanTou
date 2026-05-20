"""
Neo4j 关系时序字段回填脚本

问题：存量关系 edges 中 valid_to 全部为 NULL，
      导致同一 (from_entity, to_entity, rel_type) 可能存在多条"当前有效"边。

修复：对所有 valid_to IS NULL 的边，
      将 valid_to 回填为 valid_from（同一天自然结束，不丢历史精度）。
      之后新 upsert 会自动创建带正确 valid_from/to 的新边。

用法：
  uv run python scripts/backfill_relation_timestamps.py [--dry-run]
"""
import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from datetime import date
from app.core.neo4j_client import run, run_write


def backfill(dry_run: bool = True) -> dict:
    """
    对所有 valid_to IS NULL 的关系边，
    将 valid_to 回填为 valid_from。
    """
    today = str(date.today())
    now = str(date.today())

    # 统计：有多少条 open 边
    count_result = run(
        """MATCH ()-[r]->()
           WHERE r.valid_to IS NULL
           RETURN count(r) AS total
        """
    )
    total = count_result[0]["total"] if count_result else 0

    if total == 0:
        return {"status": "no_open_relations", "total": 0}

    if dry_run:
        # 预览前10条
        preview = run(
            """MATCH (a)-[r]->(b)
               WHERE r.valid_to IS NULL
               RETURN a.entity_id AS from_entity, type(r) AS rel_type,
                      b.entity_id AS to_entity, r.valid_from AS valid_from
               LIMIT 10
            """
        )
        return {
            "status": "dry_run",
            "total_open": total,
            "preview": preview,
            "message": f"共 {total} 条 open 关系，执行 --no-dry-run 正式写入",
        }

    # 正式回填
    run_write(
        """MATCH ()-[r]->()
           WHERE r.valid_to IS NULL
           SET r.valid_to = r.valid_from,
               r.updated_at = $now
        """,
        {"now": now},
    )
    return {"status": "done", "total_open": total}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Neo4j 关系时序字段回填")
    parser.add_argument("--no-dry-run", action="store_true", help="正式写入（默认 dry-run）")
    args = parser.parse_args()

    result = backfill(dry_run=not args.no_dry_run)
    print(f"[回填结果] {result['status']}")
    if result["status"] == "dry_run":
        print(f"共 {result['total_open']} 条 open 关系，前 10 条预览：")
        for r in result["preview"]:
            print(f"  {r['from_entity']} -[{r['rel_type']}]-> {r['to_entity']}  (from={r['valid_from']})")
        print(result["message"])
    else:
        print(f"已回填 {result.get('total_open', total)} 条 open 关系")
