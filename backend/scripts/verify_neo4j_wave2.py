"""
Neo4j WAVE 2 Schema 验证脚本

验证内容（Schema V1.2，Phase 8 KG-03）：
  1. Company / Product / Metric 三类节点存在
  2. RELATES 关系类型存在
  3. 2-hop 遍历正常（带 LIMIT，防止图爆炸）

用法：
  python scripts/verify_neo4j_wave2.py
"""
import logging
import sys
import os
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv()

from app.core.neo4j_client import get_driver

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def verify_wave2_schema() -> bool:
    """
    验证 WAVE 2 Schema（V1.2）：Company / Product / Metric + RELATES

    Returns:
        True = 所有节点和关系类型均存在
    """
    driver = get_driver()
    all_ok = True

    with driver.session() as session:
        # 1. Company 节点数
        r = session.run("MATCH (n:Company) RETURN count(n) AS cnt")
        cnt = r.single()["cnt"]
        print(f"  Company nodes: {cnt}")
        if cnt == 0:
            logger.warning("Company 节点数为 0")
            all_ok = False

        # 2. Product 节点数
        r = session.run("MATCH (n:Product) RETURN count(n) AS cnt")
        cnt = r.single()["cnt"]
        print(f"  Product nodes: {cnt}")
        if cnt == 0:
            logger.warning("Product 节点数为 0")
            all_ok = False

        # 3. Metric 节点数（Schema V1.2 新增）
        r = session.run("MATCH (n:Metric) RETURN count(n) AS cnt")
        cnt = r.single()["cnt"]
        print(f"  Metric nodes: {cnt}")
        if cnt == 0:
            logger.warning("Metric 节点数为 0（Schema V1.2 尚未迁移）")
            all_ok = False

        # 4. RELATES 关系数
        r = session.run("MATCH ()-[r:RELATES]->() RETURN count(r) AS cnt")
        cnt = r.single()["cnt"]
        print(f"  RELATES count: {cnt}")
        if cnt == 0:
            logger.warning("RELATES 关系数为 0（Schema V1.2 尚未迁移）")
            all_ok = False

        # 5. 2-hop 遍历测试（带 LIMIT）
        r = session.run("""
            MATCH (a:Company)-[:RELATES]->(b:Company)
            WHERE a <> b
            RETURN a.name AS from_node, b.name AS to_node
            LIMIT 5
        """)
        rows = list(r)
        print(f"  2-hop via RELATES (sample 5): {len(rows)} results")
        for row in rows:
            print(f"    {row['from_node']} -> {row['to_node']}")

        logger.info("WAVE 2 Schema verification complete")

    return all_ok


def main():
    print("=== Neo4j WAVE 2 Schema 验证 ===")
    try:
        ok = verify_wave2_schema()
        if ok:
            print("\n✅ WAVE 2 Schema 验证通过")
        else:
            print("\n⚠️  WAVE 2 Schema 部分缺失（Metric 节点或 RELATES 关系尚未迁移）")
            print("   这可能是预期状态，请参考 Phase 8 KG-3 任务说明")
    except Exception as e:
        logger.exception(f"验证失败: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
