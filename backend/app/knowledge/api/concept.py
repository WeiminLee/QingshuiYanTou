"""
概念分析 API

核心功能：
- 每日涨停概念 TOP10 排名（从本地 concept_limit 表读取历史数据计算）
- 概念详情查询（成分股 + 资金面排序）
- 统一使用 THS TI 格式（与 limit_cpt_list 体系一致）
"""

import logging

from fastapi import HTTPException
from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import (
    ConceptLimit,
    DailyBasic,
    DailyData,
    Stock,
    ThsConcept,
    ThsConceptMember,
)

logger = logging.getLogger(__name__)


async def get_top_concepts(
    db: AsyncSession,
    days: int = 5,
    top_n: int = 10,
):
    """
    获取最近N个交易日最强概念 TOP N

    算法（从本地 concept_limit 表读取）：
    1. 获取最近 N 个有数据的交易日
    2. 指数衰减权重：当天=1.0，前1天=0.5，前2天=0.25...
    3. 每日得分 = pct_chg × 权重 + 涨停数加成（up_nums>=5 → +10，>=10 → +20）
    4. 累加 N 天得分，取 TOP N
    """
    # 获取最近 N 个有数据的交易日
    trade_dates_stmt = select(ConceptLimit.trade_date).distinct().order_by(desc(ConceptLimit.trade_date)).limit(days)
    result = await db.execute(trade_dates_stmt)
    trade_dates = [row[0] for row in result.fetchall()]

    if len(trade_dates) < 2:
        raise HTTPException(
            status_code=400,
            detail=f"本地数据不足（仅{len(trade_dates)}个交易日），请先运行同步脚本采集数据",
        )

    # 读取所有相关数据
    data_stmt = select(ConceptLimit).where(ConceptLimit.trade_date.in_(trade_dates))
    result = await db.execute(data_stmt)
    rows = result.scalars().all()

    # 按概念聚合
    concept_scores: dict[str, dict] = {}
    for row in rows:
        idx = trade_dates.index(row.trade_date)
        weight = 1.0 / (2**idx)
        up_bonus = 20 if (row.up_nums or 0) >= 10 else (10 if (row.up_nums or 0) >= 5 else 0)

        if row.concept_code not in concept_scores:
            concept_scores[row.concept_code] = {
                "name": row.concept_name,
                "total_score": 0.0,
                "days_count": 0,
                "last_pct_chg": 0.0,
                "last_up_nums": 0,
            }

        concept_scores[row.concept_code]["total_score"] += (row.pct_chg or 0 + up_bonus) * weight
        concept_scores[row.concept_code]["days_count"] += 1
        concept_scores[row.concept_code]["last_pct_chg"] = row.pct_chg or 0
        concept_scores[row.concept_code]["last_up_nums"] = row.up_nums or 0

    sorted_concepts = sorted(
        concept_scores.items(),
        key=lambda x: x[1]["total_score"],
        reverse=True,
    )[:top_n]

    return {
        "trade_dates": [d.strftime("%Y%m%d") for d in trade_dates],
        "data_days": len(trade_dates),
        "items": [
            {
                "concept_code": code,
                "concept_name": data["name"],
                "total_score": round(data["total_score"], 4),
                "appear_days": data["days_count"],
                "last_pct_chg": round(data["last_pct_chg"], 4),
                "last_up_nums": data["last_up_nums"],
                "rank": idx + 1,
            }
            for idx, (code, data) in enumerate(sorted_concepts)
        ],
    }


