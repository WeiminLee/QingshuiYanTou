#!/usr/bin/env python3
"""
下载缺失的 PDF 文件

从数据库查询有 pdf_url 但没有 file_path 的记录，重试下载。
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

import psycopg2

# 添加 backend 到 path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.data_pipeline.file_storage import FileStorage
from app.data_pipeline.rate_limiter import get_cninfo_pdf_async_limiter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# 目标公告类型（需要下载 PDF 的）
TARGET_TYPES = (
    "annual_report",
    "half_report",
    "quarter_report",
    "research_survey",
    "ma_activity",
    "investment",
)


def get_db_connection():
    """获取数据库连接"""
    return psycopg2.connect(host="localhost", port=5433, database="qingshui", user="qingshui", password="qingshui123")


def get_pending_downloads(conn, limit: int = 10000):
    """获取待下载记录"""
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT cninfo_id, ts_code, name, title, pdf_url, ann_date
        FROM announcements
        WHERE announcement_type IN %s
          AND source_type = 'minishare'
          AND (file_path IS NULL OR file_path = '')
          AND pdf_url IS NOT NULL AND pdf_url != ''
        ORDER BY ann_date DESC
        LIMIT %s
    """,
        (TARGET_TYPES, limit),
    )

    results = cursor.fetchall()
    cursor.close()
    return results


async def download_one(item, storage, pdf_limiter, sem):
    """下载单个 PDF"""
    cninfo_id, ts_code, name, title, pdf_url, ann_date = item
    safe_title = (title or "untitled")[:60] or "untitled"
    filename = f"{cninfo_id}_{safe_title}.pdf"
    date_str = ann_date.strftime("%Y%m%d") if ann_date else "unknown"

    async with sem:
        await pdf_limiter.wait_and_acquire()
        try:
            file_path = await storage.download_notice_async(
                url=pdf_url,
                ts_code=ts_code or "_invalid",
                filename=filename,
                pub_date=date_str,
            )
            return (cninfo_id, file_path) if file_path else (cninfo_id, None)
        except Exception as e:
            logger.warning("下载失败 [%s]: %s", cninfo_id, e)
            return (cninfo_id, None)


async def batch_download(items, storage, batch_size: int = 50):
    """批量下载"""
    pdf_limiter = get_cninfo_pdf_async_limiter()
    sem = asyncio.Semaphore(10)  # 并发数

    all_results = []

    for i in range(0, len(items), batch_size):
        batch = items[i : i + batch_size]
        tasks = [download_one(item, storage, pdf_limiter, sem) for item in batch]
        results = await asyncio.gather(*tasks, return_exceptions=False)
        all_results.extend(results)

        # 打印进度
        downloaded = sum(1 for _, fp in all_results if fp)
        logger.info(f"进度: {i + len(batch)}/{len(items)}, 成功: {downloaded}")

    return all_results


def update_file_paths(conn, updates):
    """更新数据库中的 file_path"""
    cursor = conn.cursor()
    updated = 0

    for cninfo_id, file_path in updates:
        if file_path:
            cursor.execute(
                """
                UPDATE announcements
                SET file_path = %s
                WHERE cninfo_id = %s
            """,
                (str(file_path), cninfo_id),
            )
            updated += cursor.rowcount

    conn.commit()
    cursor.close()
    return updated


async def main(limit: int = 10000, batch_size: int = 50):
    """主函数"""
    print(f"{'=' * 60}")
    print("  下载缺失的 PDF 文件")
    print(f"{'=' * 60}")
    print(f"  待下载限制: {limit}")
    print(f"  批处理大小: {batch_size}")
    print(f"  开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    start_time = time.time()

    # 初始化存储
    storage = FileStorage()

    # 从数据库获取待下载记录
    conn = get_db_connection()
    items = get_pending_downloads(conn, limit)
    conn.close()

    if not items:
        print("没有待下载的记录")
        return

    print(f"获取到 {len(items)} 条待下载记录")
    print()

    # 批量下载
    results = await batch_download(items, storage, batch_size)

    # 统计结果
    successful = [(cid, fp) for cid, fp in results if fp]
    failed = len(results) - len(successful)

    # 更新数据库
    conn = get_db_connection()
    updated = update_file_paths(conn, successful)
    conn.close()

    elapsed = int(time.time() - start_time)

    print()
    print(f"{'=' * 60}")
    print("  下载完成!")
    print(f"{'=' * 60}")
    print(f"  总数:       {len(results)}")
    print(f"  成功:       {len(successful)}")
    print(f"  失败:       {failed}")
    print(f"  数据库更新: {updated}")
    print(f"  总耗时:     {elapsed} 秒")
    print(f"  完成时间:  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="下载缺失的 PDF 文件")
    parser.add_argument("--limit", type=int, default=15000, help="最大下载数量")
    parser.add_argument("--batch-size", type=int, default=50, help="批处理大小")
    args = parser.parse_args()

    asyncio.run(main(args.limit, args.batch_size))
