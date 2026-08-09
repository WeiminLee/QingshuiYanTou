"""K 线数据源 provider 协议、标准化及 fallback registry。

Task 1: 建立 K 线标准 provider 协议和 fallback registry

设计：
- ``StockKlineProvider`` Protocol：所有 provider 必须实现的接口
- ``KlineProviderResult``：不可变结果 dataclass，含 records、source、fallback_used、errors
- ``normalize_kline_record()``：标准化原始记录字段名和数值类型
- ``KlineProviderRegistry``：按配置顺序调用 provider，失败自动 fallback
- ``BaostockKlineProvider``：基于 ``DataSourceClient.get_stock_kline()`` 的适配器
- ``EfinanceKlineProvider`` / ``AkshareKlineProvider``：可选源，仅在对应库可导入时注册
- ``create_default_registry()``：工厂函数，组装默认 provider 链
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, List, Optional, Protocol, runtime_checkable

from app.data_pipeline.data_source import DataSourceClient

logger = logging.getLogger(__name__)

# =========================================================================
# 标准 K 线记录字段名
# =========================================================================

STANDARD_KEYS = [
    "date",
    "code",
    "open",
    "high",
    "low",
    "close",
    "preclose",
    "volume",
    "amount",
    "pctChg",
    "tradestatus",
]

# 需要转为 float 的数值字段
_FLOAT_FIELDS = {"open", "high", "low", "close", "preclose", "amount", "pctChg"}

# 需要转为 int 的字段
_INT_FIELDS = {"volume"}


# =========================================================================
# 类型转换工具
# =========================================================================


def _safe_float(val: Any) -> Optional[float]:
    """安全转换为浮点数，空值/NaN 返回 None。"""
    if val is None:
        return None
    try:
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


def _safe_int(val: Any) -> Optional[int]:
    """安全转换为整数，空值/NaN 返回 None。"""
    f = _safe_float(val)
    if f is not None:
        return int(f)
    return None


def _safe_str(val: Any) -> str:
    """安全转字符串。"""
    if val is None:
        return ""
    return str(val)


# =========================================================================
# Provider 协议
# =========================================================================


@runtime_checkable
class StockKlineProvider(Protocol):
    """K 线数据源 provider 协议。

    所有 provider 必须实现此接口。
    """

    name: str

    def fetch_stock_kline(
        self,
        ts_code: str,
        start_date: str,
        end_date: str,
        adjustflag: str = "3",
    ) -> list[dict[str, Any]]:
        """获取个股日线 K 线数据。

        Args:
            ts_code: 股票代码，如 "600000.SH" / "000001.SZ"
            start_date: 开始日期 "YYYYMMDD"
            end_date: 结束日期 "YYYYMMDD"
            adjustflag: "1" 后复权 / "2" 前复权 / "3" 不复权（默认）

        Returns:
            list[dict] — 原始记录列表，字段因 provider 可能不同。
            失败时抛出异常，调用方通过 Registry 处理 fallback。

        Raises:
            RuntimeError: 网络/API 错误
            ValueError: 无效参数
        """
        ...


# =========================================================================
# 标准化结果
# =========================================================================


@dataclass(frozen=True)
class KlineProviderResult:
    """Provider 执行结果（不可变）。

    Attributes:
        records: 标准化后的 K 线记录列表
        source: 成功返回数据的数据源名称（空字符串表示全部失败）
        fallback_used: 是否使用了 fallback 数据源
        errors: 各 provider 的错误信息列表
    """

    records: List[dict[str, Any]]
    source: str
    fallback_used: bool
    errors: List[dict[str, str]] = field(default_factory=list)


# =========================================================================
# 记录标准化
# =========================================================================


def normalize_kline_record(
    raw: dict[str, Any],
    ts_code: str,
) -> dict[str, Any]:
    """标准化原始 K 线记录。

    将原始记录的字段映射到标准字段名，并对数值字段进行类型转换。
    缺失字段保留为 None，但 ``STANDARD_KEYS`` 中列出的所有字段都会出现在结果中。

    Args:
        raw: 原始记录 dict
        ts_code: 标准股票代码（如 "600000.SH"）

    Returns:
        标准化后的记录 dict，包含 ``STANDARD_KEYS`` 中所有字段。
    """
    result: dict[str, Any] = {}

    # 日期 — 保留原始字符串
    result["date"] = _safe_str(raw.get("date"))

    # 代码 — 写入标准格式
    result["code"] = ts_code

    # 浮点数值字段
    for field in _FLOAT_FIELDS:
        raw_val = raw.get(field)
        result[field] = _safe_float(raw_val)

    # 整数字段
    for field in _INT_FIELDS:
        raw_val = raw.get(field)
        result[field] = _safe_int(raw_val)

    # 字符串字段（tradestatus）
    result["tradestatus"] = _safe_str(raw.get("tradestatus"))

    return result


# =========================================================================
# Provider Registry
# =========================================================================


def _validate_ts_code(ts_code: str) -> Optional[str]:
    """校验股票代码格式，无效时返回错误描述。

    接受格式：600000.SH / 000001.SZ / 600000（裸数字按 6 开头视作沪市）
    """
    if not ts_code or not ts_code.strip():
        return "ts_code 不能为空"

    code = ts_code.strip()
    if "." in code:
        parts = code.split(".")
        if len(parts) != 2:
            return f"无效的股票代码格式: {ts_code}"
        num, exchange = parts
        if exchange.upper() not in ("SH", "SZ"):
            return f"不支持的交易所代码: {exchange}"
        if len(num) != 6 or not num.isdigit():
            return f"无效的股票代码数字部分: {num}"
        return None

    if len(code) != 6 or not code.isdigit():
        return f"无效的股票代码: {ts_code}（应为 6 位数字或含 .SH/.SZ 后缀）"
    return None


class KlineProviderRegistry:
    """K 线 provider 注册表，按配置顺序调用 provider 并实现 fallback。

    职责：
    - 按顺序调用已注册的 provider
    - 当前 provider 失败（异常或空结果）时自动切换到下一个
    - 收集所有 provider 的错误信息
    - 返回标准化的 KlineProviderResult
    """

    def __init__(self, providers: Optional[List[StockKlineProvider]] = None):
        self.providers: list[StockKlineProvider] = list(providers or [])

    def fetch_stock_kline(
        self,
        ts_code: str,
        start_date: str,
        end_date: str,
        adjustflag: str = "3",
    ) -> KlineProviderResult:
        """按 provider 顺序获取 K 线数据，自动 fallback。

        Args:
            ts_code: 股票代码，如 "600000.SH" / "000001.SZ"
            start_date: 开始日期 "YYYYMMDD"
            end_date: 结束日期 "YYYYMMDD"
            adjustflag: "1" 后复权 / "2" 前复权 / "3" 不复权（默认）

        Returns:
            KlineProviderResult — 包含标准化记录、数据源名称、fallback 标志和错误列表。
        """
        errors: list[dict[str, str]] = []
        total_providers = len(self.providers)

        if total_providers == 0:
            return KlineProviderResult(
                records=[],
                source="",
                fallback_used=False,
                errors=[{"provider": "registry", "error": "no providers registered"}],
            )

        # 校验代码格式（不调用 provider）
        validation_error = _validate_ts_code(ts_code)
        if validation_error:
            return KlineProviderResult(
                records=[],
                source="",
                fallback_used=False,
                errors=[{"provider": "registry", "error": validation_error}],
            )

        for idx, provider in enumerate(self.providers):
            try:
                raw_records = provider.fetch_stock_kline(
                    ts_code, start_date, end_date, adjustflag=adjustflag
                )

                if not raw_records:
                    # 空结果视为失败，继续 fallback
                    errors.append(
                        {
                            "provider": provider.name,
                            "error": "empty result",
                        }
                    )
                    logger.info(
                        "[%s] %s 返回空结果，继续 fallback",
                        provider.name,
                        ts_code,
                    )
                    continue

                # 标准化所有记录
                normalized = [normalize_kline_record(r, ts_code) for r in raw_records]

                # 成功 — 返回结果
                return KlineProviderResult(
                    records=normalized,
                    source=provider.name,
                    fallback_used=idx > 0,
                    errors=errors,
                )

            except (RuntimeError, ValueError) as e:
                errors.append(
                    {
                        "provider": provider.name,
                        "error": str(e),
                    }
                )
                logger.info(
                    "[%s] %s 失败: %s，%s",
                    provider.name,
                    ts_code,
                    e,
                    "继续 fallback" if idx + 1 < total_providers else "无更多 provider",
                )
                continue

        # 所有 provider 均失败
        return KlineProviderResult(
            records=[],
            source="",
            fallback_used=True,
            errors=errors,
        )


# =========================================================================
# Baostock 适配器
# =========================================================================


class BaostockKlineProvider:
    """基于 baostock 的 K 线 provider 适配器。

    封装 ``DataSourceClient.get_stock_kline()``，调用时传入
    ``raise_on_error=True`` 以确保异常被正确传播到 registry。
    """

    name = "baostock"

    def __init__(self, client: Optional[DataSourceClient] = None):
        self._client = client or DataSourceClient()

    def fetch_stock_kline(
        self,
        ts_code: str,
        start_date: str,
        end_date: str,
        adjustflag: str = "3",
    ) -> list[dict[str, Any]]:
        return self._client.get_stock_kline(
            ts_code,
            start_date,
            end_date,
            adjustflag=adjustflag,
            raise_on_error=True,
        )


# =========================================================================
# 可选 Provider（efinance / akshare）
# =========================================================================


class _LazyEfinanceKlineProvider:
    """efinance K 线 provider（懒加载，仅在 efinance 可导入时创建）。"""

    name = "efinance"
    _dependency = "efinance"

    def __init__(self, client: Optional[Any] = None):
        self._client = client

    def fetch_stock_kline(
        self,
        ts_code: str,
        start_date: str,
        end_date: str,
        adjustflag: str = "3",
    ) -> list[dict[str, Any]]:
        try:
            import efinance as ef
        except ImportError:
            raise RuntimeError("efinance not installed")

        try:
            numeric = "".join(filter(str.isdigit, ts_code))
            df = ef.stock.get_quote_history(numeric)
            if df is None or len(df) == 0:
                return []
            records: list[dict[str, Any]] = []
            for _, row in df.iterrows():
                records.append(
                    {
                        "date": str(row.get("日期", "")),
                        "code": ts_code,
                        "open": row.get("开盘"),
                        "high": row.get("最高"),
                        "low": row.get("最低"),
                        "close": row.get("收盘"),
                        "preclose": row.get("昨收"),
                        "volume": row.get("成交量"),
                        "amount": row.get("成交额"),
                        "pctChg": row.get("涨跌幅"),
                        "tradestatus": "1",
                    }
                )
            return records
        except Exception as e:
            raise RuntimeError(f"efinance fetch failed: {e}")


class _LazyAkshareKlineProvider:
    """akshare K 线 provider（懒加载，仅在 akshare 可导入时创建）。"""

    name = "akshare"
    _dependency = "akshare"

    def __init__(self, client: Optional[Any] = None):
        self._client = client

    def fetch_stock_kline(
        self,
        ts_code: str,
        start_date: str,
        end_date: str,
        adjustflag: str = "3",
    ) -> list[dict[str, Any]]:
        try:
            import akshare as ak
        except ImportError:
            raise RuntimeError("akshare not installed")

        try:
            numeric = "".join(filter(str.isdigit, ts_code))
            df = ak.stock_zh_a_hist(
                symbol=numeric,
                period="daily",
                start_date=start_date,
                end_date=end_date,
                adjust="qfq" if adjustflag == "2" else "",
            )
            if df is None or len(df) == 0:
                return []
            records: list[dict[str, Any]] = []
            for _, row in df.iterrows():
                records.append(
                    {
                        "date": str(row.get("日期", "")),
                        "code": ts_code,
                        "open": row.get("开盘"),
                        "high": row.get("最高"),
                        "low": row.get("最低"),
                        "close": row.get("收盘"),
                        "preclose": row.get("昨收"),
                        "volume": row.get("成交量"),
                        "amount": row.get("成交额"),
                        "pctChg": row.get("涨跌幅"),
                        "tradestatus": "1",
                    }
                )
            return records
        except Exception as e:
            raise RuntimeError(f"akshare fetch failed: {e}")


# =========================================================================
# 工厂函数
# =========================================================================


def _try_import_optional_provider(
    provider_cls: type,
    client: Optional[Any] = None,
) -> Optional[StockKlineProvider]:
    """尝试导入可选 provider 的依赖库，成功则返回实例。

    Args:
        provider_cls: provider 类（如 ``_LazyEfinanceKlineProvider``）
        client: 可选的已初始化 client 实例

    Returns:
        provider 实例或 None（依赖不可用时）
    """
    dep_name = getattr(provider_cls, "_dependency", "")
    if dep_name:
        try:
            __import__(dep_name)
        except ImportError:
            logger.debug("可选 provider %s 跳过（依赖 %s 未安装）", provider_cls.__name__, dep_name)
            return None

    return provider_cls(client=client)


def create_default_registry(
    client: Optional[DataSourceClient] = None,
) -> KlineProviderRegistry:
    """创建默认 provider registry。

    Args:
        client: 可选的 ``DataSourceClient`` 实例（测试时注入 mock）

    Returns:
        配置好默认 provider 链的 ``KlineProviderRegistry`` 实例。
    """
    providers: list[StockKlineProvider] = []

    # 1. Baostock（始终可用）
    providers.append(BaostockKlineProvider(client=client or DataSourceClient()))

    # 2. Efinance（可选）
    efinance = _try_import_optional_provider(_LazyEfinanceKlineProvider, client=client)
    if efinance is not None:
        providers.append(efinance)

    # 3. Akshare（可选）
    akshare = _try_import_optional_provider(_LazyAkshareKlineProvider, client=client)
    if akshare is not None:
        providers.append(akshare)

    return KlineProviderRegistry(providers=providers)