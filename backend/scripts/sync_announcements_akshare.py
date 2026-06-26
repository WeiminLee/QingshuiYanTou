#!/usr/bin/env python3
"""
历史公告同步脚本 (akshare 版)

使用 akshare 的 stock_zh_a_disclosure_report_cninfo 接口获取全市场个股公告。
该接口可以获取单只股票完整的历史公告记录。

用法:
    python -m scripts.sync_announcements_akshare [--batch-size N]
"""

import argparse
import asyncio
import sys
from datetime import datetime, timedelta
from pathlib import Path

# 添加 backend 到 path
sys.path.insert(0, str(Path(__file__).parent.parent))

import akshare as ak
from sqlalchemy import text

from app.core.database import engine
from app.data_pipeline.rate_limiter import get_akshare_limiter


async def save_announcement(
    cninfo_id: str,
    ann_date: str,
    ts_code: str,
    name: str,
    title: str,
    pdf_url: str | None = None,
) -> bool:
    """保存单条公告到数据库"""
    sql = """
    INSERT INTO announcements (
        ann_date, ts_code, name, title,
        cninfo_id, announcement_type,
        source_type, source_name, confidence_tier, pdf_url
    ) VALUES (
        :ann_date, :ts_code, :name, :title,
        :cninfo_id, :announcement_type,
        :source_type, :source_name, :confidence_tier, :pdf_url
    )
    ON CONFLICT (cninfo_id) DO NOTHING
    """
    try:
        from datetime import date as date_type

        if len(ann_date) >= 10:
            d = datetime.strptime(ann_date[:10], "%Y-%m-%d")
            parsed_date = date_type(d.year, d.month, d.day)
        else:
            return False
    except Exception:
        return False

    try:
        async with engine.begin() as conn:
            result = await conn.execute(
                text(sql),
                {
                    "ann_date": parsed_date,
                    "ts_code": ts_code or None,
                    "name": name or None,
                    "title": (title or "")[:500],
                    "cninfo_id": cninfo_id,
                    "announcement_type": "disclosure",
                    "source_type": "cninfo_akshare",
                    "source_name": "巨潮-Akshare",
                    "confidence_tier": "Tier1",
                    "pdf_url": pdf_url,
                },
            )
        return result.rowcount > 0 if result.rowcount else False
    except Exception:
        return False


def fetch_stock_announcements(symbol: str, start_date: str, end_date: str) -> list[dict]:
    """获取单只股票的公告（同步函数，供 asyncio.to_thread 调用）

    Args:
        symbol: 6 位股票代码
        start_date: 起始日期 YYYYMMDD
        end_date: 结束日期 YYYYMMDD
    """
    try:
        # 限速
        get_akshare_limiter().wait_and_acquire()

        df = ak.stock_zh_a_disclosure_report_cninfo(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
        )

        if df is None or df.empty:
            return []

        # 处理列名
        results = []
        for _, row in df.iterrows():
            # 从 URL 中提取 announcementId
            url = str(row.get("公告链接", ""))
            cninfo_id = None
            if "announcementId=" in url:
                try:
                    cninfo_id = url.split("announcementId=")[1].split("&")[0]
                except Exception:
                    cninfo_id = None
            if not cninfo_id:
                # 使用行索引作为备用
                cninfo_id = f"{symbol}_{row.name}"

            ann_date = str(row.get("公告时间", ""))

            # 判断交易所
            if symbol.startswith("6"):
                ts_code = f"{symbol}.SH"
            elif symbol.startswith(("0", "3")):
                ts_code = f"{symbol}.SZ"
            elif symbol.startswith("8") or symbol.startswith("4"):
                ts_code = f"{symbol}.BJ"
            else:
                ts_code = f"{symbol}.SZ"

            results.append(
                {
                    "cninfo_id": cninfo_id,
                    "ann_date": ann_date,
                    "ts_code": ts_code,
                    "name": str(row.get("简称", "")),
                    "title": str(row.get("公告标题", "")),
                    "pdf_url": url,
                }
            )

        return results
    except Exception:
        return []


async def get_existing_count() -> int:
    """获取已入库公告数量"""
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT COUNT(*) FROM announcements WHERE source_type = 'cninfo_akshare'"))
            return result.scalar() or 0
    except Exception:
        return 0


