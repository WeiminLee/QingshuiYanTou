"""海外行情抓取（美股 / 台股 / 韩股）。

数据源：Yahoo Finance chart API。chemagent 容器可直连
``query1.finance.yahoo.com``；如后续网络收紧，可把
``OVERSEAS_RELAY_PREFIX`` 设为 ``https://r.jina.ai/`` 走中转。

落库复用现有表：
- ``stocks``：ts_code/symbol 用 Yahoo 符号（NVDA、2330.TW、005930.KS），
  market=US/TW/KR，area=美国/台湾/韩国。
- ``daily_data``：日线 OHLCV，pre_close/pct_chg 由序列推导。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text

from app.core.database import engine
from app.data_pipeline.overseas_universe import MARKET_AREA, universe_for

logger = logging.getLogger(__name__)

YAHOO_BASE = os.getenv("OVERSEAS_YAHOO_BASE", "https://query1.finance.yahoo.com")
RELAY_PREFIX = os.getenv("OVERSEAS_RELAY_PREFIX", "")
REQUEST_TIMEOUT = int(os.getenv("OVERSEAS_REQUEST_TIMEOUT", "40"))
SLEEP_BETWEEN_SYMBOLS = float(os.getenv("OVERSEAS_SLEEP", "1"))
MAX_RETRIES = 5


def _chart_url(symbol: str, range_: str) -> str:
    path = (
        f"/v8/finance/chart/{symbol}"
        f"?range={range_}&interval=1d&includePrePost=false&events=div%2Csplits"
    )
    return f"{RELAY_PREFIX}{YAHOO_BASE}{path}" if RELAY_PREFIX else f"{YAHOO_BASE}{path}"


def _extract_json(text_body: str) -> dict[str, Any]:
    """r.jina.ai 会在 JSON 前加 Title/URL/Markdown 头，截取第一个 {"chart"。"""
    idx = text_body.find('{"chart"')
    if idx < 0:
        # 兼容直连（无 markdown 头）
        idx = text_body.find("{")
    if idx < 0:
        raise ValueError("response is not json")
    return json.loads(text_body[idx:])


def parse_chart(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Yahoo chart JSON → daily bars（asc，已推导 pre_close/pct_chg）。"""
    chart = payload.get("chart") or {}
    if chart.get("error"):
        raise ValueError(f"yahoo error: {chart['error']}")
    results = chart.get("result") or []
    if not results:
        return []
    result = results[0]
    timestamps = result.get("timestamp") or []
    quotes = (result.get("indicators", {}).get("quote") or [{}])[0]
    opens = quotes.get("open") or []
    highs = quotes.get("high") or []
    lows = quotes.get("low") or []
    closes = quotes.get("close") or []
    volumes = quotes.get("volume") or []

    bars: list[dict[str, Any]] = []
    prev_close: float | None = None
    for i, ts in enumerate(timestamps):
        close = closes[i] if i < len(closes) else None
        if close is None:
            continue
        trade_date = datetime.fromtimestamp(int(ts), tz=UTC).date()
        open_ = opens[i] if i < len(opens) else None
        high = highs[i] if i < len(highs) else None
        low = lows[i] if i < len(lows) else None
        vol = volumes[i] if i < len(volumes) else None
        change = None if prev_close is None else close - prev_close
        pct_chg = None if not prev_close else round((close - prev_close) / prev_close * 100, 4)
        bars.append(
            {
                "trade_date": trade_date,
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "pre_close": prev_close,
                "change": change,
                "pct_chg": pct_chg,
                "vol": vol,
            }
        )
        prev_close = close
    return bars


def _fetch_sync(symbol: str, range_: str) -> dict[str, Any]:
    from urllib.request import Request, urlopen

    url = _chart_url(symbol, range_)
    last_exc: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            req = Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
            with urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                body = resp.read().decode("utf-8", "replace")
            return _extract_json(body)
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"fetch {symbol} failed: {last_exc}")


async def _fetch(symbol: str, range_: str) -> dict[str, Any]:
    return await asyncio.to_thread(_fetch_sync, symbol, range_)


async def _upsert(symbol: str, name: str, industry: str, market: str, payload: dict[str, Any]) -> int:
    bars = parse_chart(payload)
    if not bars:
        return 0

    meta = payload["chart"]["result"][0].get("meta") or {}
    list_date = None
    first_trade = meta.get("firstTradeDate")
    if first_trade:
        list_date = datetime.fromtimestamp(int(first_trade), tz=UTC).date()

    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO stocks (ts_code, symbol, name, area, industry, market, list_date)
                VALUES (:ts_code, :symbol, :name, :area, :industry, :market, :list_date)
                ON CONFLICT (ts_code) DO UPDATE SET
                    symbol = EXCLUDED.symbol,
                    name = EXCLUDED.name,
                    area = EXCLUDED.area,
                    industry = EXCLUDED.industry,
                    market = EXCLUDED.market,
                    list_date = COALESCE(EXCLUDED.list_date, stocks.list_date)
                """
            ),
            [
                {
                    "ts_code": symbol,
                    "symbol": symbol,
                    "name": name,
                    "area": MARKET_AREA.get(market, market),
                    "industry": industry,
                    "market": market,
                    "list_date": list_date,
                }
            ],
        )

        for start in range(0, len(bars), 500):
            chunk = bars[start : start + 500]
            await conn.execute(
                text(
                    """
                    INSERT INTO daily_data (
                        ts_code, trade_date, open, high, low, close,
                        pre_close, change, pct_chg, vol, amount, is_suspended
                    )
                    VALUES (
                        :ts_code, :trade_date, :open, :high, :low, :close,
                        :pre_close, :change, :pct_chg, :vol, NULL, false
                    )
                    ON CONFLICT (ts_code, trade_date) DO UPDATE SET
                        open = EXCLUDED.open,
                        high = EXCLUDED.high,
                        low = EXCLUDED.low,
                        close = EXCLUDED.close,
                        pre_close = COALESCE(EXCLUDED.pre_close, daily_data.pre_close),
                        change = COALESCE(EXCLUDED.change, daily_data.change),
                        pct_chg = COALESCE(EXCLUDED.pct_chg, daily_data.pct_chg),
                        vol = COALESCE(EXCLUDED.vol, daily_data.vol)
                    """
                ),
                [{"ts_code": symbol, **bar} for bar in chunk],
            )
    return len(bars)


async def sync_markets(markets: list[str] | tuple[str, ...] | None = None, range_: str = "1mo") -> dict[str, Any]:
    """抓取指定市场的核心股日线并落库。

    Returns:
        {"symbols": n, "bars": n, "errors": [{"symbol":..., "error":...}], "markets": {...}}
    """
    rows = universe_for(markets)
    logger.info("[overseas] start markets=%s symbols=%d range=%s", markets, len(rows), range_)
    total_bars = 0
    errors: list[dict[str, str]] = []
    per_market: dict[str, int] = {}
    for symbol, name, industry, market in rows:
        try:
            payload = await _fetch(symbol, range_)
            n = await _upsert(symbol, name, industry, market, payload)
            total_bars += n
            per_market[market] = per_market.get(market, 0) + n
            logger.info("[overseas] %s %s bars=%d", market, symbol, n)
        except Exception as exc:  # noqa: BLE001
            errors.append({"symbol": symbol, "error": str(exc)[:200]})
            logger.warning("[overseas] %s %s failed: %s", market, symbol, exc)
        await asyncio.sleep(SLEEP_BETWEEN_SYMBOLS)

    summary = {
        "symbols": len(rows) - len(errors),
        "failed": len(errors),
        "bars": total_bars,
        "markets": per_market,
        "errors": errors,
    }
    logger.info("[overseas] done %s", {k: v for k, v in summary.items() if k != "errors"})
    return summary
