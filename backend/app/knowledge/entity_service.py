# ── 节点类型常量 ────────────────────────────────────────
# V1.3 Schema: 3 类实体（Company / Product / Metric）
# 设计原则：克制扩展，最小 Schema，业务逻辑外置
# 其他类型（Category/Application/Technology/Project）归入属性，不作为独立实体
# 参考：docs/知识图谱设计.md - 四条铁律

from __future__ import annotations

import hashlib
import logging
import re
import unicodedata
from datetime import date, datetime
from typing import Any, Optional

from app.core.neo4j_client import run, run_write, run_single, write_transaction

logger = logging.getLogger(__name__)

# ── 节点类型常量 ────────────────────────────────────────
# V1.3 Schema: 3 类实体（克制扩展原则）

ENTITY_TYPES = frozenset({
    "Company", "Product", "Metric"
})

# ── entity_type 校验函数 ──────────────────────────────────────────────
# 安全修复：防止 Cypher 注入攻击，entity_type 必须在白名单内

def validate_entity_type(entity_type: str) -> str:
    """
    校验 entity_type 是否在白名单内，防止 Cypher 注入。

    Args:
        entity_type: 实体类型字符串

    Returns:
        校验通过的 entity_type

    Raises:
        ValueError: entity_type 不在白名单内
    """
    if entity_type not in ENTITY_TYPES:
        raise ValueError(f"无效 entity_type: {entity_type}，有效值: {ENTITY_TYPES}")
    return entity_type


def is_valid_entity_type(entity_type: str) -> bool:
    """检查 entity_type 是否有效（不抛异常）"""
    return entity_type in ENTITY_TYPES


# ── ID 生成 ──────────────────────────────────────────────

def _short_hash(text: str, length: int = 16) -> str:
    text = unicodedata.normalize("NFKC", text or "").strip()
    return hashlib.md5(text.encode("utf-8")).hexdigest()[:length]


def _safe_metric_name(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "").strip()
    value = re.sub(r"\s+", "_", value)
    return value.replace("/", "_").replace(":", "_")


def generate_entity_id(
    entity_type: str,
    name: str,
    ts_code: Optional[str] = None,
    metric_name: Optional[str] = None,
    period: Optional[str] = None,
) -> str:
    """
    唯一ID规则（V1.3 Schema - 3 类实体）：
      Company → C:{ts_code}（上市）/ CO:{md5(name)[:12]}（非上市）
      Product → P:{md5(name)[:16]}
      Metric  → M:{ts_code}:{metric_name}:{period}（无period则省略最后一段）

    其他类型（Category/Application/Technology/Project）不作为独立实体，
    应归入 Company/Product 节点的 properties 属性中。
    """
    if entity_type == "Company":
        if ts_code:
            return f"C:{ts_code}"
        # 非上市公司用名称哈希
        return f"CO:{_short_hash(name, length=12)}"
    if entity_type == "Product":
        return f"P:{_short_hash(name)}"
    if entity_type == "Metric":
        metric = metric_name or name
        if not metric:
            raise ValueError("Metric 类型必须提供 metric_name/name")
        safe_metric = _safe_metric_name(metric)
        if period:
            safe_period = _safe_metric_name(period)
            if ts_code:
                return f"M:{ts_code}:{safe_metric}:{safe_period}"
            # 无 ts_code 时用名称哈希作为标识符（回退机制）
            return f"M:{_short_hash(name, length=8)}:{safe_metric}:{safe_period}"
        if ts_code:
            return f"M:{ts_code}:{safe_metric}"
        # 无 ts_code 且无 period 时用名称哈希
        return f"M:{_short_hash(name, length=8)}:{safe_metric}"
    raise ValueError(f"未知 entity_type: {entity_type}，有效值: {ENTITY_TYPES}")


# ── 节点 → dict 互转 ──────────────────────────────────

