from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from datetime import UTC, date, datetime
from typing import Any

from app.config import settings
from app.core.database import engine

logger = logging.getLogger(__name__)

_TUSHARE_PRO: Any = None
_PUBLIC_PAGE_CAP = 50
_HTTP_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"\s+")


def _get_ts_pro():
    global _TUSHARE_PRO
    if _TUSHARE_PRO is None:
        from app.data_pipeline.tinyshare_client import open_tinyshare_pro

        _TUSHARE_PRO = open_tinyshare_pro(settings.tushare_token)
    return _TUSHARE_PRO


def _add_counts(total: dict[str, int], part: dict[str, int]) -> None:
    for key in ("fetched", "inserted", "skipped"):
        total[key] = total.get(key, 0) + part.get(key, 0)


def stable_event_id(title: str) -> str:
    raw = (title or "").strip()
    return f"EV:{hashlib.sha256(raw.encode()).hexdigest()[:16]}"


def auto_tag(title: str, concept_names: list[str]) -> list[str]:
    tags = []
    for name in concept_names:
        if name in title:
            tags.append(name)
    return tags


def _public_page_size(limit: int) -> int:
    return min(max(int(limit), 1), _PUBLIC_PAGE_CAP)


def _strip_html(value: str) -> str:
    return _SPACE_RE.sub(" ", _TAG_RE.sub("", value or "")).strip()


def _coerce_unix(value: Any) -> datetime | None:
    """秒或毫秒的 unix 时间。东财的日期字符串仍走 _parse_datetime。"""
    if isinstance(value, bool) or value is None or value == "":
        return None
    if isinstance(value, datetime):
        return _parse_datetime(value)
    if isinstance(value, (int, float)):
        raw = float(value)
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            raw = float(text)
        except ValueError:
            return _parse_datetime(text)
    else:
        return None
    if raw > 10_000_000_000:
        raw /= 1000.0
    if raw <= 0:
        return None
    return datetime.fromtimestamp(raw, tz=UTC)


def _flash_record(
    *,
    title: str,
    summary: str,
    url: str,
    publish_at: datetime | None,
    source: str,
) -> dict[str, Any] | None:
    title = title.strip()
    if not title:
        return None
    return {
        "title": title,
        "summary": (summary or title).strip(),
        "url": url.strip(),
        "publish_at": publish_at or datetime.now(UTC),
        "source": source,
    }


def parse_wallstreetcn_payload(data: Any) -> list[dict[str, Any]]:
    items = ((data or {}).get("data") or {}).get("items") or []
    records: list[dict[str, Any]] = []
    if not isinstance(items, list):
        return records
    for item in items:
        if not isinstance(item, dict):
            continue
        content_text = str(item.get("content_text") or "").strip()
        html_text = _strip_html(str(item.get("content") or ""))
        title = str(item.get("title") or "").strip() or content_text or html_text
        record = _flash_record(
            title=title,
            summary=content_text or html_text or title,
            url=str(item.get("uri") or ""),
            publish_at=_coerce_unix(item.get("display_time")),
            source="wallstreetcn",
        )
        if record is not None:
            records.append(record)
    return records


def parse_ths_payload(data: Any) -> list[dict[str, Any]]:
    items = ((data or {}).get("data") or {}).get("list") or []
    records: list[dict[str, Any]] = []
    if not isinstance(items, list):
        return records
    for item in items:
        if not isinstance(item, dict):
            continue
        record = _flash_record(
            title=str(item.get("title") or ""),
            summary=str(item.get("digest") or item.get("short") or ""),
            url=str(item.get("url") or ""),
            publish_at=_coerce_unix(item.get("ctime") or item.get("rtime")),
            source="ths",
        )
        if record is not None:
            records.append(record)
    return records


def parse_sina_roll_payload(data: Any) -> list[dict[str, Any]]:
    items = ((data or {}).get("result") or {}).get("data")
    records: list[dict[str, Any]] = []
    if not isinstance(items, list):
        return records
    for item in items:
        if not isinstance(item, dict):
            continue
        record = _flash_record(
            title=str(item.get("title") or ""),
            summary=str(item.get("intro") or ""),
            url=str(item.get("url") or ""),
            publish_at=_coerce_unix(item.get("ctime")),
            source="sina",
        )
        if record is not None:
            records.append(record)
    return records


def _get_json(url: str, params: dict[str, Any]) -> Any:
    import requests

    response = requests.get(url, params=params, headers=_HTTP_HEADERS, timeout=30)
    response.raise_for_status()
    return response.json()


