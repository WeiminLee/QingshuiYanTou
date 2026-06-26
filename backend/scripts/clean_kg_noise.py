"""
清理 Neo4j 中的噪声数据

用法:
  uv run --directory backend python -c "
from scripts.clean_kg_noise import clean_noise
clean_noise()
"

清理内容:
  1. 删除所有 Event 节点（V1.2 Schema 已废弃）
  2. 删除无效 Company:
     - 名称含"研究所"、"研究院"、"基金"、"资产管理"
     - 名称含"http"、"@"、"Email"
     - 名称长度 > 50
  3. 删除关联的 RELATES 关系
"""

from pathlib import Path

from neo4j import GraphDatabase

# ── 加载 .env ──────────────────────────────────────────────────────
env = {}
env_path = Path(__file__).resolve().parent.parent / ".env"
if env_path.exists():
    raw = env_path.read_bytes().decode("utf-8", errors="replace")
    for line in raw.splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip()

URI = env.get("NEO4J_URL", "bolt://localhost:7687")
USER = env.get("NEO4J_USER", "neo4j")
PASSWORD = env.get("NEO4J_PASSWORD", "qingshui123")


def clean_noise():
    driver = GraphDatabase.driver(URI, auth=(USER, PASSWORD))

    with driver.session() as s:
        # ── 统计清理前的数量 ───────────────────────────────────────
        before_entities = s.run("MATCH (e) RETURN count(e) as c").single()["c"]
        before_rels = s.run("MATCH ()-[r]->() RETURN count(r) as c").single()["c"]
        before_events = s.run("MATCH (e:Event) RETURN count(e) as c").single()["c"]
        print(f"清理前: {before_entities} 节点, {before_rels} 关系, {before_events} Event 节点")

        # ── Step 1: 删除无效 Company ────────────────────────────
        invalid_company_patterns = [
            r".*研究所.*",
            r".*研究院.*",
            r".*基金管理.*",
            r".*资产管理.*",
            r".*证券经纪.*",
            r".*投资咨询.*",
            r"http.*",
            r".*@.*",
            r".*Email.*",
        ]
        pattern = "|".join(f"(?i){p}" for p in invalid_company_patterns)

        # 先查出要删的节点
        invalid_companies = s.run(
            """
            MATCH (e:Company)
            WHERE e.name =~ $pattern OR size(e.name) > 50
            RETURN e.name as name, e.entity_id as eid
            """,
            pattern=pattern,
        ).data()

        if invalid_companies:
            print(f"\n无效 Company 节点（将删除 {len(invalid_companies)} 个）:")
            for c in invalid_companies:
                print(f"  删除: {c['name']} ({c['eid']})")

            # 删除这些 Company 的关系再删节点
            s.run(
                """
                MATCH (e:Company)
                WHERE e.name =~ $pattern OR size(e.name) > 50
                DETACH DELETE e
                """,
                pattern=pattern,
            )
            print(f"  → 已删除 {len(invalid_companies)} 个无效 Company")
        else:
            print("\n无效 Company 节点: 无")

        # ── Step 2: 删除所有 Event 节点（V1.2 Schema 废弃）─────────
        event_count = s.run("MATCH (e:Event) DETACH DELETE e RETURN count(e) as c").single()["c"]
        print(f"\n已删除 {event_count} 个 Event 节点")

        # ── 统计清理后的数量 ──────────────────────────────────────
        after_entities = s.run("MATCH (e) RETURN count(e) as c").single()["c"]
        after_rels = s.run("MATCH ()-[r]->() RETURN count(r) as c").single()["c"]
        print(f"\n清理后: {after_entities} 节点, {after_rels} 关系")
        print(f"净减少: {before_entities - after_entities} 节点, {before_rels - after_rels} 关系")

    driver.close()
    print("\n清理完成 ✓")


if __name__ == "__main__":
    clean_noise()
