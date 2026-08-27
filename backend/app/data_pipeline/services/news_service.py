from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import UTC, datetime
from typing import Any

from app.config import settings
from app.core.database import engine

logger = logging.getLogger(__name__)

_TUSHARE_PRO: Any = None


def _get_ts_pro():
    global _TUSHARE_PRO
    if _TUSHARE_PRO is None:
        import tinyshare as ts

        ts.set_token(settings.tushare_token)
        _TUSHARE_PRO = ts.pro_api()
    return _TUSHARE_PRO


def stable_event_id(title: str) -> str:
    raw = (title or "").strip()
    return f"EV:{hashlib.sha256(raw.encode()).hexdigest()[:16]}"


def auto_tag(title: str, concept_names: list[str]) -> list[str]:
    tags = []
    for name in concept_names:
        if name in title:
            tags.append(name)
    return tags


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

        async with engine.connect() as conn:
            for _, row in df.head(limit).iterrows():
                title = str(row.get("title") or "")
                if not title.strip():
                    skipped += 1
                    continue

                eid = stable_event_id(title)
                tags = auto_tag(title, concept_names)
                metadata = {"tags": tags} if tags else {}

                publish_at = _parse_datetime(row.get("pub_time") or row.get("datetime") or "")

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
                        "summary": str(row.get("content") or row.get("summary") or ""),
                        "source": "tushare",
                        "url": str(row.get("url") or ""),
                        "publish_at": publish_at,
                        "metadata": json.dumps(metadata, ensure_ascii=False),
                    },
                )
                if result.rowcount > 0:
                    inserted += 1
                else:
                    skipped += 1

            await conn.commit()

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

        if df is not None and not df.empty:
            return await self._save_events_from_df(df, limit)

        # 兜底：东方财富 7x24 快讯（纯 HTTP + 30s 超时，不依赖 akshare / news 接口权限）
        records = await asyncio.to_thread(self._fetch_eastmoney_flash, limit)
        return await self._save_flash_records(records, limit)

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

    async def _save_flash_records(
        self,
        records: list[dict[str, str]],
        limit: int,
    ) -> dict[str, int]:
        """将 HTTP 快讯记录写入 events 表（按 title 去重）。"""
        concept_names = await self._load_concept_names()
        inserted = skipped = 0

        from sqlalchemy import text

        async with engine.connect() as conn:
            for rec in records[:limit]:
                title = rec.get("title") or ""
                if not title:
                    skipped += 1
                    continue
                eid = stable_event_id(title)
                tags = auto_tag(title, concept_names)
                metadata = {"tags": tags} if tags else {}
                publish_at = _parse_datetime(rec.get("publish_at") or "")
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
                        "summary": rec.get("summary") or "",
                        "source": "eastmoney_flash",
                        "url": rec.get("url") or "",
                        "publish_at": publish_at,
                        "metadata": json.dumps(metadata, ensure_ascii=False),
                    },
                )
                if result.rowcount > 0:
                    inserted += 1
                else:
                    skipped += 1
            await conn.commit()
        return {"fetched": len(records), "inserted": inserted, "skipped": skipped}


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