def _node_to_dict(node: Any) -> dict:
    """将 Neo4j Node 对象转为 plain dict（含 entity_id）"""
    if node is None:
        return {}
    d: dict = dict(node)
    d["entity_id"] = node.get("entity_id")
    d["entity_type"] = list(node.labels)[0] if node.labels else None
    return d


# ── 实体服务 ─────────────────────────────────────────────

def upsert_entity(
    entity_id: str,
    entity_type: str,
    name: str = "",
    ts_code: Optional[str] = None,
    properties: Optional[dict] = None,
    confidence: float = 0.80,
    source_type: Optional[str] = None,
    source_name: Optional[str] = None,
    evidence_url: Optional[str] = None,
    valid_from: Optional[date] = None,
    valid_to: Optional[date] = None,
    parser_version: str = "v1.3",
) -> tuple[dict, bool]:
    """
    Upsert 单条实体节点（原子性 MERGE 模式 - 防止竞态条件）。

    安全修复：
    - 使用 MERGE + ON CREATE SET + ON MATCH SET 原子操作
    - entity_type 校验防止 Cypher 注入
    - 避免查改分离导致的重复节点问题

    Returns:
        (节点 dict, 是否为新插入)
    """
    # 安全校验：entity_type 必须在白名单内
    validate_entity_type(entity_type)

    if valid_from is None:
        valid_from = date.today()

    now = datetime.now().isoformat()
    valid_from_str = str(valid_from)
    valid_to_str = str(valid_to) if valid_to else None

    # 准备属性
    props = {
        "entity_id": entity_id,
        "name": name,
        "confidence": confidence,
        "source_type": source_type,
        "source_name": source_name,
        "evidence_url": evidence_url,
        "valid_from": valid_from_str,
        "valid_to": valid_to_str,
        "parser_version": parser_version,
        "created_at": now,
        "updated_at": now,
    }
    if ts_code:
        props["ts_code"] = ts_code
        # Company 节点：自动从 StockNameResolver 解析 aliases
        if entity_type == "Company":
            try:
                from app.knowledge.stock_name_resolver import get_stock_name_resolver
                all_names = get_stock_name_resolver().get_aliases(ts_code)
                aliases = [n for n in all_names if n and n != name]
                if aliases:
                    props["aliases"] = aliases
            except Exception as e:
                logger.warning("解析 Company aliases 失败 [%s]: %s", entity_id, e)

    # 合并额外 properties（但不覆盖核心字段）
    extra_props = dict(properties or {})

    # 原子性 MERGE Cypher（单事务）
    # 关键：使用 MERGE 确保 no race condition，ON CREATE/ON MATCH 处理两种情况
    cypher = f"""
    MERGE (n:{entity_type} {{entity_id: $entity_id}})
    ON CREATE SET
        n.name           = $name,
        n.confidence     = $confidence,
        n.source_type    = $source_type,
        n.source_name    = $source_name,
        n.evidence_url   = $evidence_url,
        n.valid_from     = $valid_from,
        n.valid_to       = $valid_to,
        n.parser_version = $parser_version,
        n.ts_code        = $ts_code,
        n.aliases        = $aliases,
        n.created_at     = $created_at,
        n.updated_at     = $updated_at
    ON MATCH SET
        n.name           = $name,
        n.confidence     = CASE WHEN n.confidence < $confidence THEN $confidence ELSE n.confidence END,
        n.updated_at     = $updated_at,
        n.valid_to       = COALESCE(n.valid_to, $valid_to)
    WITH n
    WHERE n.source_type IS NULL AND $source_type IS NOT NULL
      SET n.source_type = $source_type
    WITH n
    WHERE n.source_name IS NULL AND $source_name IS NOT NULL
      SET n.source_name = $source_name
    WITH n
    WHERE n.evidence_url IS NULL AND $evidence_url IS NOT NULL
      SET n.evidence_url = $evidence_url
    WITH n, $extra_props AS extra
    WHERE extra IS NOT NULL AND size(extra) > 0
      SET n += extra
    RETURN n, n.created_at = $created_at AS is_new
    """

    try:
        result = run_single(cypher, {
            "entity_id": entity_id,
            "name": name,
            "confidence": confidence,
            "source_type": source_type,
            "source_name": source_name,
            "evidence_url": evidence_url,
            "valid_from": valid_from_str,
            "valid_to": valid_to_str,
            "parser_version": parser_version,
            "ts_code": ts_code or "",
            "aliases": props.get("aliases", []),
            "created_at": now,
            "updated_at": now,
            "extra_props": extra_props,
        })

        if result:
            node = result["n"]
            is_new = bool(result.get("is_new", False))
            node_dict = dict(node)
            node_dict["entity_id"] = node.get("entity_id")
            node_dict["entity_type"] = entity_type
            if is_new:
                logger.debug("新增实体: %s", entity_id)
            else:
                logger.debug("更新实体: %s", entity_id)
            return node_dict, is_new
    except Exception as e:
        logger.warning("MERGE upsert 失败 [%s]: %s", entity_id, e)
        # 降级：回退到旧的非原子模式（作为兜底）
        return _upsert_entity_legacy(
            entity_id, entity_type, name, ts_code, properties,
            confidence, source_type, source_name, evidence_url,
            valid_from, valid_to, parser_version
        )

    # 兜底返回
    return props, True