async def get_concept_stocks(
    concept_code: str,
    db: AsyncSession,
    sort_by: str = "volume",
    limit: int = 30,
):
    """
    获取概念的成分股列表（按资金面/涨跌排序）

    concept_code: THS TI 格式（如 885806.TI 华为概念）
    支持按代码、名称模糊查找
    """
    # 用 TI 格式代码直接从 ths_concepts 表查找
    concept_stmt = select(ThsConcept).where(ThsConcept.ts_code == concept_code)
    concept_result = await db.execute(concept_stmt)
    concept = concept_result.scalar_one_or_none()

    # 查不到时，用名称模糊匹配
    if not concept:
        concept_stmt = select(ThsConcept).where(ThsConcept.name == concept_code)
        concept_result = await db.execute(concept_stmt)
        concept = concept_result.scalar_one_or_none()

    if not concept:
        raise HTTPException(status_code=404, detail="概念不存在")

    # 成分股列表（从 ths_concept_members 查，con_code 是股票代码）
    member_stmt = select(ThsConceptMember.con_code, ThsConceptMember.con_name).where(
        ThsConceptMember.ts_code == concept.ts_code
    )
    member_result = await db.execute(member_stmt)
    member_rows = member_result.all()

    if not member_rows:
        return {
            "concept_code": concept.ts_code,
            "concept_name": concept.name,
            "stock_count": 0,
            "items": [],
        }

    stock_codes = [r[0] for r in member_rows]
    con_name_map = {r[0]: r[1] for r in member_rows}

    # 关联 stocks 表获取行业等信息
    stock_info_stmt = select(Stock.ts_code, Stock.name, Stock.industry).where(Stock.ts_code.in_(stock_codes))
    stock_info_result = await db.execute(stock_info_stmt)
    stock_info_map = {r[0]: {"name": r[1], "industry": r[2]} for r in stock_info_result.fetchall()}

    # 最新交易日
    date_stmt = select(func.max(DailyData.trade_date)).where(DailyData.ts_code.in_(stock_codes))
    latest_date = (await db.execute(date_stmt)).scalar_one_or_none()

    if not latest_date:
        items = [
            {
                "ts_code": code,
                "name": stock_info_map.get(code, {}).get("name") or con_name_map.get(code, ""),
                "industry": stock_info_map.get(code, {}).get("industry"),
                "close": None,
                "pct_chg": None,
                "volume_ratio": None,
                "turnover_rate": None,
                "pe": None,
                "pb": None,
            }
            for code in stock_codes[:limit]
        ]
        return {
            "concept_code": concept.ts_code,
            "concept_name": concept.name,
            "stock_count": len(stock_codes),
            "latest_trade_date": None,
            "sort_by": sort_by,
            "items": items,
        }

    # 日线数据
    price_stmt = select(DailyData.ts_code, DailyData.close, DailyData.pct_chg).where(
        and_(DailyData.ts_code.in_(stock_codes), DailyData.trade_date == latest_date)
    )
    price_map = {r[0]: {"close": r[1], "pct_chg": r[2]} for r in (await db.execute(price_stmt)).fetchall()}

    # 基本面数据
    basic_stmt = select(
        DailyBasic.ts_code,
        DailyBasic.turnover_rate,
        DailyBasic.volume_ratio,
        DailyBasic.pe,
        DailyBasic.pb,
    ).where(and_(DailyBasic.ts_code.in_(stock_codes), DailyBasic.trade_date == latest_date))
    basic_map = {
        r[0]: {"turnover_rate": r[1], "volume_ratio": r[2], "pe": r[3], "pb": r[4]}
        for r in (await db.execute(basic_stmt)).fetchall()
    }

    # 合并
    stocks_data = []
    for code in stock_codes:
        p = price_map.get(code, {})
        b = basic_map.get(code, {})
        stocks_data.append(
            {
                "ts_code": code,
                "name": stock_info_map.get(code, {}).get("name") or con_name_map.get(code, ""),
                "industry": stock_info_map.get(code, {}).get("industry"),
                "close": p.get("close"),
                "pct_chg": p.get("pct_chg"),
                "volume_ratio": b.get("volume_ratio"),
                "turnover_rate": b.get("turnover_rate"),
                "pe": b.get("pe"),
                "pb": b.get("pb"),
            }
        )

    # 排序
    sort_keys = {"volume": "volume_ratio", "turnover": "turnover_rate", "pct_chg": "pct_chg"}
    key = sort_keys.get(sort_by, "volume_ratio")
    stocks_data.sort(key=lambda x: x.get(key) or 0, reverse=True)

    return {
        "concept_code": concept.ts_code,
        "concept_name": concept.name,
        "stock_count": len(stock_codes),
        "latest_trade_date": latest_date.strftime("%Y%m%d") if latest_date else None,
        "sort_by": sort_by,
        "items": stocks_data[:limit],
    }


async def get_stock_concepts(
    ts_code: str,
    db: AsyncSession,
):
    """
    给定个股，返回它所属的所有概念
    （从 ths_concept_members 表查询，TI 格式与 concept_limit 自然对齐）
    """
    # 验证股票存在
    stock_stmt = select(Stock.name).where(Stock.ts_code == ts_code)
    stock_name = (await db.execute(stock_stmt)).scalar_one_or_none()
    if not stock_name:
        raise HTTPException(status_code=404, detail="股票不存在")

    # 查询所属概念（从 ths_concept_members）
    member_stmt = select(ThsConceptMember.ts_code).where(ThsConceptMember.con_code == ts_code)
    member_result = await db.execute(member_stmt)
    ths_codes = [row[0] for row in member_result.fetchall()]

    if not ths_codes:
        return {
            "ts_code": ts_code,
            "stock_name": stock_name,
            "concept_count": 0,
            "items": [],
        }

    # 获取概念名称
    concept_stmt = select(ThsConcept.ts_code, ThsConcept.name).where(ThsConcept.ts_code.in_(ths_codes))
    concept_name_map = {r[0]: r[1] for r in (await db.execute(concept_stmt)).fetchall()}

    # 获取近期涨停数据（concept_limit 用同样的 TI 格式，直接匹配）
    limit_stmt = (
        select(
            ConceptLimit.concept_code,
            ConceptLimit.pct_chg,
            ConceptLimit.up_nums,
            ConceptLimit.trade_date,
        )
        .where(ConceptLimit.concept_code.in_(ths_codes))
        .order_by(desc(ConceptLimit.trade_date))
    )
    limit_map: dict[str, dict] = {}
    for code, pct_chg, up_nums, trade_date in (await db.execute(limit_stmt)).fetchall():
        if code not in limit_map:
            limit_map[code] = {
                "pct_chg": pct_chg,
                "up_nums": up_nums,
                "trade_date": trade_date.strftime("%Y%m%d") if trade_date else None,
            }

    return {
        "ts_code": ts_code,
        "stock_name": stock_name,
        "concept_count": len(ths_codes),
        "items": [
            {
                "concept_code": code,
                "concept_name": concept_name_map.get(code, ""),
                "last_pct_chg": limit_map.get(code, {}).get("pct_chg"),
                "last_up_nums": limit_map.get(code, {}).get("up_nums"),
                "last_trade_date": limit_map.get(code, {}).get("trade_date"),
            }
            for code in ths_codes
        ],
    }

