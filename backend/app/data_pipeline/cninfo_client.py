"""
CninfoClient - 巨潮资讯网 API 异步客户端

通过巨潮 API 获取公告列表（带 PDF 下载链接）。
迁移自 data_access_mvp/src/utils/cninfo_client.py，并适配新项目的 async 架构。

设计要点：
- 底层使用同步 ``requests`` 库（与旧项目一致），通过 ``asyncio.to_thread`` 桥接到 async 上下文。
- 限流通过 ``AsyncRateLimiter`` 在异步层执行，避免阻塞事件循环。
- API 端点参考 ``CNINFO_QUERY_API``，PDF 通过 ``CNINFO_PDF_BASE`` 拼接。

Plan: 03-01 (phase 03-cninfoclient)
Decisions referenced: D-01 (官方 API), D-06 (1 req/sec 限流)
"""
from __future__ import annotations

import asyncio
import re
import logging
import time
import threading
from typing import Any, Awaitable, Callable

import requests

from app.data_pipeline.rate_limiter import get_cninfo_api_limiter

logger = logging.getLogger(__name__)

# ── 巨潮 API 端点 ────────────────────────────────────────────────
# D-01：使用 cninfo 官方 API，不走 akshare 封装
CNINFO_QUERY_API = "http://www.cninfo.com.cn/new/hisAnnouncement/query"
CNINFO_PDF_BASE = "http://static.cninfo.com.cn/"

# ── 请求头 ───────────────────────────────────────────────────────
# 模拟浏览器请求，参考旧项目和巨潮接口文档
CNINFO_HEADERS: dict[str, str] = {
    "Accept": "*/*",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Host": "www.cninfo.com.cn",
    "Origin": "http://www.cninfo.com.cn",
    "Referer": (
        "http://www.cninfo.com.cn/new/commonUrl/pageOfSearch"
        "?url=disclosure/list/search"
    ),
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "X-Requested-With": "XMLHttpRequest",
}

# ── 默认参数 ─────────────────────────────────────────────────────
DEFAULT_PAGE_SIZE = 30
DEFAULT_TIMEOUT = 30  # seconds
EXCHANGE_MAP = {"0": "SZ", "3": "SZ", "6": "SH", "8": "BJ"}
CNINFO_STOCK_JSON = "http://www.cninfo.com.cn/new/data/szse_stock.json"
_HTML_TAG_RE = re.compile(r"<[^>]+>")


# ── 模块级股票代码映射缓存（线程安全单例） ─────────────────────
# @lru_cache on a staticmethod is unsafe under asyncio.to_thread concurrency.
# Replace with a module-level singleton guarded by a lock.
_org_map_lock = threading.Lock()
_org_map_cache: dict[str, str] | None = None


def _get_stock_org_map_cached() -> dict[str, str]:
    """线程安全的模块级 A 股代码→orgId 映射缓存（进程内单次请求）。"""
    global _org_map_cache
    if _org_map_cache is None:
        with _org_map_lock:
            if _org_map_cache is None:  # double-check
                try:
                    response = requests.get(
                        CNINFO_STOCK_JSON,
                        headers=CNINFO_HEADERS,
                        timeout=DEFAULT_TIMEOUT,
                    )
                    response.raise_for_status()
                    data = response.json()
                except Exception as e:
                    logger.warning("获取巨潮股票 orgId 映射失败: %s", e)
                    _org_map_cache = {}
                    return _org_map_cache

                stock_list = data.get("stockList") or []
                result: dict[str, str] = {}
                for item in stock_list:
                    code = str(item.get("code") or "").strip()
                    org_id = str(item.get("orgId") or "").strip()
                    if code and org_id:
                        result[code] = org_id
                _org_map_cache = result
    return _org_map_cache


class CninfoClientError(RuntimeError):
    """巨潮公告接口请求失败或返回业务错误。"""


