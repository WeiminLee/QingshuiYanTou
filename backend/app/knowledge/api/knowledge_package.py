"""
知识包 API

GET /api/v1/knowledge/package/{ts_code}  — 完整知识包
GET /api/v1/knowledge/package/{ts_code}/summary  — 精简摘要
"""
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from app.knowledge.knowledge_package import build_knowledge_package
from app.core.database import async_session
from app.models.models import Stock
from sqlalchemy import select

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/package/{ts_code}")
async def get_knowledge_package(
    ts_code: str,
    include_content: bool = Query(False, description="是否返回实体完整 properties"),
):
    """
    获取个股完整知识包。

    返回结构：
    - ts_code / generated_at / data_freshness
    - entities（按类型分组）
    - relations（按类型统计）
    - signals（信号事件）
    - concept_scores（概念评分）
    - state_machine（状态跃迁）
    - contradiction_alerts（冲突警告）
    - confidence_summary（置信度汇总）
    """
    # 验证 ts_code 存在
    async with async_session() as db:
        stmt = select(Stock).where(Stock.ts_code == ts_code)
        result = await db.execute(stmt)
        stock = result.scalar_one_or_none()
        if not stock:
            raise HTTPException(status_code=404, detail=f"股票 {ts_code} 不存在")

    try:
        package = await build_knowledge_package(ts_code)
        if not include_content:
            # 精简模式：去掉冗长的 properties 内容
            for entity_list in package.get("entities", {}).values():
                if isinstance(entity_list, list):
                    for e in entity_list:
                        e.pop("properties", None)
        return package
    except Exception as e:
        logger.exception(f"知识包生成失败 [{ts_code}]: {e}")
        raise HTTPException(status_code=500, detail=f"知识包生成失败: {e}")


@router.get("/package/{ts_code}/summary")
async def get_knowledge_package_summary(ts_code: str):
    """
    获取个股知识包精简摘要。

    只返回核心指标，不含实体详情和关系列表。
    """
    async with async_session() as db:
        stmt = select(Stock).where(Stock.ts_code == ts_code)
        result = await db.execute(stmt)
        stock = result.scalar_one_or_none()
        if not stock:
            raise HTTPException(status_code=404, detail=f"股票 {ts_code} 不存在")

    try:
        full = await build_knowledge_package(ts_code)

        # 精简摘要
        return {
            "ts_code": ts_code,
            "name": stock.name,
            "generated_at": full["generated_at"],
            "summary": {
                "entity_count": full["entities"]["total"],
                "relation_count": full["relations"]["total"],
                "signal_count": full["signals"]["count"],
                "concept_count": full.get("concept_scores", {}).get("count", 0),
                "contradiction_count": len(full.get("contradiction_alerts", [])),
            },
            "entities_by_type": full["entities"]["by_type"],
            "relations_by_type": full["relations"]["by_type"],
            "signals_by_type": full["signals"]["by_type"],
            "top_concepts": [
                {"concept_name": c["concept_name"], "score": c.get("score")}
                for c in full.get("concept_scores", {}).get("top_concepts", [])[:5]
            ],
            "sentiment_score": full["signals"].get("sentiment_score", 0),
            "confidence_summary": full.get("confidence_summary", {}),
            "has_conflicts": len(full.get("contradiction_alerts", [])) > 0,
        }
    except Exception as e:
        logger.exception(f"知识包摘要生成失败 [{ts_code}]: {e}")
        raise HTTPException(status_code=500, detail=f"知识包摘要生成失败: {e}")