def _upsert_entity_legacy(
    entity_id: str,
    entity_type: str,
    name: str = "",
    ts_code: Optional[str] = None,
    properties: Optional[dict] = None,
    confidence: float = 0.80,
    source_type: Optional[str] = None,
    source_name: Optional[str] = None,
    evidence_url: Optional[str] = None,
    valid_from: Optional[date] = None,
    valid_to: Optional[date] = None,
    parser_version: str = "v1.3",
) -> tuple[dict, bool]:
    """
    Legacy non-atomic upsert（仅作为 MERGE 失败时的降级方案）。
    注意：此函数存在竞态条件风险，仅用于兜底。
    """
    if valid_from is None:
        valid_from = date.today()

    now = datetime.now().isoformat()

    existing = run_single(
        "MATCH (n) WHERE n.entity_id = $entity_id RETURN n",
        {"entity_id": entity_id},
    )

    if existing:
        existing_node = existing["n"]
        merged = dict(existing_node)
        if properties:
            merged.update(properties)
        if not merged.get("source_type") and source_type:
            merged["source_type"] = source_type
        if not merged.get("source_name") and source_name:
            merged["source_name"] = source_name
        if not merged.get("evidence_url") and evidence_url:
            merged["evidence_url"] = evidence_url
        merged["confidence"] = max(float(merged.get("confidence") or 0), confidence)
        merged["updated_at"] = now

        run_write(
            f"MATCH (n) WHERE n.entity_id = $entity_id SET n += $props",
            {"entity_id": entity_id, "props": merged},
        )
        logger.debug("Legacy 更新实体: %s", entity_id)
        return merged, False

    # 创建新节点
    props = {
        "entity_id": entity_id,
        "name": name,
        "confidence": confidence,
        "source_type": source_type,
        "source_name": source_name,
        "evidence_url": evidence_url,
        "valid_from": str(valid_from) if valid_from else None,
        "valid_to": str(valid_to) if valid_to else None,
        "parser_version": parser_version,
        "created_at": now,
        "updated_at": now,
    }
    if ts_code:
        props["ts_code"] = ts_code
        if entity_type == "Company":
            try:
                from app.knowledge.stock_name_resolver import get_stock_name_resolver
                all_names = get_stock_name_resolver().get_aliases(ts_code)
                aliases = [n for n in all_names if n and n != name]
                if aliases:
                    props["aliases"] = aliases
            except Exception as e:
                logger.warning("解析 Company aliases 失败 [%s]: %s", entity_id, e)
    if properties:
        props.update(properties)

    run_write(
        f"CREATE (n:{entity_type} $props) RETURN n",
        {"props": props},
    )
    logger.debug("Legacy 新增实体: %s", entity_id)
    return props, True


