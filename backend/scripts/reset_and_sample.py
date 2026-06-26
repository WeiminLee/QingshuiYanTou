"""
清空 Neo4j 并重新抽样抽取

执行步骤：
  1. 清空 Neo4j 所有节点和关系
  2. 从 kg_file_index 中选 5 个 status=done 的文件，重置为 pending
  3. 打印选中的文件列表（供后续抽取）

用法:
  uv run --directory backend python scripts/reset_and_sample.py
"""

import random
import sys
from pathlib import Path

import pymongo
from neo4j import GraphDatabase

# ── 加载 .env（直接读原始行，防编码问题）───────────────────────
env = {}
env_path = Path(__file__).resolve().parent.parent / ".env"
if env_path.exists():
    raw = env_path.read_bytes().decode("utf-8", errors="replace")
    for line in raw.splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            # 只取第一个 = 分隔（URL 中有多个 =）
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip()

URI = env.get("NEO4J_URL", "bolt://localhost:7687")
USER = env.get("NEO4J_USER", "neo4j")
PASSWORD = env.get("NEO4J_PASSWORD", "qingshui123")
MONGO_URL = env.get("MONGODB_URL", "")


def reset_and_sample(n: int = 5):
    # ── Step 1: 清空 Neo4j ──────────────────────────────
    driver = GraphDatabase.driver(URI, auth=(USER, PASSWORD))
    with driver.session() as s:
        # 统计清空前
        nc_before = s.run("MATCH (e) RETURN count(e) as c").single()["c"]
        rc_before = s.run("MATCH ()-[r]->() RETURN count(r) as c").single()["c"]

        # 删除所有节点（DETACH DELETE 会自动删关系）
        s.run("MATCH (n) DETACH DELETE n")
        print(f"[1/3] ✓ Neo4j 已清空（删除了 {nc_before} 节点, {rc_before} 关系）")

    driver.close()

    # ── Step 2: 选文件重置为 pending ───────────────────
    mc = pymongo.MongoClient(MONGO_URL)
    db = mc.get_database()
    coll = db["kg_file_index"]

    done_files = list(
        coll.find(
            {"status": {"$in": ["done", "failed"]}},
            {"_id": 0, "file_path": 1, "file_name": 1, "status": 1, "ts_code": 1},
        )
    )

    if not done_files:
        print("[2/3] ✗ 没有 status=done/failed 的文件可抽取")
        mc.close()
        return

    # 随机抽样（避免总是取前几个）
    sampled = random.sample(done_files, min(n, len(done_files)))

    paths = []
    print(f"\n[2/3] 选中 {len(sampled)} 个文件重置为 pending：")
    for f in sampled:
        coll.update_one(
            {"file_path": f["file_path"]},
            {
                "$set": {
                    "status": "pending",
                    "error": None,
                    "entities_count": 0,
                    "relations_count": 0,
                }
            },
        )
        print(f"  → {f['file_name']}  ({f['status']} → pending)")
        paths.append(f["file_path"])

    # ── Step 3: 统计 ───────────────────────────────────
    stats = coll.aggregate([{"$group": {"_id": "$status", "count": {"$sum": 1}}}])
    stat_map = {r["_id"]: r["count"] for r in stats}
    print("\n[3/3] kg_file_index 状态统计：")
    for status, count in sorted(stat_map.items()):
        print(f"  {status}: {count}")

    print("\n文件绝对路径（供后续抽取使用）：")
    for p in paths:
        print(f"  {p}")

    mc.close()
    print(f"\n✓ 完成！选中了 {len(paths)} 个文件，已重置为 pending。")
    print("  下一步：运行抽取命令（bash backend/scripts/start_all.sh --restart）")


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    reset_and_sample(n)
