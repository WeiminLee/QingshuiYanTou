"""
知识构建层 — 关系服务（Relation Service）

存储后端：Neo4j
- 关系类型 = relationship_type（结构化类型，见下）
- MERGE 依据：(from_entity, to_entity, relationship_type, valid_from)
- 时序字段作为关系属性

子模块：
  - knowledge.relation_types: 关系类型常量
  - knowledge.contradiction: 冲突检测

关系类型详见 relation_types.py
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta
from typing import Any, Optional

from app.core.neo4j_client import run, run_write, run_single, write_transaction
from app.knowledge.relation_types import RELATIONSHIP_TYPES, RELATIONSHIP_DESCRIPTIONS

logger = logging.getLogger(__name__)

RELATES_STATE_MERGE_PROMPT = """
检测到同一实体对新增了一条关系边，需要合并。

实体A：{from_entity}
实体B：{to_entity}

旧边信息：
- 关系描述：{old_text}
- 有效时间：{old_valid_from}
- 状态历史：{old_state_history}

新边信息：
- 关系描述：{new_text}
- 有效时间：{new_valid_from}

请生成合并后的关系：
1. TEXT: 覆盖完整时间线，描述状态变化全过程（不超过100字）
2. STATE_HISTORY: 状态历史列表，每个状态包含 valid_from, valid_to, text
3. 当前状态的 valid_to 必须为 null