def batch_upsert_entities(entities: list[dict]) -> tuple[int, int]:
    """
    批量 upsert，返回 (新增数, 更新数)。

    BUG-6 修复：委托给 batch_upsert_entities_unwind，避免 N+1 查询问题。
    内部使用 UNWIND + MERGE 单事务批量写入。
    """
    # 委托给高效的批量方法
    result = batch_upsert_entities_unwind(entities)
    logger.info("批量 upsert 完成: 新增=%d 更新=%d",
                result.get("inserted", 0), result.get("updated", 0))
    return result.get("inserted", 0), result.get("updated", 0)


def batch_upsert_entities_unwind(entities: list[dict]) -> dict:
    """
    UNWIND 单事务批量 upsert 实体节点（V1.3 Schema - 7类实体）。

    使用 UNWIND + MERGE 在单事务中完成全部写入，目标 1000 实体 < 5s。

    Args:
        entities: list[dict]，每个 dict 支持 upsert_entity 的全部关键字参数，
                 至少包含 entity_id / entity_type / name

    Returns:
        {
            "inserted": int,        # 新增节点数（估算）
            "updated": int,         # 更新节点数（估算）
            "failed": int,          # 失败数（entity_id 缺失）
            "elapsed_seconds": float
        }
    """
    import time
    start = time.monotonic()
    failed = 0

    # 过滤无效记录（entity_id/entity_type 缺失 + entity_type 不在白名单）
    # 安全修复：防止非法 entity_type 进入 Cypher
    valid_entities = [
        e for e in entities
        if e.get("entity_id") and e.get("entity_type") and is_valid_entity_type(e["entity_type"])
    ]
    invalid_type_count = len(entities) - len([e for e in entities if not e.get("entity_id") or not e.get("entity_type")]) - len(valid_entities)
    if invalid_type_count > 0:
        logger.warning("batch_upsert 过滤 %d 条非法 entity_type 记录", invalid_type_count)

    if not valid_entities:
        elapsed = time.monotonic() - start
        return {"inserted": 0, "updated": 0, "failed": len(entities), "elapsed_seconds": elapsed}

    now = datetime.now().isoformat()
    default_valid_from = date.today().isoformat()

    # 准备 UNWIND 数据
    rows = []
    for ent in valid_entities:
        props = {
            "entity_id": ent["entity_id"],
            "name": ent.get("name", ""),
            "entity_type": ent["entity_type"],
            "confidence": float(ent.get("confidence", 0.80)),
            "source_type": ent.get("source_type"),
            "source_name": ent.get("source_name"),
            "evidence_url": ent.get("evidence_url"),
            "valid_from": ent.get("valid_from") or default_valid_from,
            "valid_to": str(ent["valid_to"]) if ent.get("valid_to") else None,
            "parser_version": ent.get("parser_version", "v1.3"),
            "created_at": now,
            "updated_at": now,
        }
        # B6 fix: 先 update properties，再添加 ts_code（避免被覆盖）
        if ent.get("properties"):
            props.update(ent["properties"])
        if ent.get("ts_code"):
            props["ts_code"] = ent["ts_code"]
        # B16 fix: 提取 aliases 供 ON MATCH 使用
        aliases = props.get("aliases", [])
        if aliases:
            props["aliases"] = aliases

        rows.append(props)

    cypher = """
    UNWIND $rows AS row
    MERGE (n {entity_id: row.entity_id})
    ON CREATE SET
        n.entity_id      = row.entity_id,
        n.name           = row.name,
        n.confidence     = row.confidence,
        n.source_type    = row.source_type,
        n.source_name    = row.source_name,
        n.evidence_url   = row.evidence_url,
        n.valid_from    = row.valid_from,
        n.valid_to      = row.valid_to,
        n.parser_version = row.parser_version,
        n.created_at    = row.created_at,
        n.updated_at    = row.updated_at,
        n += row - {entity_id, name, entity_type, confidence, source_type,
                    source_name, evidence_url, valid_from, valid_to,
                    parser_version, created_at, updated_at}
    ON MATCH SET
        n.name        = row.name,
        n.confidence  = row.confidence,
        n.updated_at  = row.updated_at,
        n.valid_to    = COALESCE(n.valid_to, row.valid_to),
        n.aliases     = COALESCE(n.aliases, row.aliases)
    WITH n, row
    WHERE n.source_type IS NULL AND row.source_type IS NOT NULL
      SET n.source_type = row.source_type
    WITH n, row
    WHERE n.source_name IS NULL AND row.source_name IS NOT NULL
      SET n.source_name = row.source_name
    WITH n, row
    WHERE n.evidence_url IS NULL AND row.evidence_url IS NOT NULL
      SET n.evidence_url = row.evidence_url
    RETURN count(n) AS total
    """

    try:
        with write_transaction() as tx:
            result = tx.run(cypher, {"rows": rows})
            result.consume()
        elapsed = time.monotonic() - start
        total = len(valid_entities)
        logger.info("UNWIND batch_upsert_entities: total=%d elapsed=%.2fs", total, elapsed)
        return {
            "inserted": 0,  # UNWIND 无法精确区分 inserted/updated
            "updated": total,
            "failed": 0,
            "elapsed_seconds": elapsed,
        }
    except Exception as e:
        logger.error("UNWIND batch_upsert_entities 失败: %s", e)
        elapsed = time.monotonic() - start
        return {
            "inserted": 0,
            "updated": 0,
            "failed": len(valid_entities),
            "elapsed_seconds": elapsed,
        }



