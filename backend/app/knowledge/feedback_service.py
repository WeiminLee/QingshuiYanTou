"""
知识构建层 — 分析师反馈服务

处理 confirm / reject / correct 三类纠错，
更新 Neo4j RELATES 关系 weight，持久化到 MongoDB feedback collection。
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, date, datetime

from app.core.mongodb import get_mongo_db
from app.core.neo4j_client import run_single, run_write

logger = logging.getLogger(__name__)

# ── 常量 ──────────────────────────────────────────────
DECAY_FLOOR = 0.50  # weight 下限（高置信关系保护）
HIGH_CONFIDENCE_THRESHOLD = 0.85  # 当前 weight 达到此值时启用 floor 保护

# 纠错类型
CORRECTION_TYPES = frozenset({"confirm", "reject", "correct"})

# ── relation_id 解析 ──────────────────────────────────


def parse_relation_id(rel_id: str) -> dict:
    """
    解析 relation_id，返回 (from_entity, to_entity, valid_from_str).

    Format: R:{from_entity}|{to_entity}|{valid_from}
    Example: "R:C:600519.SH|P:chip_A|2026-04-21"

    If the rel_id has fewer than 3 pipe segments, valid_from defaults to today.

    BUG-11 修复：添加 entity_id 格式验证，防止注入攻击。
    合法的 entity_id 前缀：C: / P: / M: / E: / CO: / IND: / I:
    """
    import re

    # 实体ID格式验证正则
    ENTITY_ID_PATTERN = re.compile(r"^(C:|P:|M:|E:|CO:|IND:|I:)[A-Za-z0-9_.:/-]+$")

    if not rel_id or not isinstance(rel_id, str):
        raise ValueError(f"relation_id must be a non-empty string, got: {rel_id!r}")

    if not rel_id.startswith("R:"):
        raise ValueError(f"relation_id must start with 'R:', got: {rel_id}")

    inner = rel_id[2:]  # strip "R:"
    if not inner:
        raise ValueError(f"relation_id missing content after 'R:': {rel_id}")

    parts = inner.split("|")
    from_entity = parts[0]
    to_entity = parts[1] if len(parts) > 1 else ""
    valid_from = parts[2] if len(parts) > 2 else str(date.today())

    if not from_entity or not to_entity:
        raise ValueError(f"relation_id must have from_entity and to_entity: {rel_id}")

    # 验证 entity_id 格式
    for entity_id in (from_entity, to_entity):
        if not ENTITY_ID_PATTERN.match(entity_id):
            raise ValueError(
                f"Invalid entity_id format: {entity_id!r}. "
                f"Expected prefix C:/P:/M:/E:/CO:/IND:/I: followed by alphanumeric chars."
            )

    return {"from_entity": from_entity, "to_entity": to_entity, "valid_from": valid_from}


def _apply_feedback_sync(
    from_entity: str,
    to_entity: str,
    valid_from: str,
    correction_type: str,
    corrected_weight: float,
) -> dict:
    """
    同步函数：查找 RELATES 边，更新 weight，返回 (previous_weight, corrected_weight)。
    必须在 to_thread 中调用。
    """
    # 查找当前 weight
    row = run_single(
        """MATCH (a {entity_id: $from_entity})-[r:RELATES]->(b {entity_id: $to_entity})
           WHERE r.valid_from = $valid_from
           RETURN r.weight AS weight
        """,
        {"from_entity": from_entity, "to_entity": to_entity, "valid_from": valid_from},
    )
    previous_weight = float(row["weight"]) if row and row.get("weight") is not None else None

    if previous_weight is None:
        raise ValueError(
            f"RELATES edge not found: from_entity={from_entity}, to_entity={to_entity}, valid_from={valid_from}"
        )

    # DECAY floor 保护（仅 correct 类型有意义；confirm/reject 通过 Cypher 原子更新）
    if correction_type == "correct" and previous_weight >= HIGH_CONFIDENCE_THRESHOLD and corrected_weight < DECAY_FLOOR:
        corrected_weight = DECAY_FLOOR
        logger.debug(
            "DECAY_FLOOR 保护触发: previous_weight=%.2f, 限制 corrected_weight=%.2f",
            previous_weight,
            corrected_weight,
        )

    # 更新 weight
    now = datetime.now(UTC).isoformat()
    run_write(
        """MATCH (a {entity_id: $from_entity})-[r:RELATES]->(b {entity_id: $to_entity})
           WHERE r.valid_from = $valid_from
           SET r.weight = $weight, r.updated_at = $now
        """,
        {
            "from_entity": from_entity,
            "to_entity": to_entity,
            "valid_from": valid_from,
            "weight": corrected_weight,
            "now": now,
        },
    )
    return {"previous_weight": previous_weight, "corrected_weight": corrected_weight}


def _apply_delta_atomic(
    from_entity: str,
    to_entity: str,
    valid_from: str,
    delta: float,
) -> dict:
    """
    同步函数：原子地读取当前 weight，施加 delta，写入新值。
    confirm (+0.05上限1.0) 和 reject (-0.15下限0.0) 使用此函数，
    保证 read-compute-write 在单次事务内完成，消除并发竞态。
    """
    row = run_single(
        """MATCH (a {entity_id: $from_entity})-[r:RELATES]->(b {entity_id: $to_entity})
           WHERE r.valid_from = $valid_from
           RETURN r.weight AS weight
        """,
        {"from_entity": from_entity, "to_entity": to_entity, "valid_from": valid_from},
    )
    previous_weight = float(row["weight"]) if row and row.get("weight") is not None else None

    if previous_weight is None:
        raise ValueError(
            f"RELATES edge not found: from_entity={from_entity}, to_entity={to_entity}, valid_from={valid_from}"
        )

    corrected_weight = float(previous_weight + delta)
    # confirm 上限 1.0，reject 下限 0.0
    corrected_weight = max(0.0, min(1.0, corrected_weight))

    now = datetime.now(UTC).isoformat()
    run_write(
        """MATCH (a {entity_id: $from_entity})-[r:RELATES]->(b {entity_id: $to_entity})
           WHERE r.valid_from = $valid_from
           SET r.weight = $weight, r.updated_at = $now
        """,
        {
            "from_entity": from_entity,
            "to_entity": to_entity,
            "valid_from": valid_from,
            "weight": corrected_weight,
            "now": now,
        },
    )
    return {"previous_weight": previous_weight, "corrected_weight": corrected_weight}


async def apply_feedback(
    rel_id: str,
    correction_type: str,
    corrected_weight: float | None = None,
    user_id: str | None = None,
) -> dict:
    """
    处理分析师反馈，更新 Neo4j weight 并写入 MongoDB feedback collection。

    Args:
        rel_id:          关系标识，格式 "R:{from_entity}|{to_entity}|{valid_from}"
        correction_type: "confirm" | "reject" | "correct"
        corrected_weight: 仅 correct 类型需要提供
        user_id:          分析师标识（可空）

    Returns:
        {
            "relation_id": str,
            "previous_weight": float,
            "corrected_weight": float,
            "feedback_id": str,   # MongoDB document _id
        }

    Raises:
        ValueError: 纠错类型无效、correct 无 weight、边不存在
    """
    if correction_type not in CORRECTION_TYPES:
        raise ValueError(f"无效 correction_type={correction_type}，有效值: {sorted(CORRECTION_TYPES)}")
    if correction_type == "correct" and corrected_weight is None:
        raise ValueError("correction_type='correct' 时必须提供 corrected_weight")

    parsed = parse_relation_id(rel_id)
    from_entity = parsed["from_entity"]
    to_entity = parsed["to_entity"]
    valid_from = parsed["valid_from"]

    # confirm / reject：原子 Cypher 更新（消除并发竞态）
    # correct：两步 read-then-write（显式赋值，无并发风险）
    if correction_type in ("confirm", "reject"):
        delta = 0.05 if correction_type == "confirm" else -0.15
        result = await asyncio.to_thread(
            _apply_delta_atomic,
            from_entity,
            to_entity,
            valid_from,
            delta,
        )
        previous_weight = result["previous_weight"]
        final_weight = result["corrected_weight"]
    else:
        result = await asyncio.to_thread(
            _apply_feedback_sync,
            from_entity,
            to_entity,
            valid_from,
            correction_type,
            float(corrected_weight),
        )
        previous_weight = result["previous_weight"]
        final_weight = result["corrected_weight"]

    # 写入 MongoDB feedback collection
    feedback_id = str(uuid.uuid4())
    doc = {
        "_id": feedback_id,
        "relation_id": rel_id,
        "correction_type": correction_type,
        "previous_weight": previous_weight,
        "corrected_weight": final_weight,
        "user_id": user_id or "anonymous",
        "timestamp": datetime.now(UTC),
    }
    db = await get_mongo_db()
    await db.feedback.insert_one(doc)
    logger.info(
        "Feedback recorded: rel_id=%s type=%s prev=%.2f new=%.2f user=%s",
        rel_id,
        correction_type,
        previous_weight,
        final_weight,
        user_id,
    )

    return {
        "relation_id": rel_id,
        "previous_weight": previous_weight,
        "corrected_weight": final_weight,
        "feedback_id": feedback_id,
    }
