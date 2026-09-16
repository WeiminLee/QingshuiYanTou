"""UNWIND 批量 Neo4j 写入（kg/ingest 提速）。

与 entity_service.upsert_entity / relation_service.upsert_relates 语义对齐，
但用一次 UNWIND 查询写多行，把每 job ~35 次往返降到 ~4 次。

- 实体：按 entity_type 分组（Cypher 标签不能参数化），每组一次 UNWIND。
- 关系：先批量关闭旧有效关系，再批量 MERGE。
"""

from __future__ import annotations

import logging
from collections import defaultdict

from app.core.neo4j_client import run
from app.knowledge.entity_service import validate_entity_type

logger = logging.getLogger(__name__)

_graph_indexes_ensured = False


def ensure_graph_indexes() -> None:
    """确保实体 entity_id 索引存在（每进程一次）。

    无此索引时 MERGE/MATCH 会全标签扫描（实测 15 行关系 38s）；建索引后 ~1s。
    """
    global _graph_indexes_ensured
    if _graph_indexes_ensured:
        return
    _graph_indexes_ensured = True
    for label in ("Company", "Product", "Metric"):
        try:
            run(
                f"CREATE INDEX {label}_entity_id IF NOT EXISTS FOR (n:{label}) ON (n.entity_id)",
                {},
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("创建 %s.entity_id 索引失败: %s", label, e)


# 实体：ON CREATE 与单条版 upsert_entity 对齐
_ENTITY_BATCH_TMPL = """
UNWIND $rows AS row
MERGE (n:{label} {{entity_id: row.entity_id}})
ON CREATE SET
    n.name           = row.name,
    n.confidence     = row.confidence,
    n.source_type    = row.source_type,
    n.source_name    = row.source_name,
    n.evidence_url   = row.evidence_url,
    n.valid_from     = row.valid_from,
    n.valid_to       = row.valid_to,
    n.parser_version = row.parser_version,
    n.ts_code        = row.ts_code,
    n.aliases        = row.aliases,
    n.created_at     = row.created_at,
    n.updated_at     = row.updated_at,
    n.__new          = true
ON MATCH SET
    n.confidence = CASE WHEN coalesce(n.confidence, 0.0) < row.confidence THEN row.confidence ELSE n.confidence END,
    n.updated_at = row.updated_at,
    n.valid_to   = coalesce(n.valid_to, row.valid_to),
    n.source_type  = coalesce(n.source_type, row.source_type),
    n.source_name  = coalesce(n.source_name, row.source_name),
    n.evidence_url = coalesce(n.evidence_url, row.evidence_url)
WITH n, row, coalesce(n.__new, false) AS is_new
REMOVE n.__new
SET n += row.extra_props
RETURN sum(CASE WHEN is_new THEN 1 ELSE 0 END) AS created, count(n) AS total
"""


def upsert_entities_batch(rows: list[dict]) -> tuple[int, int]:
    """批量 upsert 实体。rows: 见 persist_evidence_extraction 构造。

    返回 (created, updated)。
    """
    if not rows:
        return 0, 0
    ensure_graph_indexes()
    by_type: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_type[str(r.get("entity_type") or "Company")].append(r)

    created = updated = 0
    for etype, items in by_type.items():
        validate_entity_type(etype)  # 白名单，防注入（标签用 f-string 拼接）
        try:
            res = run(_ENTITY_BATCH_TMPL.format(label=etype), {"rows": items})
        except Exception as e:  # noqa: BLE001
            logger.warning("实体批量入库失败 [%s n=%d]: %s", etype, len(items), e)
            continue
        if res:
            c = int(res[0].get("created") or 0)
            t = int(res[0].get("total") or 0)
            created += c
            updated += max(0, t - c)
    return created, updated


# 关系：先关闭同 pair 的旧有效关系（与单条版 valid_to=yesterday 对齐）
# 注意：MATCH 带标签才能命中 (label, entity_id) 索引；无标签会全图扫描（实测 15 行 38s）。
_REL_CLOSE_TMPL = """
UNWIND $rows AS row
MATCH (a:{from_label} {{entity_id: row.from_entity}})-[r:RELATES]->(b:{to_label} {{entity_id: row.to_entity}})
WHERE r.valid_to IS NULL AND r.valid_from <> row.valid_from
SET r.valid_to = row.yesterday, r.updated_at = row.now
"""

_REL_MERGE_TMPL = """
UNWIND $rows AS row
MATCH (a:{from_label} {{entity_id: row.from_entity}})
MATCH (b:{to_label} {{entity_id: row.to_entity}})
MERGE (a)-[r:RELATES {{valid_from: row.valid_from}}]->(b)
ON CREATE SET
    r.text            = row.text,
    r.weight          = row.weight,
    r.direction       = row.direction,
    r.descriptions    = [row.desc],
    r.source_type     = row.source_type,
    r.source_name     = row.source_name,
    r.source_chunk    = row.source_chunk,
    r.source_file     = row.source_file,
    r.valid_from      = row.valid_from,
    r.valid_to        = row.valid_to,
    r.evidence_id     = row.evidence_id,
    r.evidence_ids    = row.evidence_ids,
    r.stmt_type       = row.stmt_type,
    r.relation_subtype = row.relation_subtype,
    r.state_history   = row.state_history,
    r.created_at      = row.now,
    r.updated_at      = row.now,
    r.__new           = true
ON MATCH SET
    r.descriptions = CASE WHEN row.desc IN coalesce(r.descriptions, [])
                          THEN coalesce(r.descriptions, [])
                          ELSE coalesce(r.descriptions, []) + row.desc END,
    r.weight = CASE WHEN coalesce(r.weight, 0) < row.weight THEN row.weight ELSE r.weight END,
    r.updated_at = row.now,
    r.direction = CASE WHEN coalesce(r.direction, '') = '' THEN row.direction ELSE r.direction END,
    r.stmt_type = CASE WHEN row.stmt_rank > (CASE r.stmt_type WHEN 'Fact' THEN 3 WHEN 'Claim' THEN 2 ELSE 1 END)
                       THEN row.stmt_type ELSE r.stmt_type END,
    r.relation_subtype = CASE WHEN coalesce(r.relation_subtype, '') = '' THEN row.relation_subtype ELSE r.relation_subtype END,
    r.valid_to = coalesce(r.valid_to, row.valid_to),
    r.source_type = CASE WHEN coalesce(r.source_type, '') IN ['', 'unknown'] AND row.source_type <> 'unknown'
                         THEN row.source_type ELSE r.source_type END,
    r.source_name = CASE WHEN coalesce(r.source_name, '') IN ['', 'unknown'] AND row.source_name <> 'unknown'
                         THEN row.source_name ELSE r.source_name END
WITH r, coalesce(r.__new, false) AS is_new
REMOVE r.__new
RETURN sum(CASE WHEN is_new THEN 1 ELSE 0 END) AS created, count(r) AS total
"""


_LABEL_BY_PREFIX = [("CO:", "Company"), ("C:", "Company"), ("P:", "Product"), ("M:", "Metric")]


def _label_from_eid(eid: str) -> str | None:
    for pre, lab in _LABEL_BY_PREFIX:
        if eid.startswith(pre):
            return lab
    return None


def upsert_relates_batch(rows: list[dict]) -> tuple[int, int]:
    """批量 upsert RELATES 关系。返回 (created, updated)。

    按端点实体类型（由 entity_id 前缀推断）分组，使 MATCH 能命中标签索引。
    """
    if not rows:
        return 0, 0
    ensure_graph_indexes()
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in rows:
        fl = _label_from_eid(str(r.get("from_entity") or ""))
        tl = _label_from_eid(str(r.get("to_entity") or ""))
        if not fl or not tl:
            continue
        groups[(fl, tl)].append(r)

    created = updated = 0
    for (fl, tl), items in groups.items():
        try:
            run(_REL_CLOSE_TMPL.format(from_label=fl, to_label=tl), {"rows": items})
            res = run(_REL_MERGE_TMPL.format(from_label=fl, to_label=tl), {"rows": items})
        except Exception as e:  # noqa: BLE001
            logger.warning("关系批量入库失败 [%s->%s n=%d]: %s", fl, tl, len(items), e)
            continue
        if res:
            c = int(res[0].get("created") or 0)
            t = int(res[0].get("total") or 0)
            created += c
            updated += max(0, t - c)
    return created, updated