def get_entity(entity_id: str) -> Optional[dict]:
    """根据 entity_id 查询单条实体"""
    result = run_single(
        "MATCH (n) WHERE n.entity_id = $entity_id RETURN n",
        {"entity_id": entity_id},
    )
    if result:
        return _node_to_dict(result["n"])
    return None


def query_entities(
    entity_type: Optional[str] = None,
    ts_code: Optional[str] = None,
    name_keyword: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    """条件查询实体"""
    if entity_type and entity_type not in ENTITY_TYPES:
        raise ValueError(f"无效 entity_type: {entity_type}，有效值: {ENTITY_TYPES}")

    labels = f":{entity_type}" if entity_type else ""
    where_parts = []
    params: dict = {}

    if ts_code:
        where_parts.append("n.ts_code = $ts_code")
        params["ts_code"] = ts_code
    if name_keyword:
        where_parts.append("n.name CONTAINS $name_keyword")
        params["name_keyword"] = name_keyword

    where_clause = "WHERE " + " AND ".join(where_parts) if where_parts else ""
    params["limit"] = limit
    params["offset"] = offset

    rows = run(
        f"MATCH (n{labels}) {where_clause} RETURN n ORDER BY n.entity_id "
        f"SKIP $offset LIMIT $limit",
        params,
    )
    return [_node_to_dict(r["n"]) for r in rows]


def get_company_by_ts_code(ts_code: str) -> Optional[dict]:
    return get_entity(f"C:{ts_code}")


def upsert_company(
    ts_code: str,
    name: str,
    source_type: str,
    source_name: str,
    properties: Optional[dict] = None,
    evidence_url: Optional[str] = None,
) -> tuple[dict, bool]:
    entity_id = f"C:{ts_code}"
    return upsert_entity(
        entity_id=entity_id,
        entity_type="Company",
        name=name,
        ts_code=ts_code,
        properties=properties,
        source_type=source_type,
        source_name=source_name,
        evidence_url=evidence_url,
    )