class CninfoClient:
    """巨潮资讯 API 异步封装

    内部维护一个 ``requests.Session`` 用于保持 Cookie。所有对外的网络方法都是
    ``async``，通过 ``asyncio.to_thread`` 把同步 IO 卸载到线程池，避免阻塞事件循环。
    """

    def __init__(self) -> None:
        self.session: requests.Session = requests.Session()
        self.session.headers.update(CNINFO_HEADERS)
        self._session_initialized = False

    # ── 内部同步方法 ──────────────────────────────────────────────

    def _ensure_session_sync(self) -> None:
        """同步建立 session（保持 Cookie）。失败不影响后续查询。"""
        try:
            self.session.get("http://www.cninfo.com.cn/", timeout=5)
        except Exception as e:  # noqa: BLE001 - 允许失败
            logger.debug("初始化巨潮 session 失败（可忽略）: %s", e)

    def _build_payload(
        self,
        ann_date: str | None,
        ts_code: str | None,
        page: int,
        page_size: int,
        ann_date_end: str | None = None,
    ) -> dict[str, str]:
        """构造 cninfo API 请求 payload。

        - ``ts_code``: ``000001.SZ`` -> ``000001,gssz0000001``
        - ``ann_date``: ``YYYYMMDD`` -> ``YYYY-MM-DD~YYYY-MM-DD``（区间格式）
        - ``ann_date_end``: 结束日期，支持范围查询（与 ann_date 配合）
        """
        stock_code = ""
        if ts_code:
            sec_code = ts_code.split(".")[0] if "." in ts_code else ts_code
            org_id = _get_stock_org_map_cached().get(sec_code)
            stock_code = f"{sec_code},{org_id}" if org_id else sec_code

        se_date = ""
        if ann_date:
            if len(ann_date) != 8 or not ann_date.isdigit():
                raise ValueError(
                    f"ann_date 必须是 YYYYMMDD 格式（8位数字），收到: {ann_date!r}"
                )
            start_formatted = f"{ann_date[:4]}-{ann_date[4:6]}-{ann_date[6:8]}"
            if ann_date_end and ann_date_end != ann_date:
                # 范围查询
                if len(ann_date_end) != 8 or not ann_date_end.isdigit():
                    raise ValueError(
                        f"ann_date_end 必须是 YYYYMMDD 格式（8位数字），收到: {ann_date_end!r}"
                    )
                end_formatted = f"{ann_date_end[:4]}-{ann_date_end[4:6]}-{ann_date_end[6:8]}"
                se_date = f"{start_formatted}~{end_formatted}"
            else:
                se_date = f"{start_formatted}~{start_formatted}"

        return {
            "pageNum": str(page),
            "pageSize": str(page_size),
            "column": "szse" if ts_code else "",  # A 股个股查询必须指定 szse
            "tabName": "fulltext",
            "plate": "",
            "stock": stock_code,
            "searchkey": "",
            "secid": "",
            "category": "",
            "trade": "",
            "seDate": se_date,
            "sortName": "",
            "sortType": "",
            "isHLtitle": "true",
        }

    def _sync_query(
        self,
        ann_date: str | None,
        ts_code: str | None,
        page: int,
        page_size: int,
        ann_date_end: str | None = None,
    ) -> dict[str, Any]:
        """同步 HTTP POST 调用 cninfo API。

        本方法在 ``asyncio.to_thread`` 中执行；不要在 async 路径直接调用。
        """
        if not self._session_initialized:
            self._ensure_session_sync()
            self._session_initialized = True

        payload = self._build_payload(ann_date, ts_code, page, page_size, ann_date_end)

        try:
            response = self.session.post(
                CNINFO_QUERY_API,
                data=payload,
                timeout=DEFAULT_TIMEOUT,
            )
            response.raise_for_status()
            data = response.json()
        except Exception as e:  # noqa: BLE001 - 网络错误统一吞掉
            logger.error("巨潮 API 请求失败: %s", e)
            raise CninfoClientError(f"巨潮 API 请求失败: {e}") from e

        # cninfo 业务错误码：code != "0" 表示失败
        code = data.get("code")
        if code is not None and str(code) != "0":
            logger.warning(
                "巨潮 API 返回错误: code=%s message=%s",
                code,
                data.get("message", ""),
            )
            raise CninfoClientError(
                f"巨潮 API 返回错误: code={code} message={data.get('message', '')}"
            )

        announcements = data.get("announcements") or []
        total = int(
            data.get("totalRecordNum")
            or data.get("totalAnnouncement")
            or 0
        )
        return {
            "total": total,
            "list": announcements,
            "has_more": bool(data.get("hasMore")),
            "total_pages": int(data.get("totalpages") or 0),
        }

    # ── 异步公开方法 ──────────────────────────────────────────────

    async def query_announcements(
        self,
        ann_date: str | None = None,
        ts_code: str | None = None,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
        ann_date_end: str | None = None,
    ) -> dict[str, Any]:
        """查询单页公告列表

        Args:
            ann_date: 起始日期 ``YYYYMMDD``。为 ``None`` 则不限定日期。
            ann_date_end: 结束日期 ``YYYYMMDD``。与 ann_date 配合实现范围查询。
            ts_code: 股票代码（如 ``000001.SZ``）。为 ``None`` 则查全市场。
            page: 页码，从 1 开始。
            page_size: 每页数量，默认 100。

        Returns:
            ``{"total": int, "list": [announcement_dict, ...]}``
        """
        # D-06：API 查询 1 req/sec，使用异步限流器
        await get_cninfo_api_limiter().wait_and_acquire()

        # 同步 IO 卸载到线程池
        return await asyncio.to_thread(
            self._sync_query,
            ann_date,
            ts_code,
            page,
            page_size,
            ann_date_end,
        )

    async def get_announcements(
        self,
        ann_date: str | None = None,
        ts_code: str | None = None,
        ann_date_end: str | None = None,
        progress_callback: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
        max_pages: int = 500,
    ) -> list[dict[str, Any]]:
        """获取指定日期范围/股票的所有公告（自动分页）

        Args:
            ann_date: 起始日期 ``YYYYMMDD``。为 ``None`` 则不限定日期。
            ann_date_end: 结束日期 ``YYYYMMDD``。与 ann_date 配合实现范围查询。
            ts_code: 股票代码（如 ``000001.SZ``）。为 ``None`` 则查全市场。

        Returns:
            公告列表（自动分页抓取全部）
        """
        results: list[dict[str, Any]] = []
        page = 1
        page_size = DEFAULT_PAGE_SIZE

        while True:
            if page > max_pages:
                raise CninfoClientError(
                    f"巨潮 API 分页超过最大分页数 {max_pages}: "
                    f"ann_date={ann_date} ann_date_end={ann_date_end} ts_code={ts_code}"
                )
            resp = await self.query_announcements(
                ann_date=ann_date,
                ts_code=ts_code,
                page=page,
                page_size=page_size,
                ann_date_end=ann_date_end,
            )
            announcements = resp.get("list") or []
            total = int(resp.get("total", 0))
            has_more = bool(resp.get("has_more"))
            results.extend(announcements)
            if progress_callback is not None:
                await progress_callback({
                    "page": page,
                    "page_items": len(announcements),
                    "fetched_items": len(results),
                    "total_items": total,
                    "has_more": has_more,
                    "total_pages": resp.get("total_pages"),
                })

            if page % 10 == 1:
                logger.info(
                    "巨潮 API 第 %d 页，已获取 %d/%d 条",
                    page,
                    len(results),
                    total,
                )

            # 巨潮可能忽略 pageSize 并固定返回 30 条，且 totalpages 可能少算末页。
            # 以 total 是否抓满和 hasMore 为准，避免漏抓最后一页。
            if not announcements:
                break
            if total > 0 and len(results) >= total:
                break
            if not has_more:
                break
            page += 1

        logger.info(
            "巨潮 API 获取公告: %d 条（总计 %d）",
            len(results),
            total,
        )
        return results

    # ── 静态解析助手 ──────────────────────────────────────────────

    @staticmethod
    def get_pdf_url(announcement: dict[str, Any]) -> str:
        """从公告数据中提取 PDF 完整下载地址。

        cninfo 的 ``adjunctUrl`` 是相对路径，需拼接 ``CNINFO_PDF_BASE``。
        """
        adjunct_url = announcement.get("adjunctUrl", "")
        if adjunct_url:
            return CNINFO_PDF_BASE + adjunct_url
        return ""

    @staticmethod
    def get_announcement_id(announcement: dict[str, Any]) -> str:
        """获取公告 ID（用作 ``cninfo_id`` 去重键）"""
        return str(announcement.get("announcementId", ""))

    @staticmethod
    def get_title(announcement: dict[str, Any]) -> str:
        """获取公告标题"""
        title = str(announcement.get("announcementTitle", ""))
        return _HTML_TAG_RE.sub("", title)

    @staticmethod
    def get_ts_code(announcement: dict[str, Any]) -> str:
        """从巨潮公告数据提取 tushare 风格股票代码

        - ``secCode`` 不足 6 位时补零（如 ``"576"`` -> ``"000576"``）
        - 根据首位数字判断交易所：
          - ``0/3`` -> SZ（深市）
          - ``6`` -> SH（沪市）
          - ``8`` -> BJ（北交所）
          - 其他默认 SZ
        """
        sec_code = announcement.get("secCode", "")
        if not sec_code:
            return ""
        sec_code = str(sec_code).zfill(6)
        suffix = EXCHANGE_MAP.get(sec_code[0], "SZ")
        return f"{sec_code}.{suffix}"

    @staticmethod
    def get_ann_date(announcement: dict[str, Any]) -> str:
        """获取公告日期 ``YYYYMMDD``

        cninfo 返回的是毫秒时间戳，转为本地日期字符串。
        """
        ts_ms = announcement.get("announcementTime", 0)
        if not ts_ms:
            return ""
        try:
            return time.strftime("%Y%m%d", time.localtime(int(ts_ms) / 1000))
        except (TypeError, ValueError, OSError) as e:
            logger.warning("解析 announcementTime 失败: ts_ms=%r err=%s", ts_ms, e)
            return ""


__all__ = [
    "CNINFO_HEADERS",
    "CNINFO_PDF_BASE",
    "CNINFO_STOCK_JSON",
    "CNINFO_QUERY_API",
    "CninfoClient",
]