class NewsService:
    def __init__(self):
        self._concept_names: list[str] | None = None

    async def _load_concept_names(self) -> list[str]:
        if self._concept_names is not None:
            return self._concept_names
        from sqlalchemy import select

        from app.models.models import ThsConcept

        async with engine.connect() as conn:
            result = await conn.execute(select(ThsConcept.name))
            names = [r[0] for r in result.fetchall()]
        self._concept_names = names
        return names

    async def _save_events_from_df(
        self,
        df: Any,
        limit: int,
    ) -> dict[str, int]:
        """将 Tushare DataFrame 中的事件保存到 events 表。"""
        concept_names = await self._load_concept_names()
        inserted = 0
        skipped = 0
        signal_rows: list[dict[str, Any]] = []

        async with engine.connect() as conn:
            for _, row in df.head(limit).iterrows():
                title = str(row.get("title") or "")
                if not title.strip():
                    skipped += 1
                    continue

                eid = stable_event_id(title)
                tags = auto_tag(title, concept_names)
                metadata = {"tags": tags} if tags else {}
                summary = str(row.get("content") or row.get("summary") or "")
                publish_at = _parse_datetime(row.get("pub_time") or row.get("datetime") or "")
                url = str(row.get("url") or "")

                from sqlalchemy import text

                pg_stmt = text("""
                    INSERT INTO events (event_id, title, summary, source, url, publish_at, metadata)
                    VALUES (:event_id, :title, :summary, :source, :url, :publish_at, CAST(:metadata AS jsonb))
                    ON CONFLICT (event_id) DO NOTHING
                """)
                result = await conn.execute(
                    pg_stmt,
                    {
                        "event_id": eid,
                        "title": title,
                        "summary": summary,
                        "source": "tushare",
                        "url": url,
                        "publish_at": publish_at,
                        "metadata": json.dumps(metadata, ensure_ascii=False),
                    },
                )
                if result.rowcount > 0:
                    inserted += 1
                else:
                    skipped += 1
                signal_rows.append(
                    {
                        "event_id": eid,
                        "title": title,
                        "summary": summary,
                        "content": summary,
                        "source": "tushare",
                        "url": url,
                        "publish_at": publish_at,
                        "metadata": metadata,
                    }
                )

            await conn.commit()

        await _extract_signals_for_events(signal_rows)
        return {"fetched": len(df), "inserted": inserted, "skipped": skipped}

    async def fetch_and_save(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = 200,
    ) -> dict[str, int]:
        df = None
        try:
            pro = _get_ts_pro()
            src = settings.tushare_http_url.rstrip("/")
            df = pro.news(
                src=src,
                start_date=start_date,
                end_date=end_date,
            )
        except ModuleNotFoundError:
            logger.warning("tinyshare is not installed; news sync disabled")
        except Exception:
            df = None  # 无 news 权限时降级，改走 HTTP 快讯源

        totals = {"fetched": 0, "inserted": 0, "skipped": 0}
        if df is not None and not df.empty:
            _add_counts(totals, await self._save_events_from_df(df, limit))

        # 东财之外，华尔街见闻、同花顺、新浪滚动每轮都拉。单路失败已在各拉取里吞掉。
        records: list[dict[str, Any]] = []
        for fetcher in (
            self._fetch_eastmoney_flash,
            self._fetch_wallstreetcn,
            self._fetch_ths,
            self._fetch_sina_roll,
        ):
            records.extend(await asyncio.to_thread(fetcher, limit))
        _add_counts(totals, await self._save_flash_records(records))
        return totals

    def _fetch_eastmoney_flash(self, limit: int) -> list[dict[str, str]]:
        """从东方财富 7x24 快讯接口拉取财经快讯（无鉴权，30s 超时保护）。"""
        import requests

        url = "https://np-listapi.eastmoney.com/comm/web/getFastNewsList"
        params = {
            "client": "web",
            "biz": "web_724",
            "fastColumn": "102",
            "sortEnd": "",
            "pageSize": str(min(limit, 200)),
            "req_trace": "1",
        }
        headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning("东方财富快讯拉取失败: %s", e)
            return []

        items = (data.get("data") or {}).get("fastNewsList") or []
        records: list[dict[str, str]] = []
        for it in items:
            title = str(it.get("title") or "").strip()
            if not title:
                continue
            records.append(
                {
                    "title": title,
                    "summary": str(it.get("summary") or ""),
                    "url": f"https://www.eastmoney.com/a/{it.get('code', '')}.html",
                    "publish_at": str(it.get("showTime") or ""),
                }
            )
        return records

    def _fetch_wallstreetcn(self, limit: int) -> list[dict[str, Any]]:
        """华尔街见闻 7x24。标题经常为空，正文在 content_text。"""
        try:
            data = _get_json(
                "https://api-one.wallstcn.com/apiv1/content/lives",
                {"channel": "global-channel", "client": "pc", "limit": _public_page_size(limit)},
            )
        except Exception as exc:
            logger.warning("华尔街见闻快讯拉取失败: %s", exc)
            return []
        return parse_wallstreetcn_payload(data)

    def _fetch_ths(self, limit: int) -> list[dict[str, Any]]:
        """同花顺股市快讯。"""
        try:
            data = _get_json(
                "https://news.10jqka.com.cn/tapp/news/push/stock/",
                {"page": "1", "tag": "", "track": "website", "pagesize": _public_page_size(limit)},
            )
        except Exception as exc:
            logger.warning("同花顺快讯拉取失败: %s", exc)
            return []
        return parse_ths_payload(data)

    def _fetch_sina_roll(self, limit: int) -> list[dict[str, Any]]:
        """新浪财经滚动。直播接口是空的，只用 roll。"""
        try:
            data = _get_json(
                "https://feed.mix.sina.com.cn/api/roll/get",
                {"pageid": "153", "lid": "2509", "num": _public_page_size(limit), "page": "1"},
            )
        except Exception as exc:
            logger.warning("新浪滚动拉取失败: %s", exc)
            return []
        return parse_sina_roll_payload(data)

    async def _save_flash_records(
        self,
        records: list[dict[str, Any]],
    ) -> dict[str, int]:
        """将 HTTP 快讯写入 events。每路已限页，这里不再用一个上限把后面的源截掉。"""
        concept_names = await self._load_concept_names()
        inserted = skipped = 0
        signal_rows: list[dict[str, Any]] = []

        from sqlalchemy import text

        async with engine.connect() as conn:
            for rec in records:
                title = rec.get("title") or ""
                if not title:
                    skipped += 1
                    continue
                eid = stable_event_id(title)
                tags = auto_tag(title, concept_names)
                metadata = {"tags": tags} if tags else {}
                summary = rec.get("summary") or ""
                url = rec.get("url") or ""
                source = str(rec.get("source") or "eastmoney_flash")
                publish_at = _parse_datetime(rec.get("publish_at") or "")
                pg_stmt = text("""
                    INSERT INTO events (event_id, title, summary, content, source, url, publish_at, metadata)
                    VALUES (:event_id, :title, :summary, :content, :source, :url, :publish_at, CAST(:metadata AS jsonb))
                    ON CONFLICT (event_id) DO NOTHING
                """)
                result = await conn.execute(
                    pg_stmt,
                    {
                        "event_id": eid,
                        "title": title,
                        "summary": summary,
                        "content": summary,
                        "source": source,
                        "url": url,
                        "publish_at": publish_at,
                        "metadata": json.dumps(metadata, ensure_ascii=False),
                    },
                )
                newly_inserted = result.rowcount > 0
                if newly_inserted:
                    inserted += 1
                else:
                    skipped += 1
                # 东财维持原行为：冲突跳过的行仍二次加工。新源只加工刚插入的，避免三路全量每 5 分钟重跑模型。
                if source == "eastmoney_flash" or newly_inserted:
                    signal_rows.append(
                        {
                            "event_id": eid,
                            "title": title,
                            "summary": summary,
                            "content": summary,
                            "source": source,
                            "url": url,
                            "publish_at": publish_at,
                            "metadata": metadata,
                        }
                    )
            await conn.commit()
        await _extract_signals_for_events(signal_rows)
        return {"fetched": len(records), "inserted": inserted, "skipped": skipped}


