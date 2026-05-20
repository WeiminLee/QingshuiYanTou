"""
KG Schema 清理脚本 v2（2026-04-14 重构版）

执行步骤：
1. 删除 Event / Tech / Industry / Capacity 节点
2. 迁移所有现存关系到统一 RELATES 类型（text + weight）
3. 删除无数值 Metric 节点
4. 统计清理结果

用法：
  uv run --directory backend python scripts/kg_cleanup_v2.py [--dry-run]

注意事项：
  - 执行前请备份 Neo4j 数据
  - dry-run 模式仅打印待删除/迁移的统计，不写入
  - 建议先在 dry-run 模式确认无误后再执行实际清理
"""
from __future__ import annotations

import sys
import os
# 确保 backend 目录在 sys.path（uv run --directory 时 app 模块可被找到）
_backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

# 手动加载 .env（config.py 的 env_file=".env" 相对 CWD，
# 而 uv run --directory backend 时 CWD=backend/，此时 .env 存在，但
# pydantic 可能在某些情况下找不到，手动加载确保一定生效）
_env_path = os.path.join(_backend_dir, ".env")
if os.path.exists(_env_path):
    with open(_env_path) as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

import argparse
import logging
import re
import sys
from datetime import date

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

DRY_RUN = False


def _run(cypher: str, params: dict | None = None, fetch: bool = False):
    """执行 Cypher 查询/写入，dry-run 模式下 stats 查询仍执行"""
    from app.core.neo4j_client import run_write, run

    if DRY_RUN and not fetch:
        logger.info("[DRY-RUN] WRITE: %s | params=%s", cypher[:80], params)
        return None

    if fetch:
        result = run(cypher, params=params) or []
        if DRY_RUN:
            logger.info("[DRY-RUN] FETCH: %s → %s", cypher[:60], result[:2] if result else "0 rows")
        return result
    else:
        run_write(cypher, params=params)
        return None


def _run_multi(cyphers: list[str]) -> None:
    """批量执行多个写操作（dry-run 打印）"""
    for c in cyphers:
        _run(c)


# ── Step 1：统计待删除节点 ──────────────────────────────────────────────────

def step0_stats() -> dict:
    """清理前统计：打印当前节点/关系数量"""
    logger.info("=" * 60)
    logger.info("【Step 0】清理前统计")
    logger.info("=" * 60)

    stats = {}

    for label in ["Company", "Product", "Metric", "Tech", "Industry", "Capacity", "Event"]:
        result = _run(f"MATCH (n:{label}) RETURN count(n) AS cnt", fetch=True)
        cnt = result[0]["cnt"] if result else 0
        stats[label] = cnt
        logger.info("  节点类型 %s: %d", label, cnt)

    rel_types = _run("CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType", fetch=True)
    rel_counts = {}
    for r in rel_types:
        rt = r["relationshipType"]
        result = _run(f"MATCH ()-[r:{rt}]->() RETURN count(r) AS cnt", fetch=True)
        cnt = result[0]["cnt"] if result else 0
        rel_counts[rt] = cnt
        logger.info("  关系类型 %s: %d", rt, cnt)

    stats["rel_counts"] = rel_counts
    return stats


# ── Step 1：删除旧节点类型 ───────────────────────────────────────────────────

def step1_delete_legacy_nodes() -> dict:
    """删除 Event / Tech / Industry / Capacity 节点"""
    logger.info("=" * 60)
    logger.info("【Step 1】删除旧节点类型（Event/Tech/Industry/Capacity）")
    logger.info("=" * 60)

    deleted = {}

    for label in ["Event", "Tech", "Industry", "Capacity"]:
        result = _run(f"MATCH (n:{label}) DETACH DELETE n RETURN count(n) AS deleted", fetch=True)
        cnt = result[0]["deleted"] if result else 0
        deleted[label] = cnt
        logger.info("  删除 %s 节点: %d", label, cnt)

    return deleted


# ── Step 2：迁移现存关系到 RELATES 类型 ───────────────────────────────────

def step2_migrate_relations() -> dict:
    """
    迁移所有现存关系到统一 RELATES 类型。

    规则：
    - 保留原关系的 description → 归入新边的 text 属性
    - 原 weight 字段 → 新边 weight（原无 weight 则默认 1.0）
    - original_type 记录原关系类型
    - valid_from / valid_to / source_type / source_name 全部平移
    """
    logger.info("=" * 60)
    logger.info("【Step 2】迁移所有关系统一为 RELATES 类型")
    logger.info("=" * 60)

    migrated: dict = {}
    today_str = date.today().isoformat()

    # 收集所有非 RELATES 关系类型
    rel_types = _run("CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType", fetch=True)
    non_relates = [
        r["relationshipType"]
        for r in rel_types
        if r["relationshipType"] not in ("RELATES",)
    ]

    for rel_type in non_relates:
        # 统计当前关系数
        count_result = _run(
            f"MATCH (a)-[r:{rel_type}]->(b) RETURN count(r) AS cnt",
            fetch=True,
        )
        total = count_result[0]["cnt"] if count_result else 0

        if total == 0:
            logger.info("  关系类型 %s: 0 条，跳过", rel_type)
            migrated[rel_type] = 0
            continue

        logger.info("  迁移关系类型 %s: %d 条 → RELATES", rel_type, total)

        # 迁移（CREATE 新边 + DELETE 旧边，同批次执行）
        _run(f"""
            MATCH (a)-[r:{rel_type}]->(b)
            CREATE (a)-[:RELATES {{
                text: coalesce(r.description, r.relation_description, ''),
                weight: coalesce(r.weight, 1.0),
                original_type: '{rel_type}',
                direction: coalesce(r.direction, 'neutral'),
                valid_from: coalesce(r.valid_from, date('{today_str}')),
                valid_to: r.valid_to,
                source_type: coalesce(r.source_type, 'unknown'),
                source_name: coalesce(r.source_name, 'unknown'),
                migrated_at: date('{today_str}'),
                created_at: coalesce(r.created_at, datetime())
            }}]->(b)
            WITH r
            DELETE r
        """)

        migrated[rel_type] = total

    return migrated


