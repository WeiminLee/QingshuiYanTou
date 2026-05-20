"""
股票情报包生成器

输入 ts_code → 输出 Markdown 格式的股票基础情报包
供推理决策层使用
"""
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import (
    Stock, DailyData, DailyBasic,
    ThsConcept, ThsConceptMember, StockPool,
    CompanyProfile,
)
from app.core.database import async_session


# ── 均值计算 ──────────────────────────────────────

def _ma(closes: list[float], n: int) -> Optional[float]:
    if len(closes) < n:
        return None
    return sum(closes[-n:]) / n


def _ma_status(closes: list[float], ma5: Optional[float], ma10: Optional[float], ma20: Optional[float]) -> str:
    if not (ma5 and ma10 and ma20):
        return "数据不足，无法判断"
    if ma5 > ma10 > ma20:
        return "多头排列"
    elif ma5 < ma10 < ma20:
        return "空头排列"
    else:
        return "纠缠"


# ── 行情数据整理 ──────────────────────────────────

async def _fetch_daily_data(db: AsyncSession, ts_code: str, days: int = 21) -> list[dict]:
    """获取近 N 日行情数据（按日期升序）"""
    today = date.today()
    start = today - timedelta(days=days * 2)  # 多取一些防停牌

    stmt = (
        select(DailyData)
        .where(
            and_(
                DailyData.ts_code == ts_code,
                DailyData.trade_date >= start,
                DailyData.trade_date <= today,
            )
        )
        .order_by(DailyData.trade_date)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()

    data = []
    for r in rows:
        data.append({
            "trade_date": r.trade_date,
            "open": r.open,
            "high": r.high,
            "low": r.low,
            "close": r.close,
            "pct_chg": r.pct_chg,
            "vol": r.vol,
            "amount": r.amount,
            "is_suspended": r.is_suspended or False,
        })
    return data


async def _fetch_latest_basic(db: AsyncSession, ts_code: str) -> Optional[dict]:
    """获取最新基本面数据（PE/PB/换手率/市值）"""
    stmt = (
        select(DailyBasic)
        .where(DailyBasic.ts_code == ts_code)
        .order_by(DailyBasic.trade_date.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if not row:
        return None
    return {
        "trade_date": row.trade_date,
        "close": row.close,
        "turnover_rate": row.turnover_rate,
        "pe": row.pe,
        "pe_ttm": row.pe_ttm,
        "pb": row.pb,
        "total_mv": row.total_mv,      # 万元
        "circ_mv": row.circ_mv,       # 万元
    }


async def _fetch_concepts(db: AsyncSession, ts_code: str) -> list[str]:
    """获取个股所属概念列表"""
    stmt = (
        select(ThsConcept.name)
        .join(ThsConceptMember, ThsConcept.ts_code == ThsConceptMember.ts_code)
        .where(ThsConceptMember.con_code == ts_code)
        .distinct()
    )
    result = await db.execute(stmt)
    return [r[0] for r in result.fetchall()]


async def _fetch_stockpool_status(db: AsyncSession, ts_code: str) -> Optional[dict]:
    """获取 StockPool 状态"""
    stmt = (
        select(StockPool)
        .where(StockPool.ts_code == ts_code, StockPool.out_date.is_(None))
        .limit(1)
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if not row:
        return None
    return {
        "concept_name": row.concept_name,
        "concept_code": row.concept_code,
        "in_date": row.in_date,
    }


async def _fetch_company_profile(db: AsyncSession, ts_code: str) -> Optional[dict]:
    """获取公司概况"""
    stmt = select(CompanyProfile).where(CompanyProfile.ts_code == ts_code)
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if not row:
        return None
    return {
        "com_name": row.com_name,
        "main_business": row.main_business,
        "business_scope": row.business_scope,
        "introduction": row.introduction,
        "employees": row.employees,
        "province": row.province,
        "city": row.city,
        "setup_date": row.setup_date,
    }


# ── 异动标注 ──────────────────────────────────────

def _build_异动标注(daily_data: list[dict], latest_basic: Optional[dict]) -> list[str]:
    """生成异动标注（事实陈述，不做判断）"""
    labels = []

    # 近5日累计涨幅
    if len(daily_data) >= 5:
        closes = [d["close"] for d in daily_data[-5:] if d["close"]]
        if len(closes) == 5:
            pct_5d = (closes[-1] / closes[0] - 1) * 100
            labels.append(f"近5日累计涨幅：{pct_5d:+.2f}%（{closes[0]:.2f} → {closes[-1]:.2f}）")

    # 今日换手率
    if latest_basic and latest_basic.get("turnover_rate"):
        turnover = latest_basic["turnover_rate"]
        labels.append(f"今日换手率：{turnover:.2f}%")

    # 均线状态
    closes = [d["close"] for d in daily_data if d["close"]]
    if len(closes) >= 20:
        ma5 = _ma(closes, 5)
        ma10 = _ma(closes, 10)
        ma20 = _ma(closes, 20)
        status = _ma_status(closes, ma5, ma10, ma20)
        labels.append(f"均线状态：{status}")

    return labels


# ── 主函数 ────────────────────────────────────────

async def build_stock_package(ts_code: str) -> str:
    """
    生成股票基础情报包（Markdown 格式）

    包含：
    - 基础信息
    - 今日行情
    - 近20日行情（含均线）
    - 基本面
    - 概念关联
    - 公司概况（主营业务/经营范围/简介）
    - StockPool 状态
    - 异动标注

    注意：互动易 Q&A 在单独的情报包里，不在此
    """
    async with async_session() as db:
        # 1. 基础信息
        stmt = select(Stock).where(Stock.ts_code == ts_code)
        result = await db.execute(stmt)
        stock = result.scalar_one_or_none()
        if not stock:
            return f"**错误**：未找到股票 {ts_code}"

        # 2. 行情数据（多取1天用于均线计算）
        daily_data = await _fetch_daily_data(db, ts_code, days=21)
        if not daily_data:
            return f"**错误**：{ts_code} 暂无行情数据"

        # 3. 最新基本面
        latest_basic = await _fetch_latest_basic(db, ts_code)

        # 4. 概念列表
        concepts = await _fetch_concepts(db, ts_code)

        # 5. StockPool 状态
        pool_status = await _fetch_stockpool_status(db, ts_code)

        # 6. 公司概况
        profile = await _fetch_company_profile(db, ts_code)

        # 7. 互动易 Q&A（基础包不含，单独在 material_package 中）

    # ── 组装 Markdown ────────────────────────────

    lines = []
    today_str = date.today().isoformat()

    # 标题
    lines.append(f"# {stock.name}（{ts_code}）\n")
    lines.append(f"> 生成时间：{today_str}\n")

    # 基础信息
    lines.append("## 基础信息\n")
    lines.append(f"- **代码**：`{stock.ts_code}`")
    lines.append(f"- **名称**：{stock.name}")
    lines.append(f"- **行业**：{stock.industry or '未知'}")
    lines.append(f"- **市场**：{stock.market or '未知'}")
    if stock.list_date:
        lines.append(f"- **上市日期**：{stock.list_date.isoformat()}")
    lines.append("")

    # 今日行情
    latest = daily_data[-1]
    lines.append("## 今日行情\n")
    lines.append(f"- **最新价**：`{latest['close']:.2f}`")
    lines.append(f"- **涨跌幅**：`{latest['pct_chg']:+.2f}%`" if latest.get('pct_chg') is not None else "- **涨跌幅**：暂无")
    lines.append(f"- **涨跌额**：`{latest.get('change', 0):+.2f}`")
    lines.append(f"- **今开**：`{latest['open']:.2f}`")
    lines.append(f"- **最高**：`{latest['high']:.2f}`")
    lines.append(f"- **最低**：`{latest['low']:.2f}`")
    lines.append(f"- **成交量**：`{latest['vol']:.0f} 手`" if latest['vol'] else "- **成交量**：暂无")
    lines.append(f"- **成交额**：`{latest['amount']/1000:.2f} 万元`" if latest['amount'] else "- **成交额**：暂无")
    if latest_basic and latest_basic.get("turnover_rate"):
        lines.append(f"- **换手率**：`{latest_basic['turnover_rate']:.2f}%`")
    if latest.get("is_suspended"):
        lines.append("> ⚠️ 该股票今日停牌")
    lines.append("")

    # 近20日行情 + 均线
    recent_20 = daily_data[-20:] if len(daily_data) >= 20 else daily_data
    closes = [d["close"] for d in recent_20 if d["close"]]
    ma5 = _ma(closes, 5)
    ma10 = _ma(closes, 10)
    ma20 = _ma(closes, 20)

    lines.append("## 近20日行情（均线）\n")
    lines.append(f"| 日期 | 开 | 高 | 低 | 收 | 涨跌幅 |")
    lines.append(f"|------|----|----|----|----|--------|")
    for d in recent_20:
        date_str = d["trade_date"].isoformat() if hasattr(d["trade_date"], "isoformat") else str(d["trade_date"])
        pct_str = f"{d['pct_chg']:+.2f}%" if d["pct_chg"] is not None else "-"
        suspended = "（停牌）" if d.get("is_suspended") else ""
        lines.append(
            f"| {date_str} | {d['open']:.2f} | {d['high']:.2f} | "
            f"{d['low']:.2f} | {d['close']:.2f} | {pct_str} {suspended} |"
        )
    lines.append("")
    ma5_str = f"{ma5:.2f}" if ma5 else "N/A"
    ma10_str = f"{ma10:.2f}" if ma10 else "N/A"
    ma20_str = f"{ma20:.2f}" if ma20 else "N/A"
    lines.append(f"**均线**：MA5 = `{ma5_str}`，MA10 = `{ma10_str}`，MA20 = `{ma20_str}`")
    lines.append("")

    # 基本面
    lines.append("## 基本面\n")
    if latest_basic:
        lines.append(f"- **收盘价**：`{latest_basic['close']:.2f}`")
        lines.append(f"- **PE（TTM）**：`{latest_basic['pe_ttm']:.2f}`" if latest_basic.get("pe_ttm") else "- **PE（TTM）**：暂无")
        lines.append(f"- **PE**：`{latest_basic['pe']:.2f}`" if latest_basic.get("pe") else "- **PE**：暂无")
        lines.append(f"- **PB**：`{latest_basic['pb']:.2f}`" if latest_basic.get("pb") else "- **PB**：暂无")
        if latest_basic.get("total_mv"):
            lines.append(f"- **总市值**：`{latest_basic['total_mv']/10000:.2f} 亿元`")
        if latest_basic.get("circ_mv"):
            lines.append(f"- **流通市值**：`{latest_basic['circ_mv']/10000:.2f} 亿元`")
    else:
        lines.append("暂无基本面数据（Tushare daily_basic 未同步）")
    lines.append("")

    # 概念关联
    lines.append("## 概念关联\n")
    if concepts:
        lines.append("该股票所属概念：")
        for c in concepts:
            lines.append(f"- {c}")
    else:
        lines.append("暂无概念信息")
    lines.append("")

    # 公司概况
    lines.append("## 公司概况\n")
    if profile:
        if profile.get("main_business"):
            lines.append(f"- **主营业务**：{profile['main_business']}")
        if profile.get("business_scope"):
            scope = str(profile["business_scope"])[:200]
            lines.append(f"- **经营范围**：{scope}...")
        if profile.get("introduction"):
            intro = str(profile["introduction"])[:300]
            lines.append(f"- **公司简介**：{intro}...")
        if profile.get("employees"):
            lines.append(f"- **员工人数**：{profile['employees']}")
        if profile.get("province") or profile.get("city"):
            loc = "/".join(filter(None, [profile.get("province", ""), profile.get("city", "")]))
            lines.append(f"- **所在地区**：{loc}")
        if profile.get("setup_date"):
            lines.append(f"- **成立日期**：{profile['setup_date']}")
    else:
        lines.append("暂无公司概况数据（请先运行 sync_company_profiles.py）")
    lines.append("")

    # StockPool 状态
    lines.append("## StockPool 状态\n")
    if pool_status:
        in_date_str = pool_status["in_date"].isoformat() if hasattr(pool_status["in_date"], "isoformat") else str(pool_status["in_date"])
        lines.append(f"- **所属热门板块**：{pool_status['concept_name']}（{pool_status['concept_code']}）")
        lines.append(f"- **纳入日期**：{in_date_str}")
        lines.append("- **状态**：当前在调研池中")
    else:
        lines.append("- **状态**：当前不在调研池中（不在TOP5热门板块内）")
    lines.append("")

    # 异动标注
    异动 = _build_异动标注(daily_data, latest_basic)
    lines.append("## 异动标注\n")
    if 异动:
        for item in 异动:
            lines.append(f"- {item}")
    else:
        lines.append("暂无明显异动信号")
    lines.append("")

    return "\n".join(lines)


# ── JSON 版本 ────────────────────────────────────────────────────────────────

async def build_stock_package_json(ts_code: str) -> dict:
    """
    生成股票基础情报包（JSON 格式）

    返回结构：
    {
        "ts_code": str,
        "generated_at": str,
        "basic_info": {...},
        "today": {...},
        "recent_20d": {
            "candles": [...],
            "ma": {"ma5": float, "ma10": float, "ma20": float}
        },
        "fundamentals": {...},
        "concepts": [...],
        "company_profile": {...},
        "stockpool": {...},
        "anomaly_labels": [...],
    }
    """
    async with async_session() as db:
        # 1. 基础信息
        stmt = select(Stock).where(Stock.ts_code == ts_code)
        result = await db.execute(stmt)
        stock = result.scalar_one_or_none()
        if not stock:
            return {"error": f"未找到股票 {ts_code}"}

        # 2. 行情数据（多取用于均线）
        daily_data = await _fetch_daily_data(db, ts_code, days=21)

        # 3. 最新基本面
        latest_basic = await _fetch_latest_basic(db, ts_code)

        # 4. 概念列表
        concepts = await _fetch_concepts(db, ts_code)

        # 5. StockPool 状态
        pool_status = await _fetch_stockpool_status(db, ts_code)

        # 6. 公司概况
        profile = await _fetch_company_profile(db, ts_code)

    if not daily_data:
        return {"error": f"{ts_code} 暂无行情数据"}

    # 近20日数据 + 均线计算
    recent_20 = daily_data[-20:] if len(daily_data) >= 20 else daily_data
    closes_for_ma = [d["close"] for d in recent_20 if d["close"]]

    ma5 = _ma(closes_for_ma, 5)
    ma10 = _ma(closes_for_ma, 10)
    ma20 = _ma(closes_for_ma, 20)
    ma_state = _ma_status(closes_for_ma, ma5, ma10, ma20)

    # 最新交易日数据
    latest = daily_data[-1]

    # 异动标注
    anomaly = _build_异动标注(daily_data, latest_basic)

    # 组装结构
    return {
        "ts_code": ts_code,
        "generated_at": datetime.now().isoformat(),
        "basic_info": {
            "name": stock.name,
            "industry": stock.industry,
            "market": stock.market,
            "list_date": stock.list_date.isoformat() if stock.list_date else None,
            "area": stock.area,
        },
        "today": {
            "trade_date": _date_str(latest.get("trade_date")),
            "open": latest.get("open"),
            "high": latest.get("high"),
            "low": latest.get("low"),
            "close": latest.get("close"),
            "pct_chg": latest.get("pct_chg"),
            "change": latest.get("change"),
            "vol": latest.get("vol"),
            "amount": latest.get("amount"),
            "is_suspended": latest.get("is_suspended", False),
        },
        "recent_20d": {
            "candles": [
                {
                    "trade_date": _date_str(d.get("trade_date")),
                    "open": d.get("open"),
                    "high": d.get("high"),
                    "low": d.get("low"),
                    "close": d.get("close"),
                    "pct_chg": d.get("pct_chg"),
                    "vol": d.get("vol"),
                }
                for d in recent_20
            ],
            "ma": {
                "ma5": round(ma5, 2) if ma5 else None,
                "ma10": round(ma10, 2) if ma10 else None,
                "ma20": round(ma20, 2) if ma20 else None,
            },
            "ma_state": ma_state,
        },
        "fundamentals": (
            {
                "trade_date": _date_str(latest_basic.get("trade_date")),
                "close": latest_basic.get("close"),
                "pe": latest_basic.get("pe"),
                "pe_ttm": latest_basic.get("pe_ttm"),
                "pb": latest_basic.get("pb"),
                "turnover_rate": latest_basic.get("turnover_rate"),
                "total_mv": latest_basic.get("total_mv"),   # 万元
                "circ_mv": latest_basic.get("circ_mv"),     # 万元
            }
            if latest_basic
            else None
        ),
        "concepts": concepts,
        "company_profile": profile,
        "stockpool": (
            {
                "in_pool": True,
                "concept_name": pool_status["concept_name"],
                "concept_code": pool_status["concept_code"],
                "in_date": _date_str(pool_status["in_date"]),
            }
            if pool_status
            else {"in_pool": False}
        ),
        "anomaly_labels": anomaly,
        # ── P1-3 新增字段 ────────────────────────────
        "confidence_summary": _build_confidence_summary(fundamentals=latest_basic),
        "core_insight": _build_core_insight(
            daily_data=daily_data,
            latest_basic=latest_basic,
            ma_state=ma_state,
            concepts=concepts,
        ),
        "catalyst_calendar": _build_catalyst_calendar(pool_status=pool_status),
        "risk_matrix": _build_risk_matrix(latest_basic=latest_basic, ma_state=ma_state),
        "tracking_indicators": _build_tracking_indicators(daily_data=daily_data),
        "disclaimer": "本情报包仅供参考，不构成任何投资建议。",
    }


# ── P1-3 新增辅助函数 ────────────────────────────────────

def _build_confidence_summary(fundamentals: Optional[dict]) -> dict:
    """
    各模块数据来源置信度汇总。

    按分层架构规范：
    - 技术面/资金面数据来自 Tushare 日线 → Tier 0
    - 概念板块来自 THS 同花顺 → Tier 0
    - 互动易/公告来自监管平台 → Tier 1
    - 研报来自券商公开研报 → Tier 4
    """
    sources = {
        "技术面（日线）": {"source": "Tushare日线", "tier": "Tier 0", "tier_score": 100},
        "资金面（日线）": {"source": "Tushare日线", "tier": "Tier 0", "tier_score": 100},
        "概念板块（THS）": {"source": "THS同花顺概念", "tier": "Tier 0", "tier_score": 100},
        "基本面（PE/PB）": {"source": "Tushare基本面", "tier": "Tier 0", "tier_score": 100},
        "互动易Q&A": {"source": "东方财富互动易", "tier": "Tier 1", "tier_score": 80},
        "公告全文": {"source": "巨潮资讯", "tier": "Tier 1", "tier_score": 80},
        "研报": {"source": "券商研报", "tier": "Tier 4", "tier_score": 50},
    }
    avg_score = sum(s["tier_score"] for s in sources.values()) / len(sources)
    if avg_score >= 90:
        level = "高"
        label = "高置信度"
    elif avg_score >= 70:
        level = "中"
        label = "中置信度"
    else:
        level = "低"
        label = "低置信度"
    return {
        "overall_level": level,
        "overall_label": label,
        "confidence_score": round(avg_score),
        "sources": sources,
    }


def _build_core_insight(
    daily_data: list[dict],
    latest_basic: Optional[dict],
    ma_state: str,
    concepts: list[str],
) -> dict:
    """
    核心逻辑链（3句话）+ 多空逻辑。

    基于量价数据生成结构化总结，
    供推理决策层快速理解个股当前状态。
    """
    # 技术趋势
    if not daily_data:
        tech_summary = "暂无行情数据"
        trend_direction = "未知"
    else:
        pct_5d = 0.0
        if len(daily_data) >= 5:
            pct_5d = daily_data[-1].get("pct_chg", 0) or 0
            for i in range(-2, -6, -1):
                pct_5d += daily_data[i].get("pct_chg", 0) or 0
        elif len(daily_data) >= 2:
            pct_5d = (daily_data[-1].get("close", 0) or 0) / (daily_data[-5].get("close", 1) or 1) - 1
            pct_5d *= 100

        if ma_state == "多头排列":
            trend_direction = "多头"
            tech_summary = f"均线多头排列，近5日累计涨幅{pct_5d:.1f}%，技术面强势"
        elif ma_state == "空头排列":
            trend_direction = "空头"
            tech_summary = f"均线空头排列，近5日累计跌幅{pct_5d:.1f}%，技术面承压"
        else:
            trend_direction = "震荡"
            tech_summary = f"均线纠缠，近5日累计涨跌{pct_5d:.1f}%，方向待确认"

    # 估值
    if latest_basic:
        pe = latest_basic.get("pe_ttm") or latest_basic.get("pe")
        if pe is not None and pe > 0:
            if pe < 20:
                valuation = "PE偏低，估值有优势"
            elif pe < 40:
                valuation = f"PE={pe:.1f}，估值处于合理区间"
            else:
                valuation = f"PE={pe:.1f}，估值偏高"
        else:
            valuation = "PE数据缺失，估值无法判断"
    else:
        valuation = "暂无基本面数据"

    # 概念
    if concepts:
        top_concepts = ", ".join(concepts[:3])
        concept_summary = f"涉及{len(concepts)}个概念，重点包括：{top_concepts}"
    else:
        concept_summary = "暂无概念标签"

    bull_case = f"{tech_summary}；{concept_summary}。"
    bear_case = (
        f"若{trend_direction}被破坏（如放量跌破均线支撑），"
        f"需重新评估。当前{valuation}，需关注业绩兑现情况。"
    )
    return {
        "tech_summary": tech_summary,
        "valuation_summary": valuation,
        "concept_summary": concept_summary,
        "bull_case": bull_case,
        "bear_case": bear_case,
    }


def _build_catalyst_calendar(pool_status: Optional[dict]) -> list[dict]:
    """
    催化剂日历：基于已知事件节点生成未来3-12个月跟踪节点。

    目前系统尚未接入财报日历/股权解禁等数据源，
    返回固定提示节点（V1.1 阶段，后续接入真实数据后替换）。
    """
    from datetime import date as Date, timedelta
    today = Date.today()
    events = []

    # 财报季：4月底（一季报）、8月底（中报）、10月底（三季报）、4月底（年报）
    for month, label in [(4, "年报"), (4, "一季报"), (8, "中报"), (10, "三季报")]:
        event_date = Date(today.year if today.month < month else today.year, month, 30)
        if event_date < today:
            event_date = Date(today.year + 1, month, 30)
        events.append({
            "date": event_date.isoformat(),
            "event": f"{label}披露截止",
            "category": "财报季",
            "impact": "高",
            "note": "届时关注业绩是否超预期",
        })

    # StockPool 纳入提示
    if pool_status and pool_status.get("in_pool"):
        events.append({
            "date": (today + timedelta(days=7)).isoformat(),
            "event": f"关注 {pool_status.get('concept_name', '')} 板块持续性",
            "category": "板块跟踪",
            "impact": "中",
            "note": "若板块热度持续，个股有望获得资金青睐",
        })

    return sorted(events, key=lambda x: x["date"])[:6]


def _build_risk_matrix(latest_basic: Optional[dict], ma_state: str) -> list[dict]:
    """
    风险矩阵：列举常见风险项。

    V1.1 阶段基于已知数据推断，
    后续由 Critic Agent 动态生成个性化风险。
    """
    risks = []
    if latest_basic:
        pe = latest_basic.get("pe_ttm") or latest_basic.get("pe")
        if pe is not None and pe > 60:
            risks.append({
                "risk": "估值偏高",
                "probability": "中",
                "severity": "高",
                "description": f"PE_TTM={pe:.1f}，当前股价已反映较高增长预期",
            })
    if ma_state == "多头排列":
        risks.append({
            "risk": "技术性回调风险",
            "probability": "中",
            "severity": "中",
            "description": "均线多头排列后积累较多获利盘，注意短线回调压力",
        })
    if not risks:
        risks.append({
            "risk": "市场系统性风险",
            "probability": "低",
            "severity": "高",
            "description": "市场整体大幅调整可能拖累个股表现",
        })
    return risks


def _build_tracking_indicators(daily_data: list[dict]) -> list[dict]:
    """
    跟踪指标清单：基于近期行情数据生成量化跟踪项。

    V1.1 基于技术面，后续叠加基本面/研报数据。
    """
    indicators = []
    if not daily_data or len(daily_data) < 20:
        return [{
            "indicator": "近期行情数据不足",
            "current": "数据不足",
            "target": "积累20个交易日数据",
            "status": "待补充",
        }]

    recent = daily_data[-20:]
    closes = [d.get("close", 0) or 0 for d in recent]
    vols = [d.get("vol", 0) or 0 for d in recent]

    # 5日均线偏离度
    ma5 = sum(closes[-5:]) / 5
    ma20 = sum(closes) / 20
    latest_close = closes[-1] if closes else 0
    deviation = (latest_close - ma20) / ma20 * 100 if ma20 else 0
    indicators.append({
        "indicator": "MA5相对MA20偏离度",
        "current": f"{deviation:.1f}%",
        "target": "±10%以内为健康范围",
        "status": "强势" if deviation > 10 else ("弱势" if deviation < -10 else "正常"),
    })

    # 量价配合
    avg_vol_5d = sum(vols[-5:]) / 5
    avg_vol_20d = sum(vols) / 20
    vol_ratio = avg_vol_5d / avg_vol_20d if avg_vol_20d else 0
    indicators.append({
        "indicator": "量价配合（5日均量/20日均量）",
        "current": f"{vol_ratio:.2f}x",
        "target": ">1.5x 为放量，<0.7x 为缩量",
        "status": "放量" if vol_ratio > 1.5 else ("缩量" if vol_ratio < 0.7 else "正常"),
    })

    # 近5日涨跌
    pct_5d = (closes[-1] - closes[-6]) / closes[-6] * 100 if len(closes) >= 6 and closes[-6] else 0
    indicators.append({
        "indicator": "近5日涨跌幅",
        "current": f"{pct_5d:+.1f}%",
        "target": "趋势延续需日均涨幅>0",
        "status": "上涨" if pct_5d > 0 else "下跌",
    })
    return indicators


def _date_str(val) -> Optional[str]:
    if val is None:
        return None
    if hasattr(val, "isoformat"):
        return val.isoformat()
    return str(val)