async def _extract_signals_for_events(rows: list[dict[str, Any]]) -> None:
    """新闻事件二次加工成 signal，单独落 signals 表。失败不回滚已写入的事件。"""
    if not rows:
        return
    try:
        from app.signals.auto_ingestion import ingest_event_signals

        await ingest_event_signals(rows)
    except Exception as exc:  # noqa: BLE001
        logger.warning("新闻 signal 抽取失败，事件已落库: %s", exc)


def _parse_datetime(val: Any) -> datetime:
    if isinstance(val, datetime):
        if val.tzinfo is None:
            val = val.replace(tzinfo=UTC)
        return val
    if isinstance(val, str):
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(val, fmt).replace(tzinfo=UTC)
            except ValueError:
                continue
    return datetime.now(UTC)


_news_service: NewsService | None = None


def get_news_service() -> NewsService:
    global _news_service
    if _news_service is None:
        _news_service = NewsService()
    return _news_service


# ── 事件检索（agent 工具面；SQL 取自旧 find_events/get_event_detail 工具） ──────


def parse_event_day(value: str | None) -> date | None:
    """YYYYMMDD 或 YYYY-MM-DD → date。空值返回 None，非法值抛 ValueError。"""
    if value is None:
        return None
    raw = value.strip().replace("-", "")
    if not raw:
        return None
    if len(raw) != 8 or not raw.isdigit():
        raise ValueError(f"日期须为 YYYYMMDD 或 YYYY-MM-DD，收到 {value!r}")
    return datetime.strptime(raw, "%Y%m%d").date()


