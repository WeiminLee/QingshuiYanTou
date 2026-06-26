"""
ConceptService - 概念板块查询服务

从本地 PostgreSQL 查询概念板块热度数据，供 Agent 工具调用。
"""

import logging
from typing import Any

from sqlalchemy import desc, select

from app.core.database import engine
from app.models.models import ConceptLimit, ThsConcept

logger = logging.getLogger(__name__)


class ConceptService:
    """概念板块查询服务"""

    async def get_concept_ranking(
        self,
        top_n: int = 20,
        sort_by: str = "change_pct",
        days: int = 1,
    ) -> list[dict[str, Any]]:
        """
        从 PostgreSQL 查询概念板块热度排名

        Args:
            top_n: 返回数量
            sort_by: 排序方式 change_pct/turnover/limit_up
            days: 统计最近 N 个交易日

        Returns:
            概念板块列表
        """
        date_stmt = select(ConceptLimit.trade_date).distinct().order_by(desc(ConceptLimit.trade_date)).limit(days)

        try:
            async with engine.connect() as conn:
                date_result = await conn.execute(date_stmt)
                trade_dates = [row[0] for row in date_result.fetchall()]
        except Exception as e:
            logger.warning(f"查询交易日失败: {e}")
            return []

        if not trade_dates:
            logger.warning("无概念交易日数据")
            return []

        data_stmt = select(
            ConceptLimit.concept_code,
            ConceptLimit.concept_name,
            ConceptLimit.trade_date,
            ConceptLimit.up_nums,
            ConceptLimit.pct_chg,
        ).where(ConceptLimit.trade_date.in_(trade_dates))

        try:
            async with engine.connect() as conn:
                result = await conn.execute(data_stmt)
                rows = result.fetchall()
        except Exception as e:
            logger.warning(f"查询概念数据失败: {e}")
            return []

        date_weight = {d: 1.0 / (2**idx) for idx, d in enumerate(trade_dates)}

        concept_scores: dict[str, dict] = {}
        for row in rows:
            concept_code = row[0]
            concept_name = row[1]
            trade_date = row[2]
            up_nums = row[3] or 0
            pct_chg = row[4] or 0

            weight = date_weight.get(trade_date, 1.0)
            up_bonus = 20 if up_nums >= 10 else (10 if up_nums >= 5 else 0)

            entry = concept_scores.setdefault(
                concept_code,
                {
                    "name": concept_name,
                    "total_score": 0.0,
                    "last_pct_chg": 0.0,
                    "last_up_nums": 0,
                    "days_count": 0,
                },
            )
            entry["total_score"] += (pct_chg + up_bonus) * weight
            entry["last_pct_chg"] = pct_chg
            entry["last_up_nums"] = up_nums
            entry["days_count"] += 1

        if sort_by == "limit_up":
            sorted_concepts = sorted(
                concept_scores.items(),
                key=lambda x: x[1]["last_up_nums"],
                reverse=True,
            )
        else:
            sorted_concepts = sorted(
                concept_scores.items(),
                key=lambda x: x[1]["total_score"],
                reverse=True,
            )

        return [
            {
                "rank": idx + 1,
                "concept_code": code,
                "name": data["name"],
                "pct_chg": round(data["last_pct_chg"], 2),
                "up_nums": data["last_up_nums"],
                "score": round(data["total_score"], 4),
            }
            for idx, (code, data) in enumerate(sorted_concepts[:top_n])
        ]

    async def get_concept_by_code(self, concept_code: str) -> dict[str, Any] | None:
        """
        查询单个概念详情

        Args:
            concept_code: 概念代码（如 885806.TI）

        Returns:
            概念详情
        """
        stmt = select(
            ThsConcept.ts_code,
            ThsConcept.name,
            ThsConcept.count,
            ThsConcept.exchange,
        ).where(ThsConcept.ts_code == concept_code)

        try:
            async with engine.connect() as conn:
                result = await conn.execute(stmt)
                row = result.fetchone()
        except Exception as e:
            logger.warning(f"查询概念 {concept_code} 失败: {e}")
            return None

        if not row:
            return None

        return {
            "concept_code": row[0],
            "name": row[1],
            "count": row[2],
            "exchange": row[3],
        }

    async def get_concept_history(
        self,
        concept_code: str,
        days: int = 10,
    ) -> list[dict[str, Any]]:
        """
        查询概念历史数据

        Args:
            concept_code: 概念代码
            days: 历史天数

        Returns:
            历史数据列表
        """
        stmt = (
            select(
                ConceptLimit.trade_date,
                ConceptLimit.concept_code,
                ConceptLimit.concept_name,
                ConceptLimit.pct_chg,
                ConceptLimit.up_nums,
                ConceptLimit.days,
                ConceptLimit.rank,
            )
            .where(ConceptLimit.concept_code == concept_code)
            .order_by(desc(ConceptLimit.trade_date))
            .limit(days)
        )

        try:
            async with engine.connect() as conn:
                result = await conn.execute(stmt)
                rows = result.fetchall()
        except Exception as e:
            logger.warning(f"查询概念历史 {concept_code} 失败: {e}")
            return []

        return [
            {
                "trade_date": row[0].strftime("%Y%m%d") if row[0] else "",
                "concept_code": row[1],
                "concept_name": row[2],
                "pct_chg": row[3],
                "up_nums": row[4],
                "days": row[5],
                "rank": row[6],
            }
            for row in rows
        ]


_concept_service: ConceptService | None = None


def get_concept_service() -> ConceptService:
    """获取 ConceptService 单例"""
    global _concept_service
    if _concept_service is None:
        _concept_service = ConceptService()
    return _concept_service
