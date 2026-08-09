from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from typing import Any

import tushare as ts

from app.config import settings
from app.core.database import engine

logger = logging.getLogger(__name__)

_TUSHARE_PRO: Any = None


def _get_ts_pro():
    global _TUSHARE_PRO
    if _TUSHARE_PRO is None:
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
                    VALUES (:event_id, :title, :summary, :source, :url, :publish_at, :metadata::jsonb)
                    ON CONFLICT (event_id) DO NOTHING
                """)
                result = await conn.execute(
                    pg_stmt,
                    {
                        "event_id": eid,
                        "title": title,
                        "summary": str(row.get("content") or row.get("summary") or ""),
                        "source": "cls",
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
        pro = _get_ts_pro()
        src = settings.tushare_http_url.rstrip("/")
        tushare_ok = False
        df = None
        try:
            df = pro.news(
                src=src,
                start_date=start_date,
                end_date=end_date,
            )
            tushare_ok = True
        except Exception:
            try:
                df = pro.major_news(
                    src=src,
                    start_date=start_date,
                    end_date=end_date,
                )
                tushare_ok = True
            except Exception:
                pass

        if df is not None and not df.empty:
            return await self._save_events_from_df(df, limit)

        # Tushare 失败或空结果 → CLS 兜底
        from app.data_pipeline.data_source import DataSourceClient

        cls_records = DataSourceClient().get_cls_telegraph()
        if not cls_records:
            return {"fetched": 0, "inserted": 0, "skipped": 0}

        concept_names = await self._load_concept_names()
        inserted = 0
        skipped = 0

        async with engine.connect() as conn:
            for rec in cls_records[:limit]:
                title = str(rec.get("title") or "")
                if not title.strip():
                    skipped += 1
                    continue

                eid = stable_event_id(title)
                tags = auto_tag(title, concept_names)
                metadata = {"tags": tags} if tags else {}

                content = str(rec.get("content") or "")
                pub_date = str(rec.get("pub_date") or "")
                pub_time = str(rec.get("pub_time") or "")
                pub_datetime_str = f"{pub_date} {pub_time}".strip() if pub_date and pub_time else pub_date

                from sqlalchemy import text

                pg_stmt = text("""
                    INSERT INTO events (event_id, title, summary, source, url, publish_at, metadata)
                    VALUES (:event_id, :title, :summary, :source, :url, :publish_at, :metadata::jsonb)
                    ON CONFLICT (event_id) DO NOTHING
                """)
                result = await conn.execute(
                    pg_stmt,
                    {
                        "event_id": eid,
                        "title": title,
                        "summary": content,
                        "source": "cls",
                        "url": "",
                        "publish_at": _parse_datetime(pub_datetime_str),
                        "metadata": json.dumps(metadata, ensure_ascii=False),
                    },
                )
                if result.rowcount > 0:
                    inserted += 1
                else:
                    skipped += 1

            await conn.commit()

        return {"fetched": len(cls_records), "inserted": inserted, "skipped": skipped}


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