async def search_events(
    query: str | None = None,
    tags: list[str] | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    top_n: int = 10,
) -> dict:
    """按关键词/概念标签/日期检索财联社·tushare 事件库。

    query 按空格拆词 AND ILIKE title；tags 走 metadata @> JSONB 包含（OR）；
    date_from/date_to 为 YYYYMMDD 或 YYYY-MM-DD，按 Asia/Shanghai 日历日闭区间。
    query 与 tags 至少其一。
    """
    from sqlalchemy import text

    from app.core.database import async_session

    top_n = min(max(top_n, 1), 30)
    if not query and not tags:
        return {"items": [], "count": 0, "note": "请至少提供搜索关键词(query)或板块标签(tags)"}
    try:
        day_from = parse_event_day(date_from)
        day_to = parse_event_day(date_to)
    except ValueError as exc:
        return {"items": [], "count": 0, "note": str(exc)}

    conditions: list[str] = []
    params: dict = {}
    if tags:
        tag_conditions = []
        for i, tag in enumerate(tags):
            key = f"tag_{i}"
            tag_conditions.append("metadata @> :%s" % key)
            params[key] = json.dumps({"tags": [tag]}, ensure_ascii=False)
        conditions.append(f"({' OR '.join(tag_conditions)})")
    if query:
        keywords = [kw.strip() for kw in query.split() if kw.strip()]
        kw_conditions = []
        for i, kw in enumerate(keywords):
            key = f"kw_{i}"
            kw_conditions.append(f"title ILIKE :{key}")
            params[key] = f"%{kw}%"
        conditions.append(f"({' AND '.join(kw_conditions)})")
    if day_from:
        conditions.append("(publish_at AT TIME ZONE 'Asia/Shanghai')::date >= :date_from")
        params["date_from"] = day_from
    if day_to:
        conditions.append("(publish_at AT TIME ZONE 'Asia/Shanghai')::date <= :date_to")
        params["date_to"] = day_to

    sql = f"""
        SELECT event_id, title, summary, source, publish_at
        FROM events
        WHERE {' AND '.join(conditions)}
        ORDER BY publish_at DESC
        LIMIT :top_n
    """
    params["top_n"] = top_n
    async with async_session() as session:
        rows = (await session.execute(text(sql), params)).fetchall()
    items = [_event_item(r) for r in rows]
    return {"items": items, "count": len(items), "query": query, "tags": tags}


def _event_item(row: Any) -> dict:
    return {
        "event_id": row[0],
        "title": row[1],
        "summary": (row[2] or "")[:200],
        "source": row[3],
        "publish_at": str(row[4]) if row[4] else "",
    }


async def list_recent_events(limit: int = 20) -> dict:
    """最新快讯，不要求关键词。主页面滚动条用。来源含东财、华尔街见闻、同花顺、新浪滚动。"""
    from sqlalchemy import text

    from app.core.database import async_session

    limit = min(max(limit, 1), 30)
    sql = """
        SELECT event_id, title, summary, source, publish_at
        FROM events
        WHERE title IS NOT NULL AND btrim(title) <> ''
        ORDER BY publish_at DESC NULLS LAST
        LIMIT :limit
    """
    async with async_session() as session:
        rows = (await session.execute(text(sql), {"limit": limit})).fetchall()
    items = [_event_item(row) for row in rows]
    return {"items": items, "count": len(items)}


async def get_event_detail(event_id: str) -> dict:
    """事件全文。find_events 拿到 event_id 后回这里取原始内容。"""
    from sqlalchemy import text

    from app.core.database import async_session

    async with async_session() as session:
        row = (
            await session.execute(
                text("SELECT event_id, title, content, source, publish_at, metadata FROM events WHERE event_id = :eid"),
                {"eid": event_id},
            )
        ).fetchone()
    if not row:
        return {"found": False, "event_id": event_id}
    return {
        "found": True,
        "event_id": row[0],
        "title": row[1],
        "content": row[2] or "",
        "source": row[3],
        "publish_at": str(row[4]) if row[4] else "",
        "tags": (row[5] or {}).get("tags", []),
    }
