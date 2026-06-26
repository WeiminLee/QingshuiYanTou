"""
DataSourceClientMinishare — minishare 备选数据源

数据源：
- 研报: pro.research_report(trade_date=) / pro.research_report(ts_code=, start_date=, end_date=)
- 公告: pro.anns_d(ann_date=) / pro.anns_d(ts_code=, start_date=, end_date=)
"""

from __future__ import annotations

import logging
from typing import Any

import minishare as ms
import pandas as pd

from app.config import settings
from app.data_pipeline.rate_limiter import get_minishare_async_limiter

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

        if not research_token:
            logger.warning("MINISHARE_RESEARCH_TOKEN 未配置，研报数据源不可用")
            self._research_api = None
        else:
            self._research_api = ms.pro_api(research_token)

        self._anns_api = None  # 延迟初始化

    @property
    def research_available(self) -> bool:
        return self._research_api is not None

    @property
    def anns_available(self) -> bool:
        return bool(settings.minishare_anns_token)

    def _ensure_anns_api(self) -> Any:
        """延迟初始化 anns API"""
        anns_token = settings.minishare_anns_token
        if not anns_token:
            logger.warning("MINISHARE_ANNS_TOKEN 未配置，公告数据源不可用")
            self._anns_api = None
            return None
        if self._anns_api is None:
            self._anns_api = ms.pro_api(anns_token)
        return self._anns_api

    def get_reports(
        self,
        trade_date: str | None = None,
        ts_code: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
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
                records.append(
                    {
                        "trade_date": pub_date,
                        "ts_code": ts_code_val,
                        "name": _safe_str(row.get("name") or row.get("股票简称")),
                        "title": _safe_str(row.get("title") or row.get("报告名称")),
                        "inst_csname": _safe_str(row.get("inst_csname") or row.get("机构")),
                        "author": _safe_str(row.get("author") or row.get("作者")),
                        "org_code": "",
                        "url": _safe_str(row.get("url") or row.get("链接")),
                        "file_name": "",
                    }
                )

            logger.info(f"minishare 获取研报数据: {len(records)} 条")
            return records[:limit]
        except Exception as e:
            logger.error(f"minishare 获取研报数据失败: {e}")
            return []

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
                        records.append(
                            {
                                "trade_date": pub_date,
                                "ts_code": ts_code_val,
                                "name": _safe_str(row.get("name") or row.get("股票简称")),
                                "title": _safe_str(row.get("title") or row.get("报告名称")),
                                "inst_csname": _safe_str(row.get("inst_csname") or row.get("机构")),
                                "author": _safe_str(row.get("author") or row.get("作者")),
                                "org_code": "",
                                "url": _safe_str(row.get("url") or row.get("链接")),
                                "file_name": "",
                            }
                        )
                    yield date_str, records
                else:
                    yield date_str, []
            except Exception as e:
                logger.warning(f"minishare 研报 {date_str} 失败: {e}")
                yield date_str, []
            current += timedelta(days=1)

    async def iter_reports_by_date_range_async(
        self,
        start_date: str,
        end_date: str,
    ):
        """async 版本的 iter_reports_by_date_range。

        每个日期的 API 调用通过 asyncio.to_thread 放到线程池执行，
        避免阻塞 FastAPI 事件循环。
        """
        import asyncio
        from datetime import datetime, timedelta

        if not self.research_available:
            return

        current = datetime.strptime(start_date, "%Y%m%d")
        end = datetime.strptime(end_date, "%Y%m%d")
        while current <= end:
            date_str = current.strftime("%Y%m%d")
            # 网络请求放到线程池，遇到限流/网络错误时当天返回空记录
            try:
                df = await asyncio.to_thread(self._research_api.research_report, trade_date=date_str)
            except Exception as e:
                logger.warning(f"minishare 研报 {date_str} 失败: {e}")
                df = None
            if df is not None and len(df) > 0:
                records = []
                for _, row in df.iterrows():
                    pub_date = _safe_str(row.get("trade_date") or row.get("日期"))
                    if not pub_date:
                        continue
                    ts_code_val = _normalize_ts_code(str(row.get("ts_code") or row.get("股票代码") or ""))
                    records.append(
                        {
                            "trade_date": pub_date,
                            "ts_code": ts_code_val,
                            "name": _safe_str(row.get("name") or row.get("股票简称")),
                            "title": _safe_str(row.get("title") or row.get("报告名称")),
                            "inst_csname": _safe_str(row.get("inst_csname") or row.get("机构")),
                            "author": _safe_str(row.get("author") or row.get("作者")),
                            "org_code": "",
                            "url": _safe_str(row.get("url") or row.get("链接")),
                            "file_name": "",
                        }
                    )
                yield date_str, records
            else:
                yield date_str, []
            current += timedelta(days=1)

    # ── 公告（anns_d）──────────────────────────────────────

    def get_announcements(
        self,
        ann_date: str | None = None,
        ts_code: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = 5000,
    ) -> list[dict[str, Any]]:
        """获取公告数据（minishare anns_d）。

        Args:
            ann_date: 按公告日期 YYYYMMDD（与 ts_code 二选一）
            ts_code: 按股票代码（配合 start_date/end_date）
            start_date: 起始日期 YYYYMMDD
            end_date: 结束日期 YYYYMMDD
            limit: 最大返回条数
        """
        api = self._ensure_anns_api()
        if api is None:
            logger.warning("公告数据源未配置 token")
            return []

        try:
            if ann_date:
                df = api.anns_d(ann_date=ann_date, limit=limit, offset=0)
            elif ts_code:
                df = api.anns_d(ts_code=ts_code, start_date=start_date, end_date=end_date, limit=limit, offset=0)
            else:
                logger.warning("get_announcements 需要 ann_date 或 ts_code 参数")
                return []

            if df is None or len(df) == 0:
                logger.info("minishare 公告数据为空")
                return []

            records = []
            for _, row in df.iterrows():
                ann_date_val = _safe_str(row.get("ann_date"))
                if not ann_date_val:
                    continue
                ts_code_val = _normalize_ts_code(str(row.get("ts_code") or ""))
                records.append(
                    {
                        "ann_date": ann_date_val,
                        "ts_code": ts_code_val,
                        "name": _safe_str(row.get("name")),
                        "title": _safe_str(row.get("title")),
                        "url": _safe_str(row.get("url")),
                    }
                )

            logger.info(f"minishare 获取公告数据: {len(records)} 条")
            return records[:limit]
        except Exception as e:
            logger.error(f"minishare 获取公告数据失败: {e}")
            return []

    def iter_ann_by_date_range(
        self,
        start_date: str,
        end_date: str,
    ):
        """按日期范围遍历公告数据（生成器）。

        Args:
            start_date: 起始日期 YYYYMMDD
            end_date: 结束日期 YYYYMMDD

        Yields:
            tuple(date_str, list[dict]): 每天的公告记录列表
        """
        api = self._ensure_anns_api()
        if api is None:
            return

        from datetime import datetime, timedelta

        current = datetime.strptime(start_date, "%Y%m%d")
        end = datetime.strptime(end_date, "%Y%m%d")
        while current <= end:
            date_str = current.strftime("%Y%m%d")
            try:
                df = api.anns_d(ann_date=date_str, limit=5000, offset=0)
                if df is not None and len(df) > 0:
                    records = []
                    for _, row in df.iterrows():
                        ann_date_val = _safe_str(row.get("ann_date"))
                        if not ann_date_val:
                            continue
                        ts_code_val = _normalize_ts_code(str(row.get("ts_code") or ""))
                        records.append(
                            {
                                "ann_date": ann_date_val,
                                "ts_code": ts_code_val,
                                "name": _safe_str(row.get("name")),
                                "title": _safe_str(row.get("title")),
                                "url": _safe_str(row.get("url")),
                            }
                        )
                    yield date_str, records
                else:
                    yield date_str, []
            except Exception as e:
                logger.warning(f"minishare 公告 {date_str} 失败: {e}")
                yield date_str, []
            current += timedelta(days=1)

    async def iter_ann_by_date_range_async(
        self,
        start_date: str,
        end_date: str,
    ):
        """async 版本的 iter_ann_by_date_range。

        每个日期的 API 调用通过 asyncio.to_thread 放到线程池执行，
        避免阻塞 FastAPI 事件循环。
        """
        import asyncio
        from datetime import datetime, timedelta

        api = self._ensure_anns_api()
        if api is None:
            return

        current = datetime.strptime(start_date, "%Y%m%d")
        end = datetime.strptime(end_date, "%Y%m%d")
        ann_limiter = get_minishare_async_limiter("anns_d")
        while current <= end:
            date_str = current.strftime("%Y%m%d")
            await ann_limiter.wait_and_acquire()
            try:
                df = await asyncio.to_thread(api.anns_d, ann_date=date_str, limit=5000, offset=0)
            except Exception as e:
                logger.warning(f"minishare 公告 {date_str} 失败: {e}")
                df = None
            if df is not None and len(df) > 0:
                records = []
                for _, row in df.iterrows():
                    ann_date_val = _safe_str(row.get("ann_date"))
                    if not ann_date_val:
                        continue
                    ts_code_val = _normalize_ts_code(str(row.get("ts_code") or ""))
                    records.append(
                        {
                            "ann_date": ann_date_val,
                            "ts_code": ts_code_val,
                            "name": _safe_str(row.get("name")),
                            "title": _safe_str(row.get("title")),
                            "url": _safe_str(row.get("url")),
                        }
                    )
                yield date_str, records
            else:
                yield date_str, []
            current += timedelta(days=1)
