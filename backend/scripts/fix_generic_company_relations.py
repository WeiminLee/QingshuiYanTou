"""一次性迁移：把 Neo4j 中泛称端点(公司/本公司/...)的关系改挂到标准 Company 节点。

依据每条 RELATES 的 evidence_id → Mongo kg_evidence.subject_hint → 标准公司名/ts_code。
用法（云端 venv，cwd=backend）：
    python -m scripts.fix_generic_company_relations --dry-run
    python -m scripts.fix_generic_company_relations
"""

import argparse
import logging
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("fix_generic")

from app.config import settings  # noqa: E402
from app.core.neo4j_client import run  # noqa: E402
from app.knowledge.entity_service import upsert_entity  # noqa: E402

_GENERIC = {
    "公司", "本公司", "贵公司", "该公司", "上市公司", "标的公司", "目标公司", "标的",
    "本集团", "该集团", "集团", "本企业", "该企业", "企业", "本行", "本银行",
    "我们", "我司", "我公司",
}
_GENERIC_RE = re.compile(r"^(本|该|贵|标的|目标|上市)?(公司|集团|企业|银行?|行)$")


def is_generic(name: str) -> bool:
    n = (name or "").strip()
    return n in _GENERIC or bool(_GENERIC_RE.match(n))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    from pymongo import MongoClient

    mongo = MongoClient(settings.mongodb_url)
    ev_coll = mongo.get_default_database()["kg_evidence"]

    generic_list = list(_GENERIC)
    rels = run(
        """
        MATCH (a)-[r:RELATES]->(b)
        WHERE (a:Company AND a.name IN $names) OR (b:Company AND b.name IN $names)
        RETURN elementId(r) AS rid, properties(r) AS props,
               a.entity_id AS aeid, b.entity_id AS beid,
               labels(a)[0] AS alabel, labels(b)[0] AS blabel,
               a.name AS aname, b.name AS bname,
               (a:Company AND a.name IN $names) AS a_generic,
               (b:Company AND b.name IN $names) AS b_generic
        """,
        {"names": generic_list},
    )
    logger.info("泛称端点关系总数: %d", len(rels))
    if args.limit:
        rels = rels[: args.limit]

    ev_ids = list({str((r["props"] or {}).get("evidence_id") or "") for r in rels} - {""})
    ev_map: dict[str, dict] = {}
    for i in range(0, len(ev_ids), 1000):
        batch = ev_ids[i : i + 1000]
        for d in ev_coll.find({"evidence_id": {"$in": batch}}, {"evidence_id": 1, "subject_hint": 1}):
            sh = d.get("subject_hint") or {}
            if sh.get("ts_code"):
                ev_map[d["evidence_id"]] = {"ts_code": sh.get("ts_code"), "name": sh.get("company_name")}
    logger.info("evidence 主体映射: %d/%d", len(ev_map), len(ev_ids))

    # ts_code → 标准公司名（从已有 Company 节点取，补齐 evidence 缺 company_name 的情况）
    tc_to_name: dict[str, str] = {}
    for row in run(
        """
        MATCH (n:Company)
        WHERE n.ts_code IS NOT NULL AND n.ts_code <> '' AND NOT n.name IN $names
        RETURN n.ts_code AS tc, collect(n.name)[0] AS nm
        """,
        {"names": generic_list},
    ):
        if row.get("tc") and row.get("nm"):
            tc_to_name[row["tc"]] = row["nm"]
    logger.info("ts_code→公司名 映射: %d", len(tc_to_name))

    # 权威来源：PostgreSQL stocks 表
    stocks_map: dict[str, str] = {}
    try:
        import asyncio

        from sqlalchemy import text as _sql

        from app.core.database import engine as _engine

        async def _load_stocks() -> dict[str, str]:
            async with _engine.connect() as conn:
                rows = (await conn.execute(_sql("SELECT ts_code, name FROM stocks"))).fetchall()
            return {r[0]: r[1] for r in rows if r[0] and r[1]}

        stocks_map = asyncio.run(_load_stocks())
    except Exception as e:  # noqa: BLE001
        logger.warning("读取 stocks 表失败（将退化为 Neo4j 映射）: %s", e)
    logger.info("stocks ts_code→name: %d", len(stocks_map))

    moved = skipped_nomap = skipped_both = failed = 0
    ts_code_in_text = re.compile(r"(\d{6}\.(?:SZ|SH|BJ))")

    def _resolve_company(props: dict) -> tuple[str, str]:
        """返回 (标准公司名, ts_code)；解析不到返回 ("","")。"""
        ts_code = ""
        info = ev_map.get(str(props.get("evidence_id") or ""))
        if info:
            ts_code = info["ts_code"]
            company = (info.get("name") or "").strip()
            if company and not is_generic(company):
                return company, ts_code
        if not ts_code:
            m = ts_code_in_text.search(f"{props.get('source_name') or ''} {props.get('source_file') or ''}")
            if m:
                ts_code = m.group(1)
        if not ts_code:
            return "", ""
        company = (tc_to_name.get(ts_code) or stocks_map.get(ts_code) or "").strip()
        return company, ts_code

    for r in rels:
        props = r["props"] or {}
        company, ts_code = _resolve_company(props)
        if not company or is_generic(company):
            skipped_nomap += 1
            continue
        canon_eid = f"C:{ts_code}"
        a_gen, b_gen = bool(r["a_generic"]), bool(r["b_generic"])
        if a_gen and b_gen:
            skipped_both += 1
            continue
        valid_from = props.get("valid_from", "")
        new_props = {k: v for k, v in props.items() if k not in ("from_entity", "to_entity")}
        try:
            if args.dry_run:
                moved += 1
                continue
            upsert_entity(
                entity_id=canon_eid,
                entity_type="Company",
                name=company,
                ts_code=ts_code,
                source_type=props.get("source_type"),
                source_name=props.get("source_name"),
                confidence=0.9,
            )
            other_eid = r["beid"] if a_gen else r["aeid"]
            other_label = r["blabel"] if a_gen else r["alabel"]
            if a_gen:
                cypher = (
                    f"MATCH (x:Company {{entity_id: $canon}}) MATCH (y:{other_label} {{entity_id: $other}}) "
                    "MERGE (x)-[nr:RELATES {valid_from: $vf}]->(y) SET nr += $props"
                )
            else:
                cypher = (
                    f"MATCH (x:{other_label} {{entity_id: $other}}) MATCH (y:Company {{entity_id: $canon}}) "
                    "MERGE (x)-[nr:RELATES {valid_from: $vf}]->(y) SET nr += $props"
                )
            run(cypher, {"canon": canon_eid, "other": other_eid, "vf": valid_from, "props": new_props})
            run("MATCH ()-[r:RELATES]->() WHERE elementId(r) = $rid DELETE r", {"rid": r["rid"]})
            moved += 1
            if moved % 2000 == 0:
                logger.info("已处理 %d ...", moved)
        except Exception as e:  # noqa: BLE001
            failed += 1
            logger.warning("迁移失败 [%s]: %s", r["rid"], e)

    # 清理已无关系的泛称 Company 节点
    if not args.dry_run:
        run(
            "MATCH (n:Company) WHERE n.name IN $names AND NOT (n)-[:RELATES]-() DELETE n",
            {"names": generic_list},
        )
    logger.info(
        "完成: moved=%d skipped_no_company=%d skipped_both_generic=%d failed=%d dry_run=%s",
        moved, skipped_nomap, skipped_both, failed, args.dry_run,
    )
    print(f"RESULT moved={moved} skipped_no_company={skipped_nomap} skipped_both={skipped_both} failed={failed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
