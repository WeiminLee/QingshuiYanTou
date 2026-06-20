#!/usr/bin/env python3
"""
Minishare 公告历史数据回补脚本

从 minishare 接口逐日拉取全市场公告，关键词过滤后下载 PDF 并入库。

数据流：
1. 按天调 minishare anns_d API 获取某天全市场公告
2. 关键词过滤 (announcement_filter.classify_title)
3. URL 归一化：直接 PDF 链接直接下载 / 详情页链接调 cninfo API 解析后下载
4. 元数据入库 (announcements 表 + minishare_announcements 表)
5. 断点续跑 (IngestionProgressTracker + last_success_watermark)

用法:
    python -m scripts.sync_minishare_ann_history [--start-date YYYYMMDD] [--end-date YYYYMMDD]

示例:
    # 回补 2023-01-01 至今
    python -m scripts.sync_minishare_ann_history --start-date 20230101

    # 回补指定日期范围
    python -m scripts.sync_minishare_ann_history --start-date 20230101 --end-date 20260615
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import logging
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# 添加 backend 到 path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.database import engine
from app.data_pipeline.announcement_filter import (
    DOC_TYPE_SAVE as ANN_DOC_TYPE_SAVE,
    classify_title as classify_ann_title,
)
from app.data_pipeline.file_storage import FileStorage
from app.data_pipeline.minishare_client import DataSourceClientMinishare
from app.data_pipeline.rate_limiter import get_cninfo_pdf_async_limiter, get_minishare_async_limiter
from app.data_pipeline.progress import (
    FAILED,
    PARTIAL,
    SUCCESS,
    IngestionProgressTracker,
)
from app.models.models import Announcement

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# 常量
ANN_PROGRESS_EVERY = 30  # 每 30 天打印一次进度


# ── 辅助函数 ────────────────────────────────────────────


def _stable_id(prefix: str, *parts: str) -> str:
    """生成确定性唯一 ID（进程重启后不变）。"""
    raw = "".join(str(p) for p in parts).encode("utf-8", errors="replace")
    return f"{prefix}_{hashlib.sha1(raw).hexdigest()[:16]}"


def generate_cninfo_id(ts_code: str, ann_date: str, title: str, ann_id_suffix: str = "") -> str:
    """为公告生成唯一 cninfo_id。

    优先使用公告唯一标识（ann_id_suffix），否则 fallback 到 hash。
    """
    if ann_id_suffix:
        return f"ann_{ts_code}_{ann_date}_{ann_id_suffix}"
    return _stable_id("ann", ts_code, ann_date, title)


def classify_url_type(url: str) -> str:
    """判断 URL 类型：direct_pdf / detail_page / unknown"""
    if not url or not url.strip():
        return "unknown"
    url = url.strip()
    if 'finalpage' in url and url.lower().endswith('.pdf'):
        return "direct_pdf"
    if 'cninfo.com.cn' in url and 'detail' in url:
        return "detail_page"
    return "unknown"


def format_duration(seconds: int) -> str:
    """格式化持续时间为 HH:MM:SS"""
    h, remainder = divmod(seconds, 3600)
    m, s = divmod(remainder, 60)
    return f"{h}:{m:02d}:{s:02d}"


# ── 核心同步逻辑 ────────────────────────────────────────


async def _batch_insert_announcements(
    conn,
    records: list[dict],
    date_str: str,
) -> tuple[int, int]:
    """批量 INSERT 公告元数据，file_path = NULL，不下载 PDF。

    Returns:
        (inserted_count, skipped_by_conflict_count)
    """
    if not records:
        return 0, 0

    from urllib.parse import parse_qs, urlparse

    values = []
    for rec in records:
        ann_date_str = str(rec.get("ann_date") or date_str)
        try:
            parsed_date = datetime.strptime(ann_date_str, "%Y%m%d").date()
        except ValueError:
            continue
        ann_url = str(rec.get("url") or "")
        ann_id_suffix = ""
        if ann_url and 'announcementId=' in ann_url:
            parsed_url = urlparse(ann_url)
            qs = parse_qs(parsed_url.query)
            ann_id_suffix = qs.get('announcementId', [None])[0] or ""
        cninfo_id = generate_cninfo_id(
            str(rec.get("ts_code") or ""),
            ann_date_str,
            str(rec.get("title") or ""),
            ann_id_suffix,
        )
        values.append({
            "ann_date": parsed_date,
            "ts_code": str(rec.get("ts_code") or ""),
            "name": str(rec.get("name") or ""),
            "title": str(rec.get("title") or "")[:500],
            "type": None,
            "cninfo_id": cninfo_id,
            "announcement_type": rec.get("doc_type", "other"),
            "source_type": "minishare",
            "source_name": "minishare_anns",
            "confidence_tier": "Tier1",
            "file_path": None,
            "pdf_url": ann_url or None,
        })

    stmt = pg_insert(Announcement.__table__).values(values)
    # 使用 (ts_code, ann_date, title) 唯一约束去重，而非 cninfo_id
    # 因为 minishare 同一标题 + 同一天可能有多条不同 announcementId 的记录，
    # 但 (ts_code, ann_date, title) 约束更严格且已存在
    stmt = stmt.on_conflict_do_nothing(
        index_elements=["ts_code", "ann_date", "title"]
    )
    try:
        result = await conn.execute(stmt)
        inserted = result.rowcount if result.rowcount else 0
        skipped = len(values) - inserted
        return inserted, skipped
    except Exception:
        # 极端情况下某些冲突导致整批失败，降级为逐条插入
        inserted = skipped = 0
        for v in values:
            try:
                r = await conn.execute(
                    pg_insert(Announcement.__table__).values([v]).on_conflict_do_nothing(
                        index_elements=["ts_code", "ann_date", "title"]
                    )
                )
                if r.rowcount and r.rowcount > 0:
                    inserted += 1
                else:
                    skipped += 1
            except Exception:
                skipped += 1
        return inserted, skipped


async def _get_pending_downloads(conn, date_str: str) -> list[dict]:
    """查询当天需要下载 PDF 的记录（file_path IS NULL 且有关键词类型）。"""
    result = await conn.execute(
        text("""
            SELECT cninfo_id, ts_code, name, title, pdf_url
            FROM announcements
            WHERE ann_date = :ann_date
              AND file_path IS NULL
              AND pdf_url IS NOT NULL
              AND announcement_type IN (
                  'half_report', 'quarter_report', 'annual_report',
                  'research_survey', 'ma_activity', 'investment'
              )
        """),
        {"ann_date": datetime.strptime(date_str, "%Y%m%d").date()},
    )
    return [dict(row) for row in result.mappings()]


async def _concurrent_download(
    pending: list[dict],
    storage: FileStorage,
    date_str: str,
) -> tuple[int, int, list[dict]]:
    """异步并发下载 PDF。

    Returns:
        (downloaded_count, fail_count, updates_list)
        updates_list 每项: {"cninfo_id": str, "file_path": Path}
    """
    if not pending:
        return 0, 0, []

    pdf_limiter = get_cninfo_pdf_async_limiter()
    sem = asyncio.Semaphore(5)

    async def _download_one(item: dict) -> dict | None:
        cninfo_id = item["cninfo_id"]
        safe_title = (item.get("title") or "")[:60] or "untitled"
        filename = f"{cninfo_id}_{safe_title}.pdf"

        async with sem:
            await pdf_limiter.wait_and_acquire()
            try:
                file_path = await storage.download_notice_async(
                    url=item["pdf_url"],
                    ts_code=item.get("ts_code") or "_invalid",
                    filename=filename,
                    pub_date=date_str,
                )
            except Exception as e:
                logger.warning("下载异常 [%s]: %s", cninfo_id, e)
                return None

            if file_path is not None:
                return {"cninfo_id": cninfo_id, "file_path": file_path}
            return None

    tasks = [_download_one(item) for item in pending]
    results = await asyncio.gather(*tasks, return_exceptions=False)

    updates = [r for r in results if r is not None]
    downloaded = len(updates)
    fail_count = len(pending) - downloaded
    return downloaded, fail_count, updates


async def _batch_update_file_paths(conn, updates: list[dict]) -> int:
    """逐条回写 file_path（批量中对少量记录，逐条足够快）。"""
    count = 0
    for u in updates:
        r = await conn.execute(
            text("UPDATE announcements SET file_path = :fp WHERE cninfo_id = :cid"),
            {"fp": str(u["file_path"]), "cid": u["cninfo_id"]},
        )
        if r.rowcount:
            count += 1
    return count


async def sync_day(
    date_str: str,
    minishare_client: DataSourceClientMinishare,
    storage: FileStorage,
    tracker: IngestionProgressTracker,
    run_ctx: Any,
) -> dict[str, int]:
    """两阶段同步单天公告数据：先批量 INSERT 元数据，再并发下载 PDF。

    Returns:
        {"success", "skipped_by_filter", "skipped_dup", "downloaded", "fail"}
    """

    ann_limiter = get_minishare_async_limiter("anns_d")

    # 1. 获取当天全量公告
    await ann_limiter.wait_and_acquire()
    records = await asyncio.to_thread(
        minishare_client.get_announcements,
        ann_date=date_str,
    )
    if not records:
        return {"success": 0, "skipped_by_filter": 0, "skipped_dup": 0, "downloaded": 0, "fail": 0}

    # 2. 关键词过滤
    batch_records = []
    filter_skipped = 0
    for rec in records:
        title = str(rec.get("title") or "").strip()
        if not title:
            filter_skipped += 1
            continue
        doc_type, action = classify_ann_title(title)
        if action != ANN_DOC_TYPE_SAVE:
            filter_skipped += 1
            continue
        rec["doc_type"] = doc_type
        batch_records.append(rec)

    # 3. 阶段一：批量 INSERT 元数据（不下载 PDF）
    inserted = 0
    skipped_dup = 0
    if batch_records:
        async with engine.begin() as conn:
            inserted, skipped_dup = await _batch_insert_announcements(
                conn, batch_records, date_str,
            )

    # 每天总交易日志量
    n_records = len(records)
    n_filtered = len(batch_records)

    # 4. 阶段二：查询待下载记录 + 并发下载 PDF
    downloaded = 0
    fail_download = 0
    if inserted > 0 or skipped_dup > 0:
        async with engine.connect() as conn:
            pending = await _get_pending_downloads(conn, date_str)

        if pending:
            downloaded, fail_download, updates = await _concurrent_download(
                pending, storage, date_str,
            )
            # 回写 file_path
            if updates:
                async with engine.begin() as conn:
                    await _batch_update_file_paths(conn, updates)

    return {
        "success": inserted,
        "skipped_by_filter": filter_skipped,
        "skipped_dup": skipped_dup,
        "downloaded": downloaded,
        "fail": fail_download,
    }


async def main(start_date_str: str | None = None, end_date_str: str | None = None):
    """主函数：按日期范围逐日回补公告数据"""

    start_time = time.time()
    today = datetime.now()
    end_date = datetime.strptime(end_date_str, "%Y%m%d") if end_date_str else today
    start_date = datetime.strptime(start_date_str, "%Y%m%d") if start_date_str else (today - timedelta(days=730))

    start_str = start_date.strftime("%Y%m%d")
    end_str = end_date.strftime("%Y%m%d")

    print(f"{'=' * 65}")
    print(f"  Minishare 公告历史回补")
    print(f"{'=' * 65}")
    print(f"  日期范围: {start_str} ~ {end_str}")
    print(f"  开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    # 初始化依赖
    minishare_client = DataSourceClientMinishare()
    if not minishare_client.anns_available:
        print("错误: minishare 公告 token 未配置")
        return {"total_days": 0, "success": 0, "skipped": 0, "downloaded": 0, "fail": 0}

    storage = FileStorage()

    # 初始化进度追踪器
    tracker = IngestionProgressTracker(
        source="minishare_ann",
        task_name="ann_history",
        scope=f"{start_str}_{end_str}",
    )
    await tracker.ensure_tables()

    # 断点续跑
    checkpoint = await tracker.get_checkpoint()
    resume_start = start_str
    if checkpoint and checkpoint.get("last_success_watermark"):
        resume_date = checkpoint["last_success_watermark"]
        resume_next = (datetime.strptime(resume_date, "%Y%m%d") + timedelta(days=1)).strftime("%Y%m%d")
        if resume_next <= end_str:
            resume_start = resume_next
            print(f"  检测到断点: 从 {resume_start} 继续（已完成 {resume_date}）")
    print()

    run_ctx = await tracker.start_run(
        from_watermark=resume_start,
        to_watermark=end_str,
        metadata={"source": "minishare"},
    )

    # 逐日遍历
    current = datetime.strptime(resume_start, "%Y%m%d")
    end = datetime.strptime(end_str, "%Y%m%d")
    total_days = 0
    total_success = total_skipped = total_downloaded = total_fail = 0
    last_success_date = resume_start

    print(f"  开始同步...")
    print()

    while current <= end:
        date_str = current.strftime("%Y%m%d")
        total_days += 1

        result = await sync_day(date_str, minishare_client, storage, tracker, run_ctx)

        total_success += result["success"]
        total_skipped += result["skipped_by_filter"] + result["skipped_dup"]
        total_downloaded += result["downloaded"]
        total_fail += result["fail"]
        last_success_date = date_str

        # 更新 checkpoint
        await tracker.save_checkpoint(
            last_success_watermark=date_str,
            last_success_at=datetime.now(timezone.utc),
            last_status="running",
        )
        await tracker.update_run(
            run_ctx,
            current_watermark=date_str,
            total_items=total_days,
            processed_items=total_days,
            success_count=total_success,
            skipped_count=total_skipped,
            downloaded_count=total_downloaded,
            fail_count=total_fail,
        )

        # 进度显示
        if total_days % ANN_PROGRESS_EVERY == 0 or current >= end:
            elapsed = int(time.time() - start_time)
            print(f"  [{date_str}] 进度 {total_days} 天 | "
                  f"入库 {total_success} | 下载 {total_downloaded} | "
                  f"跳过 {total_skipped} | 失败 {total_fail} | "
                  f"耗时 {format_duration(elapsed)}")

        current += timedelta(days=1)

    # 完成
    await tracker.finish_run(
        run_ctx,
        status=SUCCESS if total_fail == 0 else PARTIAL,
        total_items=total_days,
        processed_items=total_days,
        success_count=total_success,
        skipped_count=total_skipped,
        downloaded_count=total_downloaded,
        fail_count=total_fail,
        current_watermark=last_success_date,
        last_item_id=last_success_date,
    )

    elapsed = int(time.time() - start_time)
    print()
    print(f"{'=' * 65}")
    print(f"  同步完成!")
    print(f"{'=' * 65}")
    print(f"  总天数:     {total_days}")
    print(f"  新增入库:   {total_success} 条")
    print(f"  已下载 PDF: {total_downloaded} 个")
    print(f"  跳过/重复:  {total_skipped} 条")
    print(f"  失败:       {total_fail} 条")
    print(f"  总耗时:     {format_duration(elapsed)}")
    print(f"  完成时间:   {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    return {
        "total_days": total_days,
        "success": total_success,
        "skipped": total_skipped,
        "downloaded": total_downloaded,
        "fail": total_fail,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Minishare 公告历史回补")
    parser.add_argument("--start-date", help="起始日期 YYYYMMDD (默认: 2年前)")
    parser.add_argument("--end-date", help="结束日期 YYYYMMDD (默认: 今天)")
    args = parser.parse_args()

    asyncio.run(main(args.start_date, args.end_date))
