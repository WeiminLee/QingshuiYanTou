"""
个股综合评分

总分 = 动量分(≤25) + 趋势分(≤30) + 资金面分(≤25) + 概念溢价(≤15) + 估值加分(≤5)
"""
import logging
from datetime import date
from typing import Optional

import pandas as pd
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import DailyData, DailyBasic, ThsConceptMember, ThsConcept, ConceptLimit

logger = logging.getLogger(__name__)


async def compute_stock_score(
    db: AsyncSession,
    ts_code: str,
    trade_date: Optional[date] = None,
) -> dict:
    """
    计算个股综合评分（满分100）

    返回结构:
    {
        "ts_code": str,
        "total_score": float,
        "breakdown": {
            "momentum": {"score": float, "detail": {...}},
            "trend": {"score": float, "detail": {...}},
            "capital": {"score": float, "detail": {...}},
            "concept": {"score": float, "detail": {...}},
            "valuation": {"score": float, "detail": {...}},
        }
    }
    """
    # 确定参考日期
    if trade_date is None:
        date_stmt = select(func.max(DailyData.trade_date)).where(DailyData.ts_code == ts_code)
        trade_date = (await db.execute(date_stmt)).scalar_one_or_none()

    if trade_date is None:
        return {"ts_code": ts_code, "total_score": None, "error": "无日线数据"}

    # 读取近60日日线数据（升序）
    daily_stmt = (
        select(DailyData)
        .where(DailyData.ts_code == ts_code, DailyData.trade_date <= trade_date)
        .order_by(DailyData.trade_date.desc())
        .limit(60)
    )
    daily_rows = (await db.execute(daily_stmt)).scalars().all()
    daily_rows = list(reversed(daily_rows))  # 转为升序

    if len(daily_rows) < 5:
        return {"ts_code": ts_code, "total_score": None, "error": f"数据不足（{len(daily_rows)}条）"}

    # 读取最新基本面
    basic_stmt = (
        select(DailyBasic)
        .where(DailyBasic.ts_code == ts_code, DailyBasic.trade_date <= trade_date)
        .order_by(DailyBasic.trade_date.desc())
        .limit(1)
    )
    basic = (await db.execute(basic_stmt)).scalar_one_or_none()

    # 读取所属概念及其近期涨停数据
    member_stmt = (
        select(ThsConceptMember.ts_code)
        .where(ThsConceptMember.con_code == ts_code)
    )
    ths_codes = [row[0] for row in (await db.execute(member_stmt)).fetchall()]

    limit_data = {}
    if ths_codes:
        limit_stmt = (
            select(ConceptLimit.concept_code, ConceptLimit.pct_chg, ConceptLimit.up_nums)
            .where(ConceptLimit.concept_code.in_(ths_codes))
            .order_by(desc(ConceptLimit.trade_date))
        )
        for code, pct_chg, up_nums in (await db.execute(limit_stmt)).fetchall():
            if code not in limit_data:
                limit_data[code] = {"pct_chg": pct_chg, "up_nums": up_nums}

    # ── 转换为 DataFrame ──
    df = pd.DataFrame([
        {
            "close": r.close,
            "pct_chg": r.pct_chg,
            "vol": r.vol,
            "amount": r.amount,
        }
        for r in daily_rows
    ])
    latest = df.iloc[-1]

    # ── 1. 动量分（0-25）──
    pct_5d = df["pct_chg"].iloc[-5:].sum() if len(df) >= 5 else df["pct_chg"].sum()
    rsi = _compute_rsi(df["pct_chg"].tolist(), 14)
    vol_series = df["vol"].tolist()
    vol_ratio = vol_series[-1] / pd.Series(vol_series[:-1]).mean() if sum(vol_series[:-1]) > 0 else 1

    momentum_score = 0
    # 近5日涨幅得分（0-15）
    if pct_5d > 20:
        momentum_score += 15
    elif pct_5d > 10:
        momentum_score += 12
    elif pct_5d > 5:
        momentum_score += 9
    elif pct_5d > 0:
        momentum_score += 6
    elif pct_5d > -5:
        momentum_score += 3
    elif pct_5d > -10:
        momentum_score += 1

    # RSI 调整（0-5）
    if rsi is not None:
        if rsi > 70:
            momentum_score += 2  # 超买轻微警告
        elif rsi < 30:
            momentum_score += 5  # 超卖加分
        else:
            momentum_score += 3

    # 量价共振（0-5）
    if len(df) >= 2:
        if df["pct_chg"].iloc[-1] > 0 and vol_ratio > 1.2:
            momentum_score += 3
        elif df["pct_chg"].iloc[-1] < 0 and vol_ratio < 0.8:
            momentum_score += 2
        elif df["pct_chg"].iloc[-1] > 0 and vol_ratio > 0.8:
            momentum_score += 1

    momentum_score = min(momentum_score, 25)

    # ── 2. 趋势分（0-30）──
    close = df["close"].values
    ma5 = _ma(close, 5)
    ma10 = _ma(close, 10)
    ma20 = _ma(close, 20)
    current_price = close[-1]

    macd_diff, macd_dea = _compute_macd(close)

    trend_score = 0
    # 均线多头/空头排列
    if ma5 and ma10 and ma20:
        if ma5 > ma10 > ma20 and current_price > ma5:
            trend_score += 12  # 多头排列
        elif ma5 < ma10 < ma20 and current_price < ma5:
            trend_score -= 4   # 空头排列
        else:
            trend_score += 3   # 均线纠结

    # 价格与MA20关系
    if ma20:
        if current_price > ma20:
            trend_score += 10
        else:
            trend_score += 0

    # 均线收敛蓄势
    if ma5 and ma20 and abs(ma5 - ma20) / ma20 < 0.02:
        trend_score += 5

    # MACD
    if macd_diff is not None and macd_dea is not None:
        if macd_diff > macd_dea:
            trend_score += 3
        else:
            trend_score += 0

    trend_score = max(0, min(trend_score, 30))

    # ── 3. 资金面分（0-25）──
    cap_score = 0
    if basic:
        # 换手率得分（0-12）
        turnover = basic.turnover_rate or 0
        if turnover >= 10:
            cap_score += 12
        elif turnover >= 5:
            cap_score += 8
        elif turnover >= 2:
            cap_score += 5
        elif turnover >= 1:
            cap_score += 3

        # 量比得分（0-8）
        vol_ratio_basic = basic.volume_ratio or 0
        if vol_ratio_basic >= 3:
            cap_score += 8
        elif vol_ratio_basic >= 2:
            cap_score += 5
        elif vol_ratio_basic >= 1.5:
            cap_score += 3

        # 量价配合（0-5）
        if basic.pct_chg is not None:
            if basic.pct_chg > 0 and vol_ratio_basic >= 1.2:
                cap_score += 3
            elif basic.pct_chg < 0 and vol_ratio_basic <= 0.8:
                cap_score += 2

    cap_score = min(cap_score, 25)

    # ── 4. 概念溢价（0-15）──
    concept_score = 0
    if limit_data:
        # 取涨停概念中得分最高的一个
        best_score = 0
        for code, data in limit_data.items():
            pct = data.get("pct_chg") or 0
            up_nums = data.get("up_nums") or 0
            score_for_concept = pct * 2 + up_nums * 0.5
            if score_for_concept > best_score:
                best_score = score_for_concept
        concept_score = min(round(best_score), 15)
        # score_for_concept 可能在 0-30 范围，*2 后最多60，概念溢价上限15
        concept_score = min(max(int(best_score), 0), 15)

    # ── 5. 估值加分（0-5）──
    val_score = 0
    if basic:
        pe = basic.pe
        pb = basic.pb
        if pe and 0 < pe < 50:
            if pe < 15:
                val_score += 3
            elif pe < 30:
                val_score += 2
            elif pe < 50:
                val_score += 1
        if pb and 0 < pb < 20:
            if pb < 2:
                val_score += 2
            elif pb < 4:
                val_score += 1
    val_score = min(val_score, 5)

    total = momentum_score + trend_score + cap_score + concept_score + val_score

    return {
        "ts_code": ts_code,
        "total_score": total,
        "trade_date": trade_date.strftime("%Y%m%d") if trade_date else None,
        "breakdown": {
            "momentum": {
                "score": momentum_score,
                "pct_5d": round(pct_5d, 2),
                "rsi": round(rsi, 1) if rsi else None,
                "vol_ratio": round(vol_ratio, 2),
            },
            "trend": {
                "score": trend_score,
                "price": round(current_price, 2),
                "ma5": round(ma5, 2) if ma5 else None,
                "ma10": round(ma10, 2) if ma10 else None,
                "ma20": round(ma20, 2) if ma20 else None,
                "macd_bullish": macd_diff > macd_dea if (macd_diff and macd_dea) else None,
            },
            "capital": {
                "score": cap_score,
                "turnover_rate": round(basic.turnover_rate, 2) if basic and basic.turnover_rate else None,
                "volume_ratio": round(basic.volume_ratio, 2) if basic and basic.volume_ratio else None,
            },
            "concept": {
                "score": concept_score,
                "limit_concepts": [
                    {"code": code, "pct_chg": data["pct_chg"], "up_nums": data["up_nums"]}
                    for code, data in list(limit_data.items())[:3]
                ],
            },
            "valuation": {
                "score": val_score,
                "pe": round(basic.pe, 1) if basic and basic.pe else None,
                "pb": round(basic.pb, 2) if basic and basic.pb else None,
            },
        },
    }


# ── 辅助函数 ──────────────────────────────────

def _ma(close_arr, window) -> Optional[float]:
    if len(close_arr) < window:
        return None
    return sum(close_arr[-window:]) / window


def _compute_rsi(changes: list, period: int = 14) -> Optional[float]:
    if len(changes) <= period:
        return None
    gains = [c if c > 0 else 0 for c in changes[-period - 1:]]
    losses = [-c if c < 0 else 0 for c in changes[-period - 1:]]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _compute_macd(close_arr, fast=12, slow=26, signal=9):
    if len(close_arr) < slow + signal:
        return None, None
    ema_fast = _ema(close_arr, fast)
    ema_slow = _ema(close_arr, slow)
    if ema_fast is None or ema_slow is None:
        return None, None
    dif = ema_fast - ema_slow
    dea = dif * 0.2  # 简化近似
    return dif, dea


def _ema(close_arr: list, period: int) -> Optional[float]:
    if len(close_arr) < period:
        return None
    k = 2 / (period + 1)
    ema = sum(close_arr[:period]) / period
    for price in close_arr[period:]:
        ema = price * k + ema * (1 - k)
    return ema
