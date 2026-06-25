from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any

import tushare as ts

from app.config import settings
from app.core.database import engine
from app.models.event import Event

logger = logging.getLogger(__name__)

_TUSHARE_PRO: Any = None


def _get_ts_pro():
    global _TUSHARE_PRO
    if _TUSHARE_PRO is None:
        ts.set_token(settings.tushare_token)
        _TUSHARE_PRO = ts.pro_api()
    return _TUSHARE_PRO


def stable_event_id(title: str) -> str:
    raw = (title or "").strip()[:16]
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
        from app.models.models import ThsConcept
        from sqlalchemy import select
        async with engine.connect() as conn:
            result = await conn.execute(select(ThsConcept.name))
            names = [r[0] for r in result.fetchall()]
        self._concept_names = names
        return names

    async def fetch_and_save(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = 200,
    ) -> dict[str, int]:
        pro = _get_ts_pro()
        src = settings.tushare_http_url.rstrip("/")
        try:
            df = pro.news(
                src=src,
                start_date=start_date,
                end_date=end_date,
            )
        except Exception:
            df = pro.major_news(
                src=src,
                start_date=start_date,
                end_date=end_date,
            )

        if df is None or df.empty:
            return {"fetched": 0, "inserted": 0, "skipped": 0}

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
                    VALUES (:event_id, :title, :summary, :source, :url, :publish_at, :metadata::jsonb)
                    ON CONFLICT (event_id) DO NOTHING
                """)
                result = await conn.execute(pg_stmt, {
                    "event_id": eid,
                    "title": title,
                    "summary": str(row.get("content") or row.get("summary") or ""),
                    "source": "cls",
                    "url": str(row.get("url") or ""),
                    "publish_at": publish_at,
                    "metadata": str(metadata).replace("'", '"'),
                })
                if result.rowcount > 0:
                    inserted += 1
                else:
                    skipped += 1

            await conn.commit()

        return {"fetched": len(df), "inserted": inserted, "skipped": skipped}


def _parse_datetime(val: Any) -> datetime:
    if isinstance(val, datetime):
        return val
    if isinstance(val, str):
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(val, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    return datetime.now(timezone.utc)


_news_service: NewsService | None = None


def get_news_service() -> NewsService:
    global _news_service
    if _news_service is None:
        _news_service = NewsService()
    return _news_service
