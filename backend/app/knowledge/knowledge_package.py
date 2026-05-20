"""
知识包生成器

聚合 Neo4j 实体/关系/信号 + concept_scores + 情报摘要，
输出结构化 JSON，供推理决策层和前端使用。

API: GET /api/v1/knowledge/package/{ts_code}
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

from app.core.neo4j_client import run, run_write, run_single
from app.core.database import async_session
from app.models.models import Stock, ConceptScore

logger = logging.getLogger(__name__)

GRAPH_FIELD_SEP = "<SEP>"


# ── Neo4j 查询 ──────────────────────────────────────────────────────────────

def _get_neo4j_stats() -> dict:
    """获取 Neo4j 图谱统计"""
    result = run("""
        MATCH (n)
        RETURN n.entity_type AS entity_type, count(*) AS count
        UNION ALL
        MATCH ()-[r]->()
        RETURN 'relationships' AS entity_type, count(*) AS count
    """, {})
    stats = {}
    for row in result:
        stats[row["entity_type"]] = row["count"]
    return stats


def _get_company_entities(ts_code: str) -> list[dict]:
    """获取与某股票相关的所有实体"""
    result = run("""
        MATCH (n)
        WHERE n.entity_id CONTAINS $ts_code
           OR n.ts_code = $ts_code
           OR (n.properties IS NOT NULL AND n.properties.company_ts_code = $ts_code)
        RETURN n.entity_id AS entity_id,
               n.entity_type AS entity_type,
               n.name AS name,
               n.properties AS properties,
               n.confidence AS confidence
        LIMIT 200
    """, {"ts_code": ts_code})
    return list(result)


def _get_kg_relations(ts_code: str) -> list[dict]:
    """获取与某股票相关的所有关系（含 direction / confidence_tier / descriptions）"""
    result = run("""
        MATCH (a)-[r]->(b)
        WHERE a.entity_id CONTAINS $ts_code
           OR b.entity_id CONTAINS $ts_code
        RETURN a.entity_id AS from_entity,
               a.name AS from_name,
               b.entity_id AS to_entity,
               b.name AS to_name,
               type(r) AS relationship_type,
               r.properties AS properties,
               r.confidence AS confidence,
               r.direction AS direction,
               r.confidence_tier AS confidence_tier,
               r.descriptions AS descriptions,
               r.latest_description AS latest_description,
               r.valid_from AS valid_from,
               r.valid_to AS valid_to
        LIMIT 300
    """, {"ts_code": ts_code})
    return list(result)


def _get_signal_events(ts_code: str) -> list[dict]:
    """获取某股票的信号 Event 节点"""
    result = run("""
        MATCH (n:Event)
        WHERE n.entity_id CONTAINS $ts_code
          AND n.signal_type IS NOT NULL
        RETURN n.entity_id AS entity_id,
               n.name AS name,
               n.properties AS properties,
               n.confidence AS confidence,
               n.valid_from AS event_date
        ORDER BY n.valid_from DESC
        LIMIT 100
    """, {"ts_code": ts_code})
    return list(result)


def _get_state_transitions(ts_code: str) -> list[dict]:
    """获取某股票相关的状态跃迁关系"""
    result = run("""
        MATCH (a)-[r:STATE_TRANSITION]->(b)
        WHERE a.entity_id CONTAINS $ts_code
           OR b.entity_id CONTAINS $ts_code
        RETURN a.entity_id AS from_entity,
               a.name AS from_name,
               b.entity_id AS to_entity,
               b.name AS to_name,
               r.properties AS properties,
               r.valid_from AS valid_from
        ORDER BY r.valid_from DESC
        LIMIT 20
    """, {"ts_code": ts_code})
    return list(result)


def _get_contradiction_alerts(ts_code: str) -> list[dict]:
    """获取某股票相关的 CONTRADICTS 冲突"""
    result = run("""
        MATCH (a)-[r:CONTRADICTS]-(b)
        WHERE a.entity_id CONTAINS $ts_code
           OR b.entity_id CONTAINS $ts_code
        RETURN a.entity_id AS entity_a, a.name AS name_a,
               b.entity_id AS entity_b, b.name AS name_b,
               r.properties AS properties
        LIMIT 20
    """, {"ts_code": ts_code})
    return list(result)


def _get_company_state(ts_code: str) -> Optional[dict]:
    """获取公司节点的当前行业状态"""
    entity_id = f"C:{ts_code}"
    result = run_single(
        """
        MATCH (n)
        WHERE n.entity_id = $entity_id
        RETURN n.industry_state AS industry_state,
               n.state_description AS state_description,
               n.state_updated_at AS state_updated_at,
               n.state_source AS state_source
        """,
        {"entity_id": entity_id},
    )
    if not result:
        return None
    return {
        "industry_state": result.get("industry_state"),
        "state_description": result.get("state_description"),
        "state_updated_at": result.get("state_updated_at"),
        "state_source": result.get("state_source"),
    }


# ── concept_scores 查询 ─────────────────────────────────────────────────────

async def _get_concept_scores(ts_code: str) -> list[dict]:
    """获取某股票关联的概念评分"""
    async with async_session() as db:
        from sqlalchemy import select, text
        from app.models.models import ThsConceptMember, ConceptScore

        # 获取该股关联的概念代码
        stmt = (
            select(ConceptScore)
            .where(ConceptScore.ts_code == ts_code)
            .order_by(ConceptScore.score.desc())
            .limit(10)
        )
        result = await db.execute(stmt)
        rows = result.scalars().all()
        return [
            {
                "concept_name": r.concept_name,
                "concept_code": r.concept_code,
                "relative_strength": r.relative_strength,
                "breadth_score": r.breadth_score,
                "score": r.score,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            }
            for r in rows
        ]


# ── 置信度汇总 ───────────────────────────────────────────────────────────

# 5级置信度体系（与 kg_extractor.py SOURCE_CONFIG 一致）
_CONFIDENCE_TIER_MAP = {
    "TIER0_LEGAL":    {"level": 5, "name": "法律文件", "weight": 0.95},
    "TIER1_OFFICIAL": {"level": 4, "name": "官方披露", "weight": 0.82},
    "TIER2_ANALYSIS": {"level": 3, "name": "研究报告", "weight": 0.72},
    "TIER3_NEWS":     {"level": 2, "name": "新闻资讯", "weight": 0.55},
    "TIER4_MEDIA":    {"level": 1, "name": "自媒体", "weight": 0.38},
}


def _build_confidence_summary(
    entity_count: int,
    relation_count: int,
    signal_count: int,
    concept_score_count: int,
) -> dict:
    """构建置信度汇总（接入5级置信度体系）"""
    if entity_count == 0:
        return {"overall_level": "低", "overall_score": 0, "by_module": {}}

    modules = {
        "kg_entities": {
            "tier": "TIER2_ANALYSIS",
            "tier_name": "研究报告",
            "score": min(100, 60 + entity_count * 2),
            "description": f"实体 {entity_count} 个，来源多元",
        },
        "kg_relations": {
            "tier": "TIER2_ANALYSIS",
            "tier_name": "研究报告",
            "score": min(100, 50 + relation_count),
            "description": f"关系 {relation_count} 条，含结构化类型",
        },
        "signals": {
            "tier": "TIER2_ANALYSIS",
            "tier_name": "研究报告",
            "score": min(70, 40 + signal_count * 3),
            "description": f"信号 {signal_count} 个，规则+LLM提取",
        },
    }

    if concept_score_count > 0:
        modules["concept_scores"] = {
            "tier": "TIER0_LEGAL",
            "tier_name": "法律文件",
            "score": 100,
            "description": "Tushare + THS 官方数据",
        }

    avg_score = sum(m["score"] for m in modules.values()) / len(modules)

    if avg_score >= 80:
        level = "高"
    elif avg_score >= 60:
        level = "中"
    else:
        level = "低"

    return {
        "overall_level": level,
        "overall_score": round(avg_score),
        "by_module": modules,
    }


# ── 核心知识包 ───────────────────────────────────────────────────────────

def build_knowledge_package_sync(ts_code: str) -> dict:
    """
    同步入口：聚合 Neo4j + concept_scores，生成知识包。

    Returns:
        知识包 dict，结构见 api/knowledge_package.py
    """
    # Neo4j 数据
    entities = _get_company_entities(ts_code)
    relations = _get_kg_relations(ts_code)
    signal_events = _get_signal_events(ts_code)
    state_transitions = _get_state_transitions(ts_code)
    contradiction_alerts = _get_contradiction_alerts(ts_code)

    # 按类型分组实体
    by_type: dict[str, list[dict]] = {}
    for e in entities:
        t = e.get("entity_type", "Unknown")
        by_type.setdefault(t, []).append({
            "entity_id": e.get("entity_id"),
            "name": e.get("name"),
            "properties": e.get("properties") or {},
            "confidence": e.get("confidence"),
            "confidence_tier": (e.get("properties") or {}).get("confidence_tier"),
        })

    # 按类型统计关系
    rel_by_type: dict[str, int] = {}
    for r in relations:
        t = r.get("relationship_type", "Unknown")
        rel_by_type[t] = rel_by_type.get(t, 0) + 1

    # 活跃关系（valid_to IS NULL）
    active_relations = [
        {
            "from": r.get("from_entity"),
            "from_name": r.get("from_name"),
            "to": r.get("to_entity"),
            "to_name": r.get("to_name"),
            "type": r.get("relationship_type"),
            "direction": r.get("direction"),                    # positive/negative/neutral/conflict
            "confidence_tier": r.get("confidence_tier"),         # TIER0_LEGAL 等
            "description": (r.get("properties") or {}).get("relation_description", ""),
            "latest_description": r.get("latest_description") or "",  # 最新原文
            "descriptions": r.get("descriptions") or [],           # 多源原文数组
            "valid_from": r.get("valid_from"),
        }
        for r in relations
        if not r.get("valid_to")
    ]

    # 信号摘要
    sentiment_scores = [
        (e.get("properties") or {}).get("sentiment_score", 0)
        for e in signal_events
        if (e.get("properties") or {}).get("sentiment_score") is not None
    ]
    avg_sentiment = (
        sum(sentiment_scores) / len(sentiment_scores)
        if sentiment_scores else 0.0
    )

    # 信号按类型分组
    signals_by_type: dict[str, int] = {}
    for e in signal_events:
        t = (e.get("properties") or {}).get("signal_type", "unknown")
        signals_by_type[t] = signals_by_type.get(t, 0) + 1

    # 数据新鲜度（最近更新）
    kg_updated_at = None
    if entities:
        kg_updated_at = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    return {
        "ts_code": ts_code,
        "generated_at": datetime.now().isoformat(),
        "data_freshness": {
            "kg_updated_at": kg_updated_at,
            "signals_updated_at": kg_updated_at,
            "concept_scores_updated_at": kg_updated_at,
        },
        "entities": {
            "total": len(entities),
            "by_type": {k: len(v) for k, v in by_type.items()},
            "companies": by_type.get("Company", []),
            "products": by_type.get("Product", []),
            "events": by_type.get("Event", []),
            "industries": by_type.get("Industry", [])
                        + by_type.get("IND", []),
            "techs": by_type.get("Tech", []),
            "metrics": by_type.get("Metric", []),
            "capacities": by_type.get("Capacity", []),
        },
        "relations": {
            "total": len(relations),
            "by_type": rel_by_type,
            "active": active_relations,
        },
        "signals": {
            "count": len(signal_events),
            "by_type": signals_by_type,
            "recent": [
                {
                    "entity_id": e.get("entity_id"),
                    "type": (e.get("properties") or {}).get("signal_type"),
                    "content": (e.get("properties") or {}).get("signal_content", "")[:100],
                    "gap_type": (e.get("properties") or {}).get("gap_type"),
                    "sentiment_score": (e.get("properties") or {}).get("sentiment_score"),
                    "event_date": e.get("event_date"),
                }
                for e in signal_events[:20]
            ],
            "sentiment_score": round(avg_sentiment, 3),
        },
        "state_machine": {
            # 公司当前状态（来自 Company 节点 industry_state 属性）
            "company_current_state": _get_company_state(ts_code),
            "latest_transitions": [
                {
                    "from": r.get("from_entity"),
                    "from_name": r.get("from_name"),
                    "to": r.get("to_entity"),
                    "to_name": r.get("to_name"),
                    "direction": (r.get("properties") or {}).get("direction"),
                    "evidence": (r.get("properties") or {}).get("evidence", ""),
                    "confidence": (r.get("properties") or {}).get("confidence"),
                    "valid_from": r.get("valid_from"),
                }
                for r in state_transitions
            ],
        },
        "contradiction_alerts": [
            {
                "entity_a": r.get("entity_a"),
                "name_a": r.get("name_a"),
                "entity_b": r.get("entity_b"),
                "name_b": r.get("name_b"),
                "description": (r.get("properties") or {}).get("description", ""),
                "resolved": (r.get("properties") or {}).get("resolved", False),
            }
            for r in contradiction_alerts
        ],
    }


async def build_knowledge_package(ts_code: str) -> dict:
    """
    主入口：Neo4j（同步）+ concept_scores（异步）。
    """
    import asyncio
    # Neo4j 查询（在线程池中执行）
    loop = asyncio.get_running_loop()
    kg_data = await loop.run_in_executor(None, build_knowledge_package_sync, ts_code)

    # concept_scores（异步）
    try:
        concept_scores = await _get_concept_scores(ts_code)
        kg_data["concept_scores"] = {
            "top_concepts": concept_scores,
            "count": len(concept_scores),
        }
    except Exception as e:
        logger.warning("concept_scores 查询失败: %s", e)
        kg_data["concept_scores"] = {"top_concepts": [], "count": 0}

    # 置信度汇总
    kg_data["confidence_summary"] = _build_confidence_summary(
        entity_count=kg_data["entities"]["total"],
        relation_count=kg_data["relations"]["total"],
        signal_count=kg_data["signals"]["count"],
        concept_score_count=len(kg_data.get("concept_scores", {}).get("top_concepts", [])),
    )

    return kg_data
