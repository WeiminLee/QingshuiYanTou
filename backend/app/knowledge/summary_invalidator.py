"""
summary_invalidator.py — KG 抽取完成后触发摘要缓存失效

将失效逻辑从 kg_extractor（1500+ 行）中拆分为独立模块，
遵循单一职责原则。kg_extractor 只需调用 `trigger_invalidation()`。
"""

from __future__ import annotations

import logging
from typing import Any

from app.knowledge.summary_cache import invalidate_entities

logger = logging.getLogger(__name__)


async def collect_affected_entities(
    entity_ids: list[str],
    written_rels: list[dict[str, Any]],
) -> list[str]:
    """收集受本次 KG 抽取影响的所有实体 ID。

    包括：
    - 本次抽取创建/更新的实体
    - 关系两端的实体（即使本次未直接修改）
    """
    affected: list[str] = list(dict.fromkeys(entity_ids))

    for rel in written_rels:
        from_eid = rel.get("from", "")
        to_eid = rel.get("to", "")
        if from_eid and from_eid not in affected:
            affected.append(from_eid)
        if to_eid and to_eid not in affected:
            affected.append(to_eid)

    return affected


async def trigger_invalidation(
    entity_ids: list[str],
    written_rels: list[dict[str, Any]],
) -> None:
    """KG 抽取后的缓存失效入口。

    调用位置：`extract_text_async()` 末尾（约 L1155 附近）。

    设计决策：
    - 使用 try/except 包围，不阻塞 KG 抽取主流程
    - 失败仅记日志，不重试（下次查询时会触发按需生成）
    - 抽取独立模块避免 kg_extractor 进一步膨胀
    """
    if not entity_ids and not written_rels:
        return

    try:
        affected = await collect_affected_entities(entity_ids, written_rels)
        if affected:
            await invalidate_entities(affected)
            logger.info(
                "摘要缓存失效完成: %d 个实体 (来自 kg_extractor)",
                len(affected),
            )
    except Exception as exc:
        logger.warning(
            "摘要缓存失效失败（非致命，下次查询会按需生成）: %s",
            exc,
        )
