#!/usr/bin/env python3
"""解析 minishare 与 cninfo 文件 ID 不一致的历史公告，补真实 PDF 直链。

背景：部分历史公告 minishare 返回的 announcementId 与 cninfo static 文件 ID
不一致（如 2024 半年报 1221007078 vs 真实 1221355838），导致 404。
本脚本按 (ts_code, ann_date) 调 cninfo hisAnnouncement/query，按标题匹配
adjunctUrl，回写 source_url 并重新入队 pdf_download。

用法：
    python resolve_ann_urls.py --dry-run
    python resolve_ann_urls.py
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import time
import urllib.parse
import urllib.request
from datetime import date, timedelta

from sqlalchemy import text

from app.core.database import engine
from app.data_pipeline.fetcher import normalize_cninfo_pdf_url
from app.data_pipeline.job_queue import IngestionJobQueue, JOB_PDF_DOWNLOAD
from app.data_pipeline.minishare_client import DataSourceClientMinishare
from app.data_pipeline.pdf_download_contract import PdfDownloadJobPayload

CNINFO_QUERY = "http://www.cninfo.com.cn/new/hisAnnouncement/query"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "http://www.cninfo.com.cn/new/commonUrl?url=disclosure/list/notice",
    "X-Requested-With": "XMLHttpRequest",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
}


def norm_title(t: str) -> str:
    return re.sub(r"[\s\u3000:：()（）\[\]【】\-—_]", "", t or "")


def safe_title(title: str) -> str:
    return re.sub(r'[\\\\/:*?\"<>| ]', "_", title)[:60]


def query_cninfo(code: str, org_id: str, ds: date) -> list[dict]:
    exchange = code.split(".")[-1].upper()
    column, plate = ("sse", "sh") if exchange == "SH" else ("szse", "sz")
    start = (ds - timedelta(days=3)).strftime("%Y-%m-%d")
    end = (ds + timedelta(days=3)).strftime("%Y-%m-%d")
    data = urllib.parse.urlencode(
        {
            "pageNum": 1,
            "pageSize": 50,
            "column": column,
            "tabName": "fulltext",
            "plate": plate,
            "stock": f"{code.split('.')[0]},{org_id}",
            "searchkey": "",
            "secid": "",
            "category": "",
            "trade": "",
            "seDate": f"{start}~{end}",
            "sortName": "",
            "sortType": "",
            "isHLtitle": "true",
        }
    ).encode()
    req = urllib.request.Request(CNINFO_QUERY, data=data, headers=HEADERS, method="POST")
    with urllib.request.urlopen(req, timeout=25) as resp:
        payload = json.loads(resp.read().decode("utf-8", "replace"))
    return payload.get("announcements") or []


def org_id_from_detail(url: str) -> str:
    try:
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        return (qs.get("orgId") or [""])[0]
    except Exception:
        return ""


async def main(dry_run: bool) -> None:
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    """
                    SELECT id, ann_date, ts_code, title, source_url
                    FROM minishare_announcements
                    WHERE download_status='pending'
                    ORDER BY ann_date, ts_code
                    """
                )
            )
        ).mappings().all()
    print(f"pending rows = {len(rows)}")

    groups: dict[tuple[str, date], list] = {}
    for r in rows:
        groups.setdefault((r["ts_code"], r["ann_date"]), []).append(r)

    client = DataSourceClientMinishare()
    queue = IngestionJobQueue()
    matched = failed = 0
    for (code, ds), items in groups.items():
        ds_str = ds.strftime("%Y%m%d")
        try:
            detail = client.get_announcements(ts_code=code, start_date=ds_str, end_date=ds_str)
        except Exception as exc:  # noqa: BLE001
            print(f"{code} {ds} minishare ERR {str(exc)[:100]}")
            failed += len(items)
            continue
        org_id = next((org_id_from_detail(x.get("url", "")) for x in detail if org_id_from_detail(x.get("url", ""))), "")
        if not org_id:
            print(f"{code} {ds} no orgId, skip {len(items)}")
            failed += len(items)
            continue
        try:
            anns = query_cninfo(code, org_id, ds)
        except Exception as exc:  # noqa: BLE001
            print(f"{code} {ds} cninfo ERR {str(exc)[:100]}")
            failed += len(items)
            await asyncio.sleep(1.5)
            continue

        by_title = {norm_title(a.get("announcementTitle", "")): a for a in anns}
        for r in items:
            hit = by_title.get(norm_title(r["title"]))
            if not hit:
                # 容错：标题包含匹配（唯一命中才算）
                cands = [a for k, a in by_title.items() if norm_title(r["title"]) in k or k in norm_title(r["title"])]
                hit = cands[0] if len(cands) == 1 else None
            if not hit:
                print(f"  MISS {code} {ds} {r['title'][:30]}")
                failed += 1
                continue
            static = "http://static.cninfo.com.cn/" + str(hit["adjunctUrl"]).lstrip("/")
            print(f"  HIT  {code} {ds} {r['title'][:26]} -> {static.rsplit('/', 1)[-1]}")
            matched += 1
            if dry_run:
                continue
            async with engine.begin() as conn:
                await conn.execute(
                    text("UPDATE minishare_announcements SET source_url=:u WHERE id=:i"),
                    {"u": static, "i": r["id"]},
                )
            sid = f"{ds_str}_{code}_{safe_title(r['title'])}"
            payload = PdfDownloadJobPayload(
                source_url=static,
                source_type="minishare_announcements",
                source_id=sid,
                stock_code=code,
                publish_date=ds,
                filename=f"{ds.isoformat()}_{code}_{sid}.pdf",
            )
            await queue.enqueue_job(
                JOB_PDF_DOWNLOAD, payload.job_key, payload.to_payload(), priority=25, max_attempts=8
            )
        await asyncio.sleep(1.5)

    print(f"matched={matched} failed={failed} dry_run={dry_run}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    asyncio.run(main(ap.parse_args().dry_run))