async def main(batch_size: int = 50, start_date: str | None = None, end_date: str | None = None):
    """主函数"""
    # 默认日期范围：过去2年
    if end_date is None:
        end_date = datetime.now().strftime("%Y%m%d")
    if start_date is None:
        start_date = (datetime.now() - timedelta(days=730)).strftime("%Y%m%d")

    print(f"{'=' * 60}")
    print("历史公告同步任务 (akshare)")
    print(f"{'=' * 60}")
    print(f"日期范围: {start_date} ~ {end_date}")

    # 获取股票列表
    print("获取股票列表...")
    from app.data_pipeline.data_source import DataSourceClient

    ds = DataSourceClient()
    stocks = ds.get_stocks_basic("L")
    ts_codes = [(s["ts_code"], s["ts_code"].split(".")[0]) for s in stocks if s.get("ts_code")]
    print(f"获取到 {len(ts_codes)} 只股票")

    # 白名单过滤：scope=tech_mvp 时仅同步白名单股票公告
    from app.data_pipeline.backfill_config import load_backfill_settings

    bf_cfg = load_backfill_settings()
    if bf_cfg.scope == "tech_mvp" and bf_cfg.ts_codes:
        before = len(ts_codes)
        ts_codes = [(tc, sym) for tc, sym in ts_codes if tc in bf_cfg.ts_codes]
        print(f"backfill scope=tech_mvp, {len(ts_codes)}/{before} 命中白名单")

    # 获取已有公告数
    existing = await get_existing_count()
    print(f"当前已入库 (akshare): {existing} 条")
    print()

    # 统计
    total_processed = 0
    total_saved = 0
    total_skipped = 0
    total_errors = 0
    start_time = datetime.now()

    print("开始同步...")
    print("-" * 60)

    for i in range(0, len(ts_codes), batch_size):
        batch = ts_codes[i : i + batch_size]
        batch_num = i // batch_size + 1
        total_batches = (len(ts_codes) + batch_size - 1) // batch_size

        batch_saved = 0
        batch_errors = 0

        for ts_code, symbol in batch:
            try:
                announcements = await asyncio.to_thread(fetch_stock_announcements, symbol, start_date, end_date)

                for ann in announcements:
                    ok = await save_announcement(
                        cninfo_id=ann["cninfo_id"],
                        ann_date=ann["ann_date"],
                        ts_code=ann["ts_code"],
                        name=ann["name"],
                        title=ann["title"],
                        pdf_url=ann["pdf_url"],
                    )
                    if ok:
                        batch_saved += 1
                        total_saved += 1
                    else:
                        total_skipped += 1

                total_processed += 1

            except Exception:
                total_errors += 1
                batch_errors += 1

        # 打印进度
        elapsed = (datetime.now() - start_time).total_seconds()
        rate = total_processed / elapsed if elapsed > 0 else 0
        eta = (len(ts_codes) - total_processed) / rate / 60 if rate > 0 else 0

        if batch_num % 5 == 1 or batch_num == total_batches:
            print(
                f"批次 {batch_num:4d}/{total_batches}: "
                f"处理 {total_processed}/{len(ts_codes)} | "
                f"新增 {total_saved} | "
                f"跳过 {total_skipped} | "
                f"耗时 {elapsed / 60:.1f}min | "
                f"剩余 ~{eta:.1f}min"
            )

    elapsed = (datetime.now() - start_time).total_seconds()

    print()
    print(f"{'=' * 60}")
    print("同步完成!")
    print(f"{'=' * 60}")
    print(f"处理股票: {total_processed}/{len(ts_codes)}")
    print(f"新增公告: {total_saved} 条")
    print(f"跳过/重复: {total_skipped} 条")
    print(f"错误: {total_errors}")
    print(f"总耗时: {elapsed / 60:.1f} 分钟")
    print(f"日期范围: {start_date} ~ {end_date}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="历史公告同步 (akshare)")
    parser.add_argument("--batch-size", type=int, default=50, help="每批处理股票数")
    parser.add_argument("--start-date", help="起始日期 YYYYMMDD (默认: 2年前)")
    parser.add_argument("--end-date", help="结束日期 YYYYMMDD (默认: 今天)")
    args = parser.parse_args()

    asyncio.run(main(args.batch_size, args.start_date, args.end_date))