# ── Step 3：删除无数值 Metric 节点 ────────────────────────────────────────

def step3_cleanup_metrics() -> dict:
    """
    删除无数值（无量化数值）的 Metric 节点。

    Metric 入库规则：必须含量化数值（数字+单位），无数值的 Metric 不入库。
    无数值指：description 为空或不包含数字+单位（% / 亿元 / 万元 / 元 / 亿 / 万等）
    """
    logger.info("=" * 60)
    logger.info("【Step 3】删除无数值 Metric 节点")
    logger.info("=" * 60)

    # 先找出无数值 Metric
    result = _run("""
        MATCH (m:Metric)
        WHERE m.description IS NULL
           OR m.description = ''
           OR NOT m.description =~ '.*\\\\d+.*'
        RETURN count(m) AS cnt
    """, fetch=True)
    cnt = result[0]["cnt"] if result else 0
    logger.info("  无数值 Metric 节点: %d", cnt)

    if cnt > 0 and not DRY_RUN:
        _run("""
            MATCH (m:Metric)
            WHERE m.description IS NULL
               OR m.description = ''
               OR NOT m.description =~ '.*\\\\d+.*'
            DETACH DELETE m
        """)
        logger.info("  已删除无数值 Metric 节点: %d", cnt)

    return {"deleted": cnt}


# ── Step 4：验证结果 ─────────────────────────────────────────────────────────

def step4_validate() -> dict:
    """验证清理后状态"""
    logger.info("=" * 60)
    logger.info("【Step 4】清理后验证")
    logger.info("=" * 60)

    stats = {}

    # 只保留 3 类实体
    for label in ["Company", "Product", "Metric"]:
        result = _run(f"MATCH (n:{label}) RETURN count(n) AS cnt", fetch=True)
        cnt = result[0]["cnt"] if result else 0
        stats[label] = cnt
        logger.info("  保留节点类型 %s: %d", label, cnt)

    # 确认旧类型已删除
    for label in ["Tech", "Industry", "Capacity", "Event"]:
        result = _run(f"MATCH (n:{label}) RETURN count(n) AS cnt", fetch=True)
        cnt = result[0]["cnt"] if result else 0
        if cnt > 0:
            logger.warning("  ⚠️  仍有 %s 节点残留: %d", label, cnt)
        else:
            logger.info("  ✅ %s 节点已清空", label)

    # 关系统计
    relates_count = _run("MATCH ()-[r:RELATES]->() RETURN count(r) AS cnt", fetch=True)
    cnt = relates_count[0]["cnt"] if relates_count else 0
    stats["relates_count"] = cnt
    logger.info("  RELATES 关系总数: %d", cnt)

    # 确认无旧类型关系残留
    rel_types = _run("CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType", fetch=True)
    legacy_rels = [
        r["relationshipType"]
        for r in rel_types
        if r["relationshipType"] not in ("RELATES", "CONTRADICTS")
    ]
    if legacy_rels:
        for rt in legacy_rels:
            result = _run(f"MATCH ()-[r:{rt}]->() RETURN count(r) AS cnt", fetch=True)
            cnt = result[0]["cnt"] if result else 0
            if cnt > 0:
                logger.warning("  ⚠️  仍有 %s 关系残留: %d", rt, cnt)
    else:
        logger.info("  ✅ 所有旧关系类型已迁移为 RELATES")

    # Metric 节点量化校验
    metric_no_value = _run("""
        MATCH (m:Metric)
        WHERE m.description IS NULL
           OR m.description = ''
           OR NOT m.description =~ '.*\\\\d+.*'
        RETURN count(m) AS cnt
    """, fetch=True)
    cnt = metric_no_value[0]["cnt"] if metric_no_value else 0
    if cnt > 0:
        logger.warning("  ⚠️  无数值 Metric 节点残留: %d", cnt)
    else:
        logger.info("  ✅ 所有 Metric 节点均含量化数值")

    return stats


# ── 主入口 ──────────────────────────────────────────────────────────────────

def main():
    global DRY_RUN

    parser = argparse.ArgumentParser(description="KG Schema 清理脚本 v2")
    parser.add_argument("--dry-run", action="store_true", help="仅打印，不写入")
    args = parser.parse_args()
    DRY_RUN = args.dry_run

    logger.info("KG Schema 清理脚本 v2（2026-04-14 重构）")
    logger.info("模式: %s", "DRY-RUN（仅预览）" if DRY_RUN else "正式执行")
    logger.info("")
    logger.info("⚠️  正式执行前请备份 Neo4j 数据！")
    logger.info("")

    # Step 0: 清理前统计
    step0_stats()

    if DRY_RUN:
        logger.info("")
        logger.info("【DRY-RUN 模式】以下操作将被跳过")
        return

    # Step 1: 删除旧节点
    step1_delete_legacy_nodes()

    # Step 2: 迁移关系到 RELATES
    step2_migrate_relations()

    # Step 3: 删除无数值 Metric
    step3_cleanup_metrics()

    # Step 4: 验证
    step4_validate()

    logger.info("")
    logger.info("✅ KG Schema 清理完成！")


if __name__ == "__main__":
    main()
