"""
DataSourceClient - 数据源客户端

封装 akshare + baostock 数据源，提供统一的数据获取接口。
迁移自 data_access_mvp/src/core/data_source.py
"""
import random
import time
import logging
from datetime import datetime
from typing import Any, Optional

import akshare as ak
import baostock as bs
import pandas as pd

logger = logging.getLogger(__name__)


def _is_null(val) -> bool:
    """判断值是否为空（None / pandas NaN / 字符串 nan/nat/none/null）"""
    if val is None:
        return True
    try:
        if pd.isna(val):
            return True
    except (TypeError, ValueError):
        pass
    if isinstance(val, str):
        return val.strip().lower() in ("", "nan", "nat", "none", "null")
    return False


def _safe_str(val) -> str:
    """安全转字符串，空值转空字符串"""
    if _is_null(val):
        return ""
    if hasattr(val, "date") and hasattr(val, "hour"):
        try:
            return val.strftime("%Y%m%d")
        except Exception:
            return ""
    return str(val)


def _safe_str_full(val) -> str:
    """安全转完整字符串（保留时间），空值转空字符串"""
    if _is_null(val):
        return ""
    if hasattr(val, "date") and hasattr(val, "hour"):
        try:
            return val.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return ""
    return str(val)


def _normalize_ts_code(code: str) -> str:
    """标准化股票代码格式"""
    if not code:
        return ""
    c = code.strip()
    if "." not in c:
        return f"{c}.SH" if c.startswith("6") else f"{c}.SZ"
    prefix, num = c.split(".", 1)
    if prefix.lower() in ("sh", "ss"):
        return f"{num}.SH"
    if prefix.lower() in ("sz",):
        return f"{num}.SZ"
    return c.upper()


def _ts_to_bs(ts_code: str) -> str:
    """项目格式 → baostock 格式（Phase 31 D-A1）。

    "600000.SH" → "sh.600000"
    "000001.SZ" → "sz.000001"
    "600000"    → "sh.600000"（裸数字按 6 开头视作上交所）
    "000001"    → "sz.000001"

    Raises:
        ValueError: 输入既非 6 位数字也不含 .SH/.SZ 后缀
    """
    if not ts_code:
        raise ValueError("ts_code 不能为空")
    code = ts_code.strip()
    if "." in code:
        num, prefix = code.split(".", 1)
        prefix_lower = prefix.lower()
        if prefix_lower not in ("sh", "sz"):
            raise ValueError(f"不支持的交易所前缀: {prefix}")
        if len(num) != 6 or not num.isdigit():
            raise ValueError(f"无效的股票代码: {code}")
        return f"{prefix_lower}.{num}"
    # 裸数字
    if len(code) != 6 or not code.isdigit():
        raise ValueError(f"无效的股票代码: {code}")
    return f"sh.{code}" if code.startswith("6") else f"sz.{code}"


