"""
DataSourceClientMinishare — minishare 备选数据源

数据源：
- 研报: pro.research_report(trade_date=) / pro.research_report(ts_code=, start_date=, end_date=)
- 互动易: pro.irm_qa_sh(trade_date=) / pro.irm_qa_sz(trade_date=)
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import minishare as ms
import pandas as pd

from app.config import settings

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


class DataSourceClientMinishare:
    """minishare 备选数据源客户端"""

    def __init__(self) -> None:
        research_token = settings.minishare_research_token
        irm_token = settings.minishare_irm_token

        if not research_token:
            logger.warning("MINISHARE_RESEARCH_TOKEN 未配置，研报数据源不可用")
            self._research_api = None
        else:
            self._research_api = ms.pro_api(research_token)

        if not irm_token:
            logger.warning("MINISHARE_IRM_TOKEN 未配置，互动易数据源不可用")
            self._irm_api = None
        else:
            self._irm_api = ms.pro_api(irm_token)

    @property
    def research_available(self) -> bool:
        return self._research_api is not None

    @property
    def irm_available(self) -> bool:
        return self._irm_api is not None

    def get_reports(
        self,
        trade_date: Optional[str] = None,
        ts_code: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: int = 5000,
    ) -> list[dict[str, Any]]:
        """获取券商研报数据（minishare）。

        Args:
            trade_date: 按研报日期 YYYYMMDD，如 '20260516'
            ts_code: 按股票代码，如 '600519.SH'
            start_date: 按股票代码时的起始日期 YYYYMMDD
            end_date: 按股票代码时的结束日期 YYYYMMDD
            limit: 最大返回条数
        """
        if not self.research_available:
            logger.warning("研报数据源未配置 token")
            return []

        try:
            if trade_date:
                df = self._research_api.research_report(trade_date=trade_date)
            elif ts_code:
                df = self._research_api.research_report(
                    ts_code=ts_code,
                    start_date=start_date,
                    end_date=end_date,
                )
            else:
                logger.warning("get_reports 需要 trade_date 或 ts_code 参数")
                return []

            if df is None or len(df) == 0:
                logger.info("minishare 研报数据为空")
                return []

            records = []
            for _, row in df.iterrows():
                pub_date = _safe_str(row.get("trade_date") or row.get("日期"))
                if not pub_date:
                    continue
                ts_code_val = _normalize_ts_code(str(row.get("ts_code") or row.get("股票代码") or ""))
                records.append({
                    "trade_date": pub_date,
                    "ts_code": ts_code_val,
                    "name": _safe_str(row.get("name") or row.get("股票简称")),
                    "title": _safe_str(row.get("title") or row.get("报告名称")),
                    "inst_csname": _safe_str(row.get("inst_csname") or row.get("机构")),
                    "author": _safe_str(row.get("author") or row.get("作者")),
                    "org_code": "",
                    "url": _safe_str(row.get("url") or row.get("链接")),
                    "file_name": "",
                })

            logger.info(f"minishare 获取研报数据: {len(records)} 条")
            return records[:limit]
        except Exception as e:
            logger.error(f"minishare 获取研报数据失败: {e}")
            return []

    def get_irm(self, trade_date: str) -> list[dict[str, Any]]:
        """获取互动易 Q&A（minishare，深交所 + 上交所）。

        Args:
            trade_date: 日期 YYYYMMDD，如 '20260512'
        """
        if not self.irm_available:
            logger.warning("互动易数据源未配置 token")
            return []

        records: list[dict[str, Any]] = []

        # 上证
        try:
            df_sh = self._irm_api.irm_qa_sh(trade_date=trade_date)
            if df_sh is not None and len(df_sh) > 0:
                for _, row in df_sh.iterrows():
                    answer = _safe_str(row.get("answer") or row.get("回答"))
                    if not answer:
                        continue
                    records.append({
                        "stock_code": _safe_str(row.get("stock_code") or row.get("股票代码")),
                        "stock_name": _safe_str(row.get("stock_name") or row.get("公司简称")),
                        "question": _safe_str(row.get("question") or row.get("问题")),
                        "answer": answer,
                        "question_time": _safe_str_full(row.get("question_time") or row.get("提问时间")),
                        "answer_time": _safe_str_full(row.get("answer_time") or row.get("回答时间")),
                        "exchange": "SH",
                    })
                logger.info(f"minishare 上证互动易: {len(df_sh)} 条")
        except Exception as e:
            logger.warning(f"minishare 上证互动易失败: {e}")

        # 深证
        try:
            df_sz = self._irm_api.irm_qa_sz(trade_date=trade_date)
            if df_sz is not None and len(df_sz) > 0:
                for _, row in df_sz.iterrows():
                    answer = _safe_str(row.get("answer") or row.get("回答内容"))
                    if not answer:
                        continue
                    records.append({
                        "stock_code": _safe_str(row.get("stock_code") or row.get("股票代码")),
                        "stock_name": _safe_str(row.get("stock_name") or row.get("公司简称")),
                        "question": _safe_str(row.get("question") or row.get("问题")),
                        "answer": answer,
                        "question_time": _safe_str_full(row.get("question_time") or row.get("提问时间")),
                        "answer_time": _safe_str_full(row.get("answer_time") or row.get("更新时间")),
                        "exchange": "SZ",
                    })
                logger.info(f"minishare 深证互动易: {len(df_sz)} 条")
        except Exception as e:
            logger.warning(f"minishare 深证互动易失败: {e}")

        return records

    def iter_reports_by_date_range(
        self,
        start_date: str,
        end_date: str,
    ):
        """按日期范围遍历研报数据（生成器）。

        Args:
            start_date: 起始日期 YYYYMMDD
            end_date: 结束日期 YYYYMMDD

        Yields:
            tuple(date_str, list[dict]): 每天的研报记录列表
        """
        if not self.research_available:
            return

        from datetime import datetime, timedelta

        current = datetime.strptime(start_date, "%Y%m%d")
        end = datetime.strptime(end_date, "%Y%m%d")
        while current <= end:
            date_str = current.strftime("%Y%m%d")
            try:
                df = self._research_api.research_report(trade_date=date_str)
                if df is not None and len(df) > 0:
                    records = []
                    for _, row in df.iterrows():
                        pub_date = _safe_str(row.get("trade_date") or row.get("日期"))
                        if not pub_date:
                            continue
                        ts_code_val = _normalize_ts_code(str(row.get("ts_code") or row.get("股票代码") or ""))
                        records.append({
                            "trade_date": pub_date,
                            "ts_code": ts_code_val,
                            "name": _safe_str(row.get("name") or row.get("股票简称")),
                            "title": _safe_str(row.get("title") or row.get("报告名称")),
                            "inst_csname": _safe_str(row.get("inst_csname") or row.get("机构")),
                            "author": _safe_str(row.get("author") or row.get("作者")),
                            "org_code": "",
                            "url": _safe_str(row.get("url") or row.get("链接")),
                            "file_name": "",
                        })
                    yield date_str, records
                else:
                    yield date_str, []
            except Exception as e:
                logger.warning(f"minishare 研报 {date_str} 失败: {e}")
                yield date_str, []
            current += timedelta(days=1)

    def iter_irm_by_date_range(
        self,
        start_date: str,
        end_date: str,
    ):
        """按日期范围遍历互动易 Q&A（生成器，上证 + 深证）。

        Args:
            start_date: 起始日期 YYYYMMDD
            end_date: 结束日期 YYYYMMDD

        Yields:
            tuple(date_str, list[dict]): 每天的互动易记录列表
        """
        if not self.irm_available:
            return

        from datetime import datetime, timedelta

        current = datetime.strptime(start_date, "%Y%m%d")
        end = datetime.strptime(end_date, "%Y%m%d")
        while current <= end:
            date_str = current.strftime("%Y%m%d")
            records: list[dict[str, Any]] = []

            # 上证
            try:
                df_sh = self._irm_api.irm_qa_sh(trade_date=date_str)
                if df_sh is not None and len(df_sh) > 0:
                    for _, row in df_sh.iterrows():
                        answer = _safe_str(row.get("answer") or row.get("回答"))
                        if not answer:
                            continue
                        records.append({
                            "stock_code": _safe_str(row.get("stock_code") or row.get("股票代码")),
                            "stock_name": _safe_str(row.get("stock_name") or row.get("公司简称")),
                            "question": _safe_str(row.get("question") or row.get("问题")),
                            "answer": answer,
                            "question_time": _safe_str_full(row.get("question_time") or row.get("提问时间")),
                            "answer_time": _safe_str_full(row.get("answer_time") or row.get("回答时间")),
                            "exchange": "SH",
                        })
            except Exception as e:
                logger.warning(f"minishare 上证互动易 {date_str} 失败: {e}")

            # 深证
            try:
                df_sz = self._irm_api.irm_qa_sz(trade_date=date_str)
                if df_sz is not None and len(df_sz) > 0:
                    for _, row in df_sz.iterrows():
                        answer = _safe_str(row.get("answer") or row.get("回答内容"))
                        if not answer:
                            continue
                        records.append({
                            "stock_code": _safe_str(row.get("stock_code") or row.get("股票代码")),
                            "stock_name": _safe_str(row.get("stock_name") or row.get("公司简称")),
                            "question": _safe_str(row.get("question") or row.get("问题")),
                            "answer": answer,
                            "question_time": _safe_str_full(row.get("question_time") or row.get("提问时间")),
                            "answer_time": _safe_str_full(row.get("answer_time") or row.get("更新时间")),
                            "exchange": "SZ",
                        })
            except Exception as e:
                logger.warning(f"minishare 深证互动易 {date_str} 失败: {e}")

            yield date_str, records
            current += timedelta(days=1)