"""
K线与技术指标 Tool — 本地数据库版

数据来源：PostgreSQL（KlineService）→ 定时任务写入
"""
import datetime as _dt
import logging
from typing import Annotated

import numpy as np
from langchain_core.tools import tool

from app.reasoning.tools._async_runner import run_async

logger = logging.getLogger(__name__)


@tool("get_kline")
def get_kline(
    ts_code: Annotated[str, "股票代码，如 300308.SZ"],
    start_date: Annotated[str, "开始日期，格式YYYYMMDD，如20240101"] = "",
    end_date: Annotated[str, "结束日期，格式YYYYMMDD，如20241231"] = "",
    freq: Annotated[str, "K线周期：D=日,W=周,M=月。默认D"] = "D",
    indicators: Annotated[list[str], "技术指标列表，如['MACD','RSI','BOLL']。默认只返回价格统计。"] = None,
) -> str:
    """获取股票的K线数据和技术指标。输入股票代码、日期范围和K线周期，返回价格走势、成交量及MACD/RSI/BOLL等技术指标，用于判断技术面趋势。"""
    return run_async(_fetch_kline(ts_code, start_date, end_date, freq, indicators or []))


async def _fetch_kline(ts_code: str, start_date: str, end_date: str, freq: str, indicators: list[str]) -> str:
    """从本地数据库读取 K线数据"""
    if not start_date:
        end = _dt.datetime.now()
        start = end - _dt.timedelta(days=180)
        start_date = start.strftime("%Y%m%d")
    if not end_date:
        end_date = _dt.datetime.now().strftime("%Y%m%d")

    try:
        from app.data_pipeline.services.kline_service import get_kline_service
        service = get_kline_service()
        frequency = {"D": "d", "W": "w", "M": "m"}.get(freq.upper(), "d")
        rows = await service.get_stock_kline(ts_code, start_date, end_date, frequency)
        if rows:
            return _format_kline(ts_code, start_date, end_date, freq, rows, indicators)
    except Exception as e:
        logger.warning(f"[KlineTool] 本地查询失败 {ts_code}: {e}")

    return f"未获取到股票 {ts_code} 的K线数据（{start_date}~{end_date}）。本地数据库可能尚未同步数据，请稍后再试。"


def _format_kline(ts_code: str, start_date: str, end_date: str, freq: str, rows: list[dict], indicators: list[str]) -> str:
    """格式化 K线数据输出"""
    if not rows:
        return f"未获取到股票 {ts_code} 的K线数据（{start_date}~{end_date}）。"

    latest = rows[-1]
    freq_label = {"d": "日", "w": "周", "m": "月"}.get(freq.lower(), freq)
    stats = (
        f"股票 {ts_code} K线（{start_date}~{end_date}，{freq_label}线，共{len(rows)}条）：\n"
        f"- 最新价：{latest.get('close', 0):.2f}（{'↑' if latest.get('pct_chg', 0) >= 0 else '↓'}{abs(latest.get('pct_chg', 0)):.2f}%）\n"
        f"- 成交量：{latest.get('volume', 0):,.0f}手\n"
        f"- 区间最高：{max(r.get('high', 0) for r in rows):.2f}，最低：{min(r.get('low', 0) for r in rows):.2f}\n"
    )
    if indicators:
        stats += _compute_indicators(rows, indicators)
    return stats


def _compute_indicators(rows: list[dict], indicators: list[str]) -> str:
    closes = np.array([r["close"] for r in rows], dtype=float)
    lines = ["\n**技术指标：**\n"]

    if "MACD" in indicators:
        try:
            ema12 = _ema(closes, 12)
            ema26 = _ema(closes, 26)
            macd = ema12 - ema26
            signal = _ema(macd, 9)
            hist = macd - signal
            lines.append(f"- MACD：{macd[-1]:.3f}，Signal：{signal[-1]:.3f}，Histogram：{hist[-1]:.3f}\n")
        except Exception:
            lines.append("- MACD：计算失败\n")

    if "RSI" in indicators:
        try:
            deltas = np.diff(closes, prepend=closes[0])
            gains = np.where(deltas > 0, deltas, 0.0)
            losses = np.where(deltas < 0, -deltas, 0.0)
            avg_gain = _ema(gains, 14)
            avg_loss = _ema(losses, 14)
            rs = avg_gain / np.where(avg_loss == 0, np.nan, avg_loss)
            rsi = 100 - (100 / (1 + rs))
            lines.append(f"- RSI(14)：{rsi[-1]:.1f}\n")
        except Exception:
            lines.append("- RSI：计算失败\n")

    if "BOLL" in indicators:
        try:
            mb = _sma(closes, 20)
            std = _std(closes, 20)
            lines.append(f"- BOLL(20)：上={mb[-1] + 2*std[-1]:.2f}，中={mb[-1]:.2f}，下={mb[-1] - 2*std[-1]:.2f}\n")
        except Exception:
            lines.append("- BOLL：计算失败\n")

    if "MA" in indicators:
        for window in [5, 10, 20, 60]:
            if len(closes) >= window:
                ma = _sma(closes, window)
                lines.append(f"- MA({window})：{ma[-1]:.2f}\n")

    return "".join(lines)


def _ema(data: np.ndarray, span: int) -> np.ndarray:
    alpha = 2.0 / (span + 1)
    ema = np.empty_like(data)
    ema[0] = data[0]
    for i in range(1, len(data)):
        ema[i] = alpha * data[i] + (1 - alpha) * ema[i - 1]
    return ema


def _sma(data: np.ndarray, window: int) -> np.ndarray:
    sma = np.empty_like(data)
    sma[:window - 1] = np.nan
    for i in range(window - 1, len(data)):
        sma[i] = np.mean(data[i - window + 1:i + 1])
    return sma


def _std(data: np.ndarray, window: int) -> np.ndarray:
    std_arr = np.empty_like(data)
    std_arr[:window - 1] = np.nan
    for i in range(window - 1, len(data)):
        std_arr[i] = np.std(data[i - window + 1:i + 1])
    return std_arr