class DataSourceClient:
    """
    统一数据源接口

    数据源：
    - 研报: akshare ak.stock_research_report_em()
    - 股票基本信息: baostock query_stock_basic() + query_stock_industry()
    - 指数K线: baostock query_history_k_data_plus()
    - 互动易（深交所 + 上交所）: akshare
    - 财联社电报: akshare
    """

    def __init__(self):
        self._bs_logged_in = False

    def _bs_login(self):
        """登录 baostock（实例级单次登录）"""
        if not self._bs_logged_in:
            bs.login()
            self._bs_logged_in = True

    def _bs_logout(self):
        """登出 baostock"""
        if self._bs_logged_in:
            bs.logout()
            self._bs_logged_in = False

    def get_reports(
        self,
        trade_date: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: int = 5000,
    ) -> list[dict[str, Any]]:
        """获取券商研报数据（akshare）"""
        try:
            df = ak.stock_research_report_em()
            if df is None or len(df) == 0:
                logger.warning("研报数据为空")
                return []

            records = []
            for _, row in df.iterrows():
                pub_date = _safe_str(row.get("日期"))
                if trade_date and pub_date != trade_date:
                    continue
                if start_date and pub_date < start_date:
                    continue
                if end_date and pub_date > end_date:
                    continue
                ts_code = _normalize_ts_code(str(row.get("股票代码") or ""))
                records.append(
                    {
                        "trade_date": pub_date,
                        "ts_code": ts_code,
                        "name": str(row.get("股票简称") or ""),
                        "title": str(row.get("报告名称") or ""),
                        "inst_csname": str(row.get("机构") or ""),
                        "author": "",
                        "org_code": "",
                        "url": str(row.get("报告PDF链接") or ""),
                        "file_name": "",
                    }
                )

            logger.info(f"获取研报数据: {len(records)} 条")
            return records[:limit]
        except Exception as e:
            logger.error(f"获取研报数据失败: {e}")
            return []

    # 互动易字段映射：深交所 / 上交所列名差异在此集中处理
    _IRM_FIELD_MAP = {
        "SZ": {
            "fetch": "stock_irm_cninfo",
            "question_time": "提问时间",
            "answer_time": "更新时间",
            "question": "问题",
            "answer": "回答内容",
        },
        "SH": {
            "fetch": "stock_sns_sseinfo",
            "question_time": "问题时间",
            "answer_time": "回答时间",
            "question": "问题",
            "answer": "回答",
        },
    }

    def get_irm(self, ts_code: str) -> list[dict[str, Any]]:
        """获取单只股票的互动易 Q&A（深交所 + 上交所）。"""
        numeric = "".join(filter(str.isdigit, ts_code))
        if not numeric:
            return []

        exchange = "SH" if numeric.startswith("6") else "SZ"
        cfg = self._IRM_FIELD_MAP[exchange]

        try:
            fetch_func = getattr(ak, cfg["fetch"])
            df = fetch_func(symbol=numeric)
        except Exception as e:
            logger.warning(f"{exchange} 互动易 {ts_code} 失败: {e}")
            raise

        if df is None or len(df) == 0 or "股票代码" not in df.columns:
            return []

        records: list[dict[str, Any]] = []
        for _, row in df.iterrows():
            answer = _safe_str(row.get(cfg["answer"]))
            if not answer:
                continue
            records.append(
                {
                    "stock_code": _safe_str(row.get("股票代码")),
                    "stock_name": _safe_str(row.get("公司简称")),
                    "question": _safe_str(row.get(cfg["question"])),
                    "answer": answer,
                    "question_time": _safe_str_full(row.get(cfg["question_time"])),
                    "answer_time": _safe_str_full(row.get(cfg["answer_time"])),
                    "exchange": exchange,
                }
            )
        return records

    def get_cls_telegraph(self, symbol: str = "全部") -> list[dict[str, Any]]:
        """获取财联社电报（akshare）"""
        try:
            df = ak.stock_info_global_cls(symbol=symbol)
            if df is None or len(df) == 0 or "标题" not in df.columns:
                return []
            records = []
            for _, row in df.iterrows():
                records.append(
                    {
                        "title": _safe_str(row.get("标题")),
                        "content": _safe_str(row.get("内容")),
                        "pub_date": _safe_str(row.get("发布日期")),
                        "pub_time": _safe_str(row.get("发布时间")),
                    }
                )
            return records
        except Exception as e:
            logger.warning("获取财联社电报失败: %s", e)
            return []

    def get_all_stock_codes(self) -> list[str]:
        """获取所有股票代码"""
        try:
            self._bs_login()
            rs = bs.query_stock_basic(code="")
            codes = []
            while rs.error_code == "0" and rs.next():
                codes.append(rs.get_row_data()[0])
            return codes
        except Exception as e:
            logger.error(f"获取股票代码列表失败: {e}")
            return []

    def get_stocks_basic(self, list_status: str = "L") -> list[dict[str, Any]]:
        """
        获取股票基本信息（baostock）。

        Args:
            list_status: L=上市中, D=退市, A=全部
        """
        try:
            self._bs_login()
            basic_data: dict[str, dict[str, Any]] = {}
            rs = bs.query_stock_basic(code="")
            # baostock row 顺序: [code, code_name, ipoDate, outDate, type, status]
            while rs.error_code == "0" and rs.next():
                row = rs.get_row_data()
                code = row[0]
                ipo_date = row[2] if len(row) > 2 else ""
                out_date = row[3] if len(row) > 3 else ""
                security_type = row[4] if len(row) > 4 else ""
                status = row[5] if len(row) > 5 else ""

                if security_type != "1":
                    continue
                if list_status == "L" and status != "1":
                    continue
                if list_status == "D" and status == "1":
                    continue

                basic_data[code] = {
                    "ts_code": _normalize_ts_code(code),
                    "name": row[1],
                    "area": "",
                    "industry": "",
                    "list_date": _safe_str(ipo_date),
                    "delist_date": _safe_str(out_date),
                    "status": status,
                    "is_hs": "",
                }

            rs2 = bs.query_stock_industry()
            while rs2.error_code == "0" and rs2.next():
                row = rs2.get_row_data()
                code = row[0]
                if code in basic_data and len(row) > 2:
                    basic_data[code]["industry"] = row[2]

            stocks = list(basic_data.values())
            logger.info(f"获取股票基本信息: {len(stocks)} 条 (status={list_status})")
            return stocks
        except Exception as e:
            logger.error(f"获取股票基本信息失败: {e}")
            return []

    def get_index_kline(
        self,
        index_code: str,
        start_date: str,
        end_date: str,
        frequency: str = "d",
        adjustflag: str = "3",
    ) -> list[dict[str, Any]]:
        """获取指数历史K线数据（baostock）"""
        try:
            self._bs_login()
            fields = "date,code,open,high,low,close,preclose,volume,amount,turn,pctChg"
            sd = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}"
            ed = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}"
            rs = bs.query_history_k_data_plus(
                index_code,
                fields,
                start_date=sd,
                end_date=ed,
                frequency=frequency,
                adjustflag=adjustflag,
            )
            records = []
            while rs.error_code == "0" and rs.next():
                row = rs.get_row_data()
                records.append(
                    {
                        "date": row[0],
                        "code": row[1],
                        "open": row[2],
                        "high": row[3],
                        "low": row[4],
                        "close": row[5],
                        "preclose": row[6],
                        "volume": row[7],
                        "amount": row[8],
                        "turn": row[9],
                        "pctChg": row[10],
                    }
                )
            return records
        except Exception as e:
            logger.error(f"获取指数K线失败: {e}")
            return []

    def get_stock_kline(
        self,
        ts_code: str,
        start_date: str,
        end_date: str,
        adjustflag: str = "3",
        raise_on_error: bool = False,
    ) -> list[dict[str, Any]]:
        """获取个股历史日线 K 线（baostock，Phase 31 D-A1）。

        Args:
            ts_code: 项目格式 "600000.SH" / "000001.SZ" / "600000"
            start_date: "YYYYMMDD"
            end_date: "YYYYMMDD"
            adjustflag: "1" 后复权 / "2" 前复权 / "3" 不复权（默认）

        Returns:
            list of dict，字段：date, code, open, high, low, close, preclose,
            volume, amount, turn, pctChg, tradestatus, isST。失败返回 []。
        """
        try:
            bs_code = _ts_to_bs(ts_code)
        except ValueError as e:
            logger.warning("baostock ts_code 转换失败 %s: %s", ts_code, e)
            if raise_on_error:
                raise
            return []

        try:
            self._bs_login()
            fields = "date,code,open,high,low,close,preclose,volume,amount,turn,pctChg,tradestatus,isST"
            sd = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}"
            ed = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}"
            rs = bs.query_history_k_data_plus(
                bs_code,
                fields,
                start_date=sd,
                end_date=ed,
                frequency="d",
                adjustflag=adjustflag,
            )
            records: list[dict[str, Any]] = []
            while rs.error_code == "0" and rs.next():
                row = rs.get_row_data()
                records.append({
                    "date": row[0],
                    "code": row[1],
                    "open": row[2],
                    "high": row[3],
                    "low": row[4],
                    "close": row[5],
                    "preclose": row[6],
                    "volume": row[7],
                    "amount": row[8],
                    "turn": row[9],
                    "pctChg": row[10],
                    "tradestatus": row[11],
                    "isST": row[12],
                })
            if rs.error_code != "0":
                message = f"baostock {ts_code} 非零返回: {rs.error_code} {rs.error_msg}"
                if raise_on_error:
                    raise RuntimeError(message)
                logger.warning(message)
            return records
        except RuntimeError as e:
            if raise_on_error:
                raise
            logger.warning("获取个股K线 %s 失败: %s", ts_code, e)
            return []
        except Exception as e:
            logger.warning("获取个股K线 %s 失败: %s", ts_code, e)
            if raise_on_error:
                raise
            return []

    def get_adjust_factor(
        self,
        ts_code: str,
        start_date: str = "2010-01-01",
        end_date: Optional[str] = None,
    ) -> dict[str, float]:
        """
        获取股票复权因子，返回 {date: foreAdjustFactor} 映射（按日期升序）。

        用于计算前复权价格：qfq_price = raw_price × (latest_factor / hist_factor)
        """
        try:
            self._bs_login()
            end = end_date or datetime.now().strftime("%Y-%m-%d")
            rs = bs.query_adjust_factor(ts_code, start_date=start_date, end_date=end)
            factors = {}
            while rs.error_code == "0" and rs.next():
                row = rs.get_row_data()
                factors[row[1]] = float(row[2])
            return factors
        except Exception as e:
            logger.warning(f"获取复权因子 {ts_code} 失败: {e}")
            return {}

    def get_stock_profile(self, ts_code: str) -> dict[str, Any]:
        """
        获取股票主营业务概况（同花顺）。

        Args:
            ts_code: 股票代码，格式 000066 或 000066.SZ 均可

        Returns:
            字段：main_business, product_type, product_name, business_scope
        """
        numeric = "".join(filter(str.isdigit, ts_code))
        if not numeric:
            return {}

        try:
            df = ak.stock_zyjs_ths(symbol=numeric)
            if df is None or len(df) == 0:
                return {}
            row = df.iloc[0]
            return {
                "main_business": _safe_str(row.get("主营业务")),
                "product_type": _safe_str(row.get("产品类型")),
                "product_name": _safe_str(row.get("产品名称")),
                "business_scope": _safe_str(row.get("经营范围")),
            }
        except Exception as e:
            logger.debug(f"获取股票概况 {ts_code} 失败: {e}")
            return {}