输出格式：
TEXT: {{合并后的关系描述}}
STATE_HISTORY:
- {{valid_from}} ~ {{valid_to}}: {{状态描述}}
"""


# ── Cypher 注入防护 ────────────────────────────────────────────────────────

# 合法的关系类型字符（仅允许字母和下划线）
_REL_TYPE_PATTERN = re.compile(r"^[A-Z_]+$")


def _safe_rel_type(rel_type: str) -> str:
    """
    验证并返回安全的 Cypher 关系类型字符串。

    BUG-1 修复：防止 Cypher 注入攻击。
    Neo4j 关系类型标签必须匹配 [A-Za-z0-9_]+，且必须预定义。
    """
    if not rel_type or not isinstance(rel_type, str):
        raise ValueError(f"relationship_type 必须是字符串: {rel_type!r}")

    if rel_type not in RELATIONSHIP_TYPES:
        raise ValueError(
            f"无效 relationship_type: {rel_type}，"
            f"有效值: {sorted(RELATIONSHIP_TYPES)}"
        )

    # 验证格式（防止注入）
    if not _REL_TYPE_PATTERN.match(rel_type):
        raise ValueError(
            f"relationship_type 包含非法字符: {rel_type!r}，"
            f"仅允许 A-Z 和下划线"
        )

    return rel_type


# ── 对称关系类型（关系边无方向）─────────────────────────────────────

SYMMETRIC_TYPES = frozenset({"CONTRADICTS", "COMPETES_WITH", "SUBSTITUTES"})


# ── LLM 描述 → 结构化关系类型映射 ──────────────────────────────────────

_TYPE_KEYWORDS: dict[str, list[re.Pattern]] = {
    "BELONGS_TO": [
        re.compile(r"属于|隶属|归属|所在板块|所属板块"),
        re.compile(r"主营.*行业|行业为|业务领域"),
    ],
    "PRODUCES": [
        re.compile(r"生产|制造|量产|出货|供货产品"),
        re.compile(r"主营|主要产品|核心产品|主要从事"),
    ],
    "DIRECTLY_SUPPLIES_TO": [
        re.compile(r"直接供货|直接供应|已通过.*认证|认证.*供货"),
        re.compile(r"已.*供货|批量供货|稳定供货|开始供货"),
        re.compile(r"已向.*提供|已给.*供应"),
    ],
    "SUPPLIES_TO": [
        re.compile(r"供货|供应|是.*供应商|供应商"),
        re.compile(r"供应链|上游.*供应|供应.*芯片"),
    ],
    "USES": [
        re.compile(r"采用|使用|应用.*技术|搭载"),
        re.compile(r"使用.*技术路线|技术路线为"),
    ],
    "APPLIES_TO": [
        re.compile(r"应用于|应用场景|应用领域|适用"),
        re.compile(r"可用于|面向|针对.*市场"),
    ],
    "COMPETES_WITH": [
        re.compile(r"竞争|竞争对手|对标|替代"),
        re.compile(r"与.*竞争|取代|替代.*产品"),
    ],
    "STATE_TRANSITION": [
        re.compile(r"进入|从.*到|跃迁|升级"),
        re.compile(r"从.*阶段|阶段跃迁|状态转移"),
        re.compile(r"量产爬坡|产能释放|规模量产|中试|送样"),
    ],
    "DISCLOSES": [
        re.compile(r"披露|公告|说明|发布"),
        re.compile(r"在.*披露|公告称|表示"),
    ],
    "CATALYZES": [
        re.compile(r"催化|推动|加速|促进"),
        re.compile(r"带动|拉动|赋能"),
    ],
    "CONSTRAINS": [
        re.compile(r"受限于|取决于|瓶颈|约束"),
        re.compile(r"受限|产能.*不足|产能.*紧张"),
    ],
}


def infer_relation_type(description: str) -> str:
    """
    根据关系描述推断最可能的结构化关系类型。

    策略：匹配关键词模式，返回得分最高的关系类型。
    如无匹配，返回 SUPPLIES_TO（最通用的供应链关系）。

    Args:
        description: 自然语言关系描述

    Returns:
        结构化 relationship_type
    """
    if not description:
        return "SUPPLIES_TO"

    scores: dict[str, int] = {}
    for rel_type, patterns in _TYPE_KEYWORDS.items():
        score = 0
        for pat in patterns:
            if pat.search(description):
                score += 1
        if score > 0:
            scores[rel_type] = score

    if not scores:
        return "SUPPLIES_TO"

    return max(scores, key=lambda k: scores[k])


# ── 关系 → dict 互转 ──────────────────────────────────

def _rel_to_dict(rel: Any) -> dict:
    """将 Neo4j Relationship 对象转为 plain dict"""
    if rel is None:
        return {}
    d: dict = dict(rel)
    d["from_entity"] = rel.start_node.get("entity_id") if rel.start_node else None
    d["to_entity"] = rel.end_node.get("entity_id") if rel.end_node else None
    d["relationship_type"] = rel.type
    return d


# ── 关系服务 ──────────────────────────────────────────

def upsert_relation(
    from_entity: str,
    to_entity: str,
    relationship_type: str,
    properties: Optional[dict] = None,
    confidence: float = 0.80,
    source_type: Optional[str] = None,
    source_name: Optional[str] = None,
    evidence_url: Optional[str] = None,
    article_ref: Optional[str] = None,
    notes: Optional[str] = None,
    valid_from: Optional[date] = None,
    valid_to: Optional[date] = None,
    superseded_by: Optional[int] = None,
) -> tuple[dict, bool]:
    """
    Upsert 单条关系边。

    - 基于 (from_entity, to_entity, relationship_type, valid_from) 查重
    - 已存在：SET r += properties（合并），元数据首次写入不覆盖
    - 不存在：CREATE 关系

    Returns:
        (关系 dict, 是否为新插入)
    """
    # BUG-1 修复：使用 _safe_rel_type 验证并安全转义关系类型
    rel_type = _safe_rel_type(relationship_type)

    if valid_from is None:
        valid_from = date.today()

    now = datetime.now().isoformat()
    valid_from_str = str(valid_from)
    valid_to_str = str(valid_to) if valid_to else None

    # 查是否存在
    existing = run_single(
        f"""MATCH (a)-[r:`{rel_type}`]->(b)
           WHERE a.entity_id = $from_entity
             AND b.entity_id = $to_entity
             AND r.valid_from = $valid_from
           RETURN r, a.entity_id AS from_e, b.entity_id AS to_e
        """,
        {"from_entity": from_entity, "to_entity": to_entity, "valid_from": valid_from_str},
    )

    if existing:
        # 合并 properties
        merged: dict = dict(existing["r"])
        if properties:
            # descriptions[] 追加而非覆盖
            # 新格式 list[dict] → 按 text 去重（跨文件去重）
            # 旧格式 list[str]  → 兼容处理
            if "descriptions" in properties and properties["descriptions"]:
                incoming = properties["descriptions"]
                existing_descs = merged.get("descriptions", [])
                if isinstance(existing_descs, list) and existing_descs:
                    first_is_dict = isinstance(existing_descs[0], dict)
                    first_in_dict = isinstance(incoming[0], dict) if incoming else False
                    if first_in_dict:
                        # 新旧都是 dict 格式：按 text 去重
                        seen_texts = {
                            d.get("text", "") for d in existing_descs
                            if isinstance(d, dict)
                        }
                        for item in incoming:
                            if not isinstance(item, dict):
                                continue
                            txt = item.get("text", "").strip()
                            if txt and txt not in seen_texts:
                                # 追加（source 相同则覆盖，不重复追加）
                                existing_descs.append(item)
                                seen_texts.add(txt)
                        merged["descriptions"] = existing_descs
                    elif first_is_dict:
                        # 新来的是 list[str]，已有的是 dict：忽略新来的（不应该发生）
                        pass
                    else:
                        # 新旧都是 list[str]：直接追加去重
                        seen = set(existing_descs)
                        for d in incoming:
                            if d and d not in seen:
                                seen.add(d)
                                existing_descs.append(d)
                        merged["descriptions"] = existing_descs
                else:
                    # 现有为空或非 list：直接覆盖
                    merged["descriptions"] = incoming
            merged.update(properties)

        # 元数据首次写入不覆盖
        if not merged.get("source_type") and source_type:
            merged["source_type"] = source_type
        if not merged.get("source_name") and source_name:
            merged["source_name"] = source_name
        if not merged.get("evidence_url") and evidence_url:
            merged["evidence_url"] = evidence_url
        if not merged.get("article_ref") and article_ref:
            merged["article_ref"] = article_ref
        if not merged.get("notes") and notes:
            merged["notes"] = notes

        merged["confidence"] = max(float(merged.get("confidence") or 0), confidence)
        if valid_to_str and not merged.get("valid_to"):
            merged["valid_to"] = valid_to_str
        merged["updated_at"] = now

        run_write(
            f"""MATCH (a)-[r:`{rel_type}`]->(b)
               WHERE a.entity_id = $from_entity
                 AND b.entity_id = $to_entity
                 AND r.valid_from = $valid_from
               SET r += $props
            """,
            {
                "from_entity": from_entity,
                "to_entity": to_entity,
                "valid_from": valid_from_str,
                "props": merged,
            },
        )
        logger.debug("更新关系: %s -[%s]-> %s", from_entity, rel_type, to_entity)
        merged["from_entity"] = from_entity
        merged["to_entity"] = to_entity
        merged["relationship_type"] = rel_type
        return merged, False

    # 创建新关系前，先关闭同 pair 的旧关系（valid_to 未设置的视为当前有效）
    # BUG-9/10/11 修复：使用事务保证原子性，避免竞态条件
    yesterday = (valid_from - timedelta(days=1)).isoformat()
    props = {
        "confidence": confidence,
        "source_type": source_type,
        "source_name": source_name,
        "evidence_url": evidence_url,
        "article_ref": article_ref,
        "notes": notes,
        "valid_from": valid_from_str,
        "valid_to": valid_to_str,
        "superseded_by": superseded_by,
        "created_at": now,
        "updated_at": now,
    }
    if properties:
        props.update(properties)

    # 使用事务合并关闭旧关系和创建新关系（原子操作）
    with write_transaction() as tx:
        # 先关闭同 pair 的旧关系
        tx.run(
            f"""MATCH (a)-[r:`{rel_type}`]->(b)
               WHERE a.entity_id = $from_entity
                 AND b.entity_id = $to_entity
                 AND r.valid_to IS NULL
               SET r.valid_to = $yesterday, r.updated_at = $now
            """,
            {"from_entity": from_entity, "to_entity": to_entity, "yesterday": yesterday, "now": now},
        )
        # 创建新关系
        tx.run(
            f"""MATCH (a {{entity_id: $from_entity}}), (b {{entity_id: $to_entity}})
               CREATE (a)-[r:`{rel_type}` $props]->(b)
            """,
            {"from_entity": from_entity, "to_entity": to_entity, "props": props},
        )
    logger.debug("新增关系: %s -[%s]-> %s", from_entity, rel_type, to_entity)
    props["from_entity"] = from_entity
    props["to_entity"] = to_entity
    props["relationship_type"] = rel_type
    return props, True


def batch_upsert_relations(relations: list[dict]) -> tuple[int, int]:
    inserted = updated = 0
    for rel in relations:
        _, is_new = upsert_relation(**rel)
        if is_new:
            inserted += 1
        else:
            updated += 1
    logger.info("批量 upsert 关系完成: 新增=%d 更新=%d", inserted, updated)
    return inserted, updated


def _serialize_state_history(state_history: list[dict] | None) -> list[str]:
    """Neo4j relationship properties only support primitive arrays."""
    items: list[str] = []
    for item in state_history or []:
        if not isinstance(item, dict):
            continue
        items.append(
            f"{item.get('valid_from') or ''}~{item.get('valid_to') or ''}:"
            f"{item.get('text') or ''}"
        )
    return items


def _parse_state_history(items: Any) -> list[dict]:
    if not isinstance(items, list):
        return []
    parsed: list[dict] = []
    for raw in items:
        if isinstance(raw, dict):
            parsed.append(raw)
            continue
        text = str(raw)
        if ":" in text:
            period, desc = text.split(":", 1)
            if "~" in period:
                valid_from, valid_to = period.split("~", 1)
            else:
                valid_from, valid_to = period, ""
            parsed.append({
                "valid_from": valid_from or None,
                "valid_to": valid_to or None,
                "text": desc.strip(),
            })
    return parsed


def _default_state_history(text: str, valid_from: str, valid_to: str | None = None) -> list[dict]:
    return [{"valid_from": valid_from, "valid_to": valid_to, "text": text}]


def merge_relations(
    old_rel: dict,
    new_rel: dict,
    llm_client: Any | None = None,
) -> dict:
    """
    Merge RELATES state into text + state_history.

    If an LLM client is provided it may return the TEXT/STATE_HISTORY format from
    RELATES_STATE_MERGE_PROMPT; otherwise this deterministic merge preserves both
    state transitions and uses the new relation text as current state.
    """
    old_history = _parse_state_history(old_rel.get("state_history"))
    if not old_history:
        old_history = _default_state_history(
            old_rel.get("text", ""),
            str(old_rel.get("valid_from") or ""),
            old_rel.get("valid_to"),
        )

    new_state = {
        "valid_from": str(new_rel.get("valid_from") or date.today()),
        "valid_to": new_rel.get("valid_to"),
        "text": new_rel.get("text", ""),
    }

    if old_history:
        old_history[-1]["valid_to"] = old_history[-1].get("valid_to") or new_state["valid_from"]
    merged_history = [*old_history, new_state]
    merged = {
        "text": new_state["text"] or old_rel.get("text", ""),
        "state_history": merged_history,
    }

    if llm_client is None:
        return merged

    try:
        prompt = RELATES_STATE_MERGE_PROMPT.format(
            from_entity=old_rel.get("from_entity", ""),
            to_entity=old_rel.get("to_entity", ""),
            old_text=old_rel.get("text", ""),
            old_valid_from=old_rel.get("valid_from", ""),
            old_state_history=old_history,
            new_text=new_rel.get("text", ""),
            new_valid_from=new_rel.get("valid_from", ""),
        )
        if hasattr(llm_client, "chat"):
            response = llm_client.chat(prompt)
        elif callable(llm_client):
            response = llm_client(prompt)
        else:
            return merged
        parsed_text = ""
        parsed_history: list[dict] = []
        for line in str(response).splitlines():
            line = line.strip()
            if line.startswith("TEXT:"):
                parsed_text = line.split(":", 1)[1].strip()
            elif line.startswith("-") and ":" in line:
                period, desc = line[1:].split(":", 1)
                if "~" in period:
                    valid_from, valid_to = [p.strip() for p in period.split("~", 1)]
                else:
                    valid_from, valid_to = period.strip(), ""
                parsed_history.append({
                    "valid_from": valid_from or None,
                    "valid_to": None if valid_to in ("", "None", "null") else valid_to,
                    "text": desc.strip(),
                })
        if parsed_text:
            merged["text"] = parsed_text[:100]
        if parsed_history:
            merged["state_history"] = parsed_history
    except Exception as exc:  # noqa: BLE001
        logger.debug("RELATES LLM merge failed, using deterministic merge: %s", exc)
    return merged


def batch_upsert_relations_unwind(relations: list[dict]) -> dict:
    """
    UNWIND 单事务批量 upsert RELATES 关系（V1.2 Schema）。

    使用 UNWIND + MERGE 在单事务中完成全部写入，目标 1000 关系 < 5s。

    MERGE 依据：(from_entity, to_entity, valid_from)
    同一实体对同一 valid_from 只产生一条关系，多个来源文本追加到 descriptions[]。
    weight 取多个来源的最大值。

    Args:
        relations: list[dict]，每个 dict 支持 upsert_relates 的关键字参数，
                   至少包含 from_entity / to_entity / text

    Returns:
        {
            "inserted": int,
            "updated": int,
            "failed": int,
            "elapsed_seconds": float
        }
    """
    import time
    import datetime as dt

    start = time.monotonic()
    failed = 0

    # 过滤无效记录
    valid_relations = [
        r for r in relations
        if r.get("from_entity") and r.get("to_entity")
    ]

    if not valid_relations:
        elapsed = time.monotonic() - start
        return {
            "inserted": 0,
            "updated": 0,
            "failed": len(relations),
            "elapsed_seconds": elapsed,
        }

    now = datetime.now().isoformat()
    default_valid_from = date.today().isoformat()
    yesterday = (date.today() - dt.timedelta(days=1)).isoformat()

    rows = []
    for rel in valid_relations:
        valid_from_str = str(rel.get("valid_from") or default_valid_from)
        valid_to_str = str(rel.get("valid_to")) if rel.get("valid_to") else None
        source_file = rel.get("source_file", "unknown")
        direction = rel.get("direction", "neutral")
        description_entry = f"[{source_file}]{direction}: {rel.get('text', '')}"

        rows.append({
            "from_entity": rel["from_entity"],
            "to_entity": rel["to_entity"],
            "text": rel.get("text", ""),
            "weight": float(rel.get("weight", 1.0)),
            "direction": direction,
            "description_entry": description_entry,
            "descriptions": [description_entry],
            "source_type": rel.get("source_type", "unknown"),
            "source_name": rel.get("source_name", "unknown"),
            "source_chunk": rel.get("source_chunk", ""),
            "source_file": source_file,
            "valid_from": valid_from_str,
            "valid_to": valid_to_str,
            "now": now,
            "yesterday": yesterday,
        })

    # Stage 1: 关闭已有开放边
    close_cypher = """
    UNWIND $rows AS row
    MATCH (a {entity_id: row.from_entity})-[r:RELATES]->(b {entity_id: row.to_entity})
    WHERE r.valid_to IS NULL
      AND r.valid_from <> row.valid_from
    SET r.valid_to = row.yesterday, r.updated_at = row.now
    """

    # Stage 2: MERGE 新关系（追加 descriptions / 取 max weight）
    upsert_cypher = """
    UNWIND $rows AS row
    MERGE (a {entity_id: row.from_entity})
    MERGE (b {entity_id: row.to_entity})
    MERGE (a)-[r:RELATES {valid_from: row.valid_from}]->(b)
    ON CREATE SET
        r.text         = row.text,
        r.weight       = row.weight,
        r.direction    = row.direction,
        r.descriptions = row.descriptions,
        r.source_type   = row.source_type,
        r.source_name   = row.source_name,
        r.source_chunk  = row.source_chunk,
        r.source_file   = row.source_file,
        r.valid_to      = row.valid_to,
        r.created_at    = row.now,
        r.updated_at    = row.now
    ON MATCH SET
        r.updated_at = row.now,
        r.weight = CASE WHEN r.weight < row.weight THEN row.weight ELSE r.weight END,
        r.source_type = COALESCE(r.source_type, row.source_type),
        r.source_name = COALESCE(r.source_name, row.source_name)
    WITH r, row
    WHERE NOT row.description_entry IN r.descriptions
      SET r.descriptions = r.descriptions + row.descriptions
    RETURN count(r) AS total
    """

    try:
        with write_transaction() as tx:
            tx.run(close_cypher, {"rows": rows})
            result = tx.run(upsert_cypher, {"rows": rows})
            result.consume()

        elapsed = time.monotonic() - start
        total = len(valid_relations)
        logger.info("UNWIND batch_upsert_relations: total=%d elapsed=%.2fs", total, elapsed)
        return {
            "inserted": 0,
            "updated": total,
            "failed": 0,
            "elapsed_seconds": elapsed,
        }
    except Exception as e:
        logger.error("UNWIND batch_upsert_relations 失败: %s", e)
        elapsed = time.monotonic() - start
        return {
            "inserted": 0,
            "updated": 0,
            "failed": len(valid_relations),
            "elapsed_seconds": elapsed,
        }


def query_relations(
    from_entity: Optional[str] = None,
    to_entity: Optional[str] = None,
    relationship_type: Optional[str] = None,
    ts_code: Optional[str] = None,
    valid_at: Optional[date] = None,
    active_only: bool = True,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    """
    条件查询关系边。

    Args:
        from_entity: 起始节点 entity_id 前缀匹配
        to_entity: 目标节点 entity_id 前缀匹配
        relationship_type: 关系类型精确过滤
        ts_code: 任一端 entity_id 含此 ts_code
        valid_at: AS-OF 查询（valid_from <= valid_at <= valid_to）
        active_only: 默认 True，仅返回当前有效关系（valid_to 未设置）
                     设为 False 可查询所有历史关系
    """
    if relationship_type and relationship_type not in RELATIONSHIP_TYPES:
        raise ValueError(f"无效 relationship_type: {relationship_type}")

    where_parts: list[str] = []
    params: dict = {}

    if from_entity:
        where_parts.append("a.entity_id STARTS WITH $from_entity")
        params["from_entity"] = from_entity
    if to_entity:
        where_parts.append("b.entity_id STARTS WITH $to_entity")
        params["to_entity"] = to_entity
    if relationship_type:
        rel_label = f"`{relationship_type}`"
        where_parts.append("type(r) = $rel_type")
        params["rel_type"] = relationship_type
    else:
        rel_label = "r"

    if ts_code:
        where_parts.append(
            "(a.entity_id CONTAINS $ts_code OR b.entity_id CONTAINS $ts_code)"
        )
        params["ts_code"] = ts_code

    if valid_at:
        valid_at_str = str(valid_at)
        where_parts.append(
            "r.valid_from <= $valid_at "
            "AND (r.valid_to IS NULL OR r.valid_to >= $valid_at)"
        )
        params["valid_at"] = valid_at_str
    elif active_only:
        # 默认：仅返回当前有效关系
        where_parts.append("r.valid_to IS NULL")

    where_clause = "WHERE " + " AND ".join(where_parts) if where_parts else ""
    params["limit"] = limit
    params["offset"] = offset

    rows = run(
        f"MATCH (a)-[{rel_label}]->(b) {where_clause} "
        f"RETURN a.entity_id AS from_entity, b.entity_id AS to_entity, "
        f"type(r) AS relationship_type, r "
        f"ORDER BY r.valid_from DESC SKIP $offset LIMIT $limit",
        params,
    )
    results = []
    for row in rows:
        d: dict = dict(row["r"])
        d["from_entity"] = row["from_entity"]
        d["to_entity"] = row["to_entity"]
        d["relationship_type"] = row["relationship_type"]
        results.append(d)
    return results


def get_company_relations(
    ts_code: str,
    rel_type: Optional[str] = None,
    valid_at: Optional[date] = None,
) -> list[dict]:
    return query_relations(
        from_entity=f"C:{ts_code}",
        relationship_type=rel_type,
        valid_at=valid_at,
    )


def link_company_to_industry(
    ts_code: str,
    company_name: str,
    ths_code: str,
    industry_name: str,
    source_type: str,
    source_name: str,
    valid_from: Optional[date] = None,
    properties: Optional[dict] = None,
) -> tuple[dict, bool]:
    if valid_from is None:
        valid_from = date.today()
    return upsert_relation(
        from_entity=f"C:{ts_code}",
        to_entity=f"I:{ths_code}",
        relationship_type="BELONGS_TO",
        properties={
            "company_name": company_name,
            "industry_name": industry_name,
            **(properties or {}),
        },
        source_type=source_type,
        source_name=source_name,
        valid_from=valid_from,
    )


# ── 统一 RELATES 关系（2026-04-14 Schema 重构）───────────────────────────────

def upsert_relates(
    from_entity: str,
    to_entity: str,
    text: str,
    weight: float = 1.0,
    source_chunk: str | None = None,
    source_file: str | None = None,
    source_type: str = "unknown",
    source_name: str = "unknown",
    valid_from: date | None = None,
    valid_to: date | None = None,
    direction: str = "neutral",
) -> tuple[dict, bool]:
    return upsert_relates_v4(
        from_entity=from_entity,
        to_entity=to_entity,
        text=text,
        weight=weight,
        source_chunk=source_chunk,
        source_file=source_file,
        source_type=source_type,
        source_name=source_name,
        valid_from=valid_from,
        valid_to=valid_to,
        direction=direction,
    )


def upsert_relates_v4(
    from_entity: str,
    to_entity: str,
    text: str,
    weight: float = 1.0,
    source_chunk: str | None = None,
    source_file: str | None = None,
    source_type: str = "unknown",
    source_name: str = "unknown",
    valid_from: date | None = None,
    valid_to: date | None = None,
    direction: str = "neutral",
    llm_client: Any | None = None,
    evidence_id: str | None = None,
    evidence_ids: list[str] | None = None,
) -> tuple[dict, bool]:
    """
    Upsert 统一 RELATES 关系（Schema V4 核心函数）。

    Schema 变更：
    - 所有预定义关系类型废除 → 统一为 RELATES(text + weight)
    - weight = 1.0：chunk 中直接陈述，LLM 仅转述
    - weight < 0.5：LLM 推断，存在不确定性

    MERGE 依据：(from_entity, to_entity, valid_from)
    同一实体对同一 valid_from 只产生一条关系，多个来源文本追加到 descriptions[]。

    Args:
        from_entity: 起始节点 entity_id
        to_entity: 目标节点 entity_id
        text: 自然语言关系陈述
        weight: 置信度（1.0=直接陈述，<0.5=LLM推断）
        source_chunk: 来源 chunk 标识（如章节名）
        source_file: 来源文件名
        source_type: 来源类型（research_report / announcement 等）
        source_name: 来源名称
        valid_from: 关系生效日期（默认今天）
        valid_to: 关系失效日期（None=至今有效）
        direction: 方向（positive/negative/neutral），写入 text 补充说明

    Returns:
        (关系 dict, 是否新插入)
    """
    if valid_from is None:
        valid_from = date.today()

    now = datetime.now().isoformat()
    valid_from_str = str(valid_from)
    valid_to_str = str(valid_to) if valid_to else None

    # descriptions 格式：list[str]，每条 = "[{source}]{direction}: {text}"
    # Neo4j 不支持 list[dict]，只能存 primitive types
    source_label = source_file or "unknown"
    new_desc_str = f"[{source_label}]{direction}: {text}"

    # 查重：同一实体对 + 同一 valid_from
    existing = run_single(
        """MATCH (a)-[r:RELATES]->(b)
           WHERE a.entity_id = $from_entity
             AND b.entity_id = $to_entity
             AND r.valid_from = $valid_from
           RETURN r, a.entity_id AS from_e, b.entity_id AS to_e
        """,
        {"from_entity": from_entity, "to_entity": to_entity, "valid_from": valid_from_str},
    )

    if existing:
        merged: dict = dict(existing["r"])
        relation_merge = merge_relations(
            {
                **merged,
                "from_entity": from_entity,
                "to_entity": to_entity,
            },
            {
                "text": text,
                "valid_from": valid_from_str,
                "valid_to": valid_to_str,
            },
            llm_client=llm_client,
        )

        # descriptions[] 追加（按 text 去重）
        existing_descs: list = merged.get("descriptions", [])
        # 兼容旧 dict 格式 entries（迁移前遗留）
        if existing_descs and isinstance(existing_descs[0], dict):
            existing_descs = [d.get("text", "") if isinstance(d, dict) else str(d)
                             for d in existing_descs]
        seen_texts = set(existing_descs)
        if text not in seen_texts:
            existing_descs.append(new_desc_str)

        merged["descriptions"] = existing_descs
        merged["text"] = relation_merge["text"]
        merged["state_history"] = _serialize_state_history(relation_merge["state_history"])

        # weight 取多个来源的最大值（高置信优先）
        old_weight = float(merged.get("weight") or 0)
        merged["weight"] = max(old_weight, weight)

        # 元数据首次写入不覆盖
        for field, val in [("source_type", source_type), ("source_name", source_name),
                           ("source_chunk", source_chunk), ("source_file", source_file)]:
            if val and val != "unknown" and not merged.get(field):
                merged[field] = val
        if valid_to_str and not merged.get("valid_to"):
            merged["valid_to"] = valid_to_str
        if evidence_id and not merged.get("evidence_id"):
            merged["evidence_id"] = evidence_id
        if evidence_ids:
            existing_ids = merged.get("evidence_ids") or []
            if not isinstance(existing_ids, list):
                existing_ids = [existing_ids]
            seen = set(existing_ids)
            for eid in evidence_ids:
                if eid and eid not in seen:
                    existing_ids.append(eid)
                    seen.add(eid)
            merged["evidence_ids"] = existing_ids

        merged["updated_at"] = now

        run_write(
            """MATCH (a)-[r:RELATES]->(b)
               WHERE a.entity_id = $from_entity
                 AND b.entity_id = $to_entity
                 AND r.valid_from = $valid_from
               SET r += $props
            """,
            {
                "from_entity": from_entity,
                "to_entity": to_entity,
                "valid_from": valid_from_str,
                "props": merged,
            },
        )
        logger.debug("RELATES 更新: %s → %s (weight=%.1f)", from_entity, to_entity, weight)
        merged["from_entity"] = from_entity
        merged["to_entity"] = to_entity
        return merged, False

    # 创建新关系：先关闭同 pair 的旧有效关系
    # BUG-9/10/11 修复：使用事务保证原子性
    yesterday = (valid_from - timedelta(days=1)).isoformat()
    props = {
        "text": text,
        "weight": weight,
        "direction": direction,
        "descriptions": [new_desc_str],
        "source_type": source_type,
        "source_name": source_name,
        "source_chunk": source_chunk or "",
        "source_file": source_file or "",
        "valid_from": valid_from_str,
        "valid_to": valid_to_str,
        "evidence_id": evidence_id or "",
        "evidence_ids": list(dict.fromkeys(evidence_ids or [])),
        "state_history": _serialize_state_history(
            _default_state_history(text, valid_from_str, valid_to_str)
        ),
        "created_at": now,
        "updated_at": now,
    }

    # 使用事务合并关闭旧关系和创建新关系（原子操作）
    with write_transaction() as tx:
        tx.run(
            """MATCH (a)-[r:RELATES]->(b)
               WHERE a.entity_id = $from_entity
                 AND b.entity_id = $to_entity
                 AND r.valid_to IS NULL
               SET r.valid_to = $yesterday, r.updated_at = $now
            """,
            {
                "from_entity": from_entity,
                "to_entity": to_entity,
                "yesterday": yesterday,
                "now": now,
            },
        )
        tx.run(
            """MATCH (a {entity_id: $from_entity})
               MATCH (b {entity_id: $to_entity})
               CREATE (a)-[r:RELATES $props]->(b)
            """,
            {"from_entity": from_entity, "to_entity": to_entity, "props": props},
        )
    logger.debug("RELATES 新增: %s → %s (weight=%.1f, text=%.20s)", from_entity, to_entity, weight, text)
    props["from_entity"] = from_entity
    props["to_entity"] = to_entity
    return props, True
