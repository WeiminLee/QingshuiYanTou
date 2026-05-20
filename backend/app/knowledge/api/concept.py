"""
概念分析 API

核心功能：
- 每日涨停概念 TOP10 排名（从本地 concept_limit 表读取历史数据计算）
- 概念详情查询（成分股 + 资金面排序）
- 统一使用 THS TI 格式（与 limit_cpt_list 体系一致）
"""
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc, and_

from app.core.database import get_db
from app.models.models import (
    Stock, DailyData, ConceptLimit, DailyBasic,
    ThsConcept, ThsConceptMember, ConceptScore, StockScore,
)

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/top-concepts")
async def get_top_concepts(
    days: int = Query(default=5, ge=2, le=20, description="统计最近N个交易日"),
    top_n: int = Query(default=10, ge=1, le=30, description="返回TOP N概念"),
    db: AsyncSession = Depends(get_db),
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
    trade_dates_stmt = (
        select(ConceptLimit.trade_date)
        .distinct()
        .order_by(desc(ConceptLimit.trade_date))
        .limit(days)
    )
    result = await db.execute(trade_dates_stmt)
    trade_dates = [row[0] for row in result.fetchall()]

    if len(trade_dates) < 2:
        raise HTTPException(
            status_code=400,
            detail=f"本地数据不足（仅{len(trade_dates)}个交易日），请先运行同步脚本采集数据"
        )

    # 读取所有相关数据
    data_stmt = select(ConceptLimit).where(
        ConceptLimit.trade_date.in_(trade_dates)
    )
    result = await db.execute(data_stmt)
    rows = result.scalars().all()

    # 按概念聚合
    concept_scores: dict[str, dict] = {}
    for row in rows:
        idx = trade_dates.index(row.trade_date)
        weight = 1.0 / (2 ** idx)
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


@router.get("/concept/{concept_code}/stocks")
async def get_concept_stocks(
    concept_code: str,
    sort_by: str = Query(default="volume", description="排序: volume/turnover/pct_chg"),
    limit: int = Query(default=30, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
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
    member_stmt = (
        select(ThsConceptMember.con_code, ThsConceptMember.con_name)
        .where(ThsConceptMember.ts_code == concept.ts_code)
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
    stock_info_stmt = (
        select(Stock.ts_code, Stock.name, Stock.industry)
        .where(Stock.ts_code.in_(stock_codes))
    )
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
    price_stmt = (
        select(DailyData.ts_code, DailyData.close, DailyData.pct_chg)
        .where(and_(DailyData.ts_code.in_(stock_codes), DailyData.trade_date == latest_date))
    )
    price_map = {r[0]: {"close": r[1], "pct_chg": r[2]} for r in (await db.execute(price_stmt)).fetchall()}

    # 基本面数据
    basic_stmt = (
        select(DailyBasic.ts_code, DailyBasic.turnover_rate, DailyBasic.volume_ratio, DailyBasic.pe, DailyBasic.pb)
        .where(and_(DailyBasic.ts_code.in_(stock_codes), DailyBasic.trade_date == latest_date))
    )
    basic_map = {r[0]: {"turnover_rate": r[1], "volume_ratio": r[2], "pe": r[3], "pb": r[4]} for r in (await db.execute(basic_stmt)).fetchall()}

    # 合并
    stocks_data = []
    for code in stock_codes:
        p = price_map.get(code, {})
        b = basic_map.get(code, {})
        stocks_data.append({
            "ts_code": code,
            "name": stock_info_map.get(code, {}).get("name") or con_name_map.get(code, ""),
            "industry": stock_info_map.get(code, {}).get("industry"),
            "close": p.get("close"),
            "pct_chg": p.get("pct_chg"),
            "volume_ratio": b.get("volume_ratio"),
            "turnover_rate": b.get("turnover_rate"),
            "pe": b.get("pe"),
            "pb": b.get("pb"),
        })

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


@router.get("/stock/{ts_code}/concepts")
async def get_stock_concepts(
    ts_code: str,
    db: AsyncSession = Depends(get_db),
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
    member_stmt = (
        select(ThsConceptMember.ts_code)
        .where(ThsConceptMember.con_code == ts_code)
    )
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
        select(ConceptLimit.concept_code, ConceptLimit.pct_chg, ConceptLimit.up_nums, ConceptLimit.trade_date)
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


@router.get("/concept/{concept_code}/history")
async def get_concept_history(
    concept_code: str,
    days: int = Query(default=10, ge=2, le=60),
    db: AsyncSession = Depends(get_db),
):
    """
    获取概念历史每日涨停数据（从 concept_limit 表）

    concept_code: THS TI 格式（如 885806.TI）或概念名称
    """
    # 优先用 TI 格式直接查
    stmt = (
        select(ConceptLimit)
        .where(ConceptLimit.concept_code == concept_code)
        .order_by(desc(ConceptLimit.trade_date))
        .limit(days)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()

    # 查不到时，尝试当作概念名称查
    if not rows:
        stmt = (
            select(ConceptLimit)
            .where(ConceptLimit.concept_name == concept_code)
            .order_by(desc(ConceptLimit.trade_date))
            .limit(days)
        )
        result = await db.execute(stmt)
        rows = result.scalars().all()

    if not rows:
        raise HTTPException(status_code=404, detail="该概念无历史数据")

    return {
        "concept_code": concept_code,
        "concept_name": rows[0].concept_name if rows else "",
        "items": [
            {
                "trade_date": r.trade_date.strftime("%Y%m%d"),
                "pct_chg": r.pct_chg,
                "up_nums": r.up_nums,
                "days": r.days,
                "rank": r.rank,
            }
            for r in rows
        ],
    }


@router.post("/sync/concept-limit")
async def sync_concept_limit_today():
    """
    手动触发今日涨停概念数据同步。
    前端 Dashboard 桑基图已降级展示，本接口返回空。
    """


# ── 概念/个股评分 ───────────────────────────────────────

@router.get("/scores/concepts")
async def get_concept_scores(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """
    获取概念评分列表（按评分降序）
    """
    stmt = (
        select(ConceptScore)
        .order_by(desc(ConceptScore.score))
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()

    count_stmt = select(func.count(ConceptScore.id))
    total = (await db.execute(count_stmt)).scalar_one()

    return {
        "total": total,
        "items": [
            {
                "concept_ts_code": r.concept_ts_code,
                "name": r.name,
                "score": r.score,
                "momentum_5d": r.momentum_5d,
                "momentum_1d": r.momentum_1d,
                "breadth": round(r.breadth, 4) if r.breadth else None,
                "breadth_rising": r.breadth_rising,
                "breadth_total": r.breadth_total,
                "relative_strength": r.relative_strength,
                "trade_date": r.trade_date.strftime("%Y-%m-%d") if r.trade_date else None,
                "calculated_at": r.calculated_at.isoformat() if r.calculated_at else None,
            }
            for r in rows
        ],
    }


@router.get("/scores/concepts/{concept_ts_code}")
async def get_concept_score(
    concept_ts_code: str,
    db: AsyncSession = Depends(get_db),
):
    """
    获取单个概念的评分详情
    """
    stmt = (
        select(ConceptScore)
        .where(ConceptScore.concept_ts_code == concept_ts_code)
        .order_by(desc(ConceptScore.trade_date))
        .limit(1)
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()

    if not row:
        raise HTTPException(status_code=404, detail="该概念无评分数据")

    return {
        "concept_ts_code": row.concept_ts_code,
        "name": row.name,
        "score": row.score,
        "momentum_5d": row.momentum_5d,
        "momentum_1d": row.momentum_1d,
        "breadth": round(row.breadth, 4) if row.breadth else None,
        "breadth_rising": row.breadth_rising,
        "breadth_total": row.breadth_total,
        "relative_strength": row.relative_strength,
        "stock_count": row.stock_count,
        "trade_date": row.trade_date.strftime("%Y-%m-%d") if row.trade_date else None,
        "calculated_at": row.calculated_at.isoformat() if row.calculated_at else None,
    }


@router.get("/scores/stocks")
async def get_stock_scores(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """
    获取个股评分列表（按总分降序）
    """
    stmt = (
        select(StockScore)
        .order_by(desc(StockScore.total_score))
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()

    count_stmt = select(func.count(StockScore.id))
    total = (await db.execute(count_stmt)).scalar_one()

    return {
        "total": total,
        "items": [
            {
                "ts_code": r.ts_code,
                "name": r.name,
                "total_score": r.total_score,
                "momentum_score": r.momentum_score,
                "trend_score": r.trend_score,
                "capital_score": r.capital_score,
                "concept_bonus": r.concept_bonus,
                "valuation_bonus": r.valuation_bonus,
                "momentum_5d": r.momentum_5d,
                "turnover_rate_pct": r.turnover_rate_pct,
                "vol_ratio": r.vol_ratio,
                "trade_date": r.trade_date.strftime("%Y-%m-%d") if r.trade_date else None,
            }
            for r in rows
        ],
    }


@router.get("/scores/stocks/{ts_code}")
async def get_stock_score(
    ts_code: str,
    db: AsyncSession = Depends(get_db),
):
    """
    获取个股综合评分详情
    """
    stmt = (
        select(StockScore)
        .where(StockScore.ts_code == ts_code)
        .order_by(desc(StockScore.trade_date))
        .limit(1)
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()

    if not row:
        raise HTTPException(status_code=404, detail="该股票无评分数据")

    # 获取该股票所属的概念评分
    concept_stmt = (
        select(ConceptScore)
        .join(ThsConceptMember, ThsConceptMember.ts_code == ConceptScore.concept_ts_code)
        .where(ThsConceptMember.con_code == ts_code)
        .where(ConceptScore.trade_date == row.trade_date)
        .order_by(desc(ConceptScore.score))
    )
    concept_result = await db.execute(concept_stmt)
    concept_rows = concept_result.scalars().all()

    return {
        "ts_code": row.ts_code,
        "name": row.name,
        "total_score": row.total_score,
        "breakdown": {
            "momentum_score": row.momentum_score,
            "trend_score": row.trend_score,
            "capital_score": row.capital_score,
            "concept_bonus": row.concept_bonus,
            "valuation_bonus": row.valuation_bonus,
        },
        "raw_data": {
            "momentum_5d": row.momentum_5d,
            "turnover_rate_pct": row.turnover_rate_pct,
            "vol_ratio": row.vol_ratio,
            "ma_state": row.ma_state,
        },
        "trade_date": row.trade_date.strftime("%Y-%m-%d") if row.trade_date else None,
        "concept_scores": [
            {
                "concept_ts_code": c.concept_ts_code,
                "name": c.name,
                "score": c.score,
                "momentum_5d": c.momentum_5d,
                "breadth": round(c.breadth, 4) if c.breadth else None,
            }
            for c in concept_rows
        ],
    }


@router.post("/scores/calculate")
async def trigger_score_calculation():
    """
    手动触发评分计算（后台异步执行）
    """
    import subprocess
    import sys
    from pathlib import Path
    script = str(Path(__file__).parent.parent / "scripts" / "sync_concept_scores.py")
    subprocess.Popen(
        [sys.executable, script],
        cwd=str(Path(__file__).parent.parent.parent),
    )
    return {"message": "评分计算任务已启动"}

