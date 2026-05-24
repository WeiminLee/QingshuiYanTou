#!/usr/bin/env python3
"""
历史公告同步脚本 - 同步全部个股过去两年的公告

策略：逐日查询全市场公告（cninfo API 范围查询分页有问题）

用法:
    python -m scripts.sync_history_announcements [--start-date YYYYMMDD] [--end-date YYYYMMDD]

示例:
    # 同步过去两年
    python -m scripts.sync_history_announcements

    # 同步指定日期范围
    python -m scripts.sync_history_announcements --start-date 20240501 --end-date 20260515
"""
import argparse
import asyncio
import sys
from datetime import datetime, timedelta, date
from pathlib import Path

# 添加 backend 到 path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text

from app.core.database import engine
from app.data_pipeline.cninfo_client import CninfoClient


# 每批天数（控制内存使用）
BATCH_DAYS = 5


def get_trading_days(start: date, end: date) -> list[date]:
    """生成交易日期列表（跳过周末）"""
    days = []
    current = start
    while current <= end:
        if current.weekday() < 5:  # 周一到周五
            days.append(current)
        current += timedelta(days=1)
    return days


async def get_existing_count() -> int:
    """获取已入库公告数量"""
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT COUNT(*) FROM announcements WHERE source_type = 'cninfo'"))
            return result.scalar() or 0
    except Exception:
        return 0


async def save_announcement(cninfo_id: str, ann_date: str, ts_code: str, name: str,
                           title: str, pdf_url: str, ann_type: str = "other") -> bool:
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
        parsed_date = date_type(int(ann_date[:4]), int(ann_date[4:6]), int(ann_date[6:8]))
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
                    "announcement_type": ann_type,
                    "source_type": "cninfo",
                    "source_name": "巨潮资讯",
                    "confidence_tier": "Tier1",
                    "pdf_url": pdf_url or None,
                },
            )
        return result.rowcount > 0 if result.rowcount else False
    except Exception:
        return False


async def sync_single_day(client: CninfoClient, target_date: str) -> dict:
    """同步单日全市场公告（处理分页）"""
    saved = 0
    skipped = 0
    total = 0
    page = 1

    while True:
        try:
            resp = await client.query_announcements(ann_date=target_date, page=page)
            announcements = resp.get("list") or []
            api_total = resp.get("total", 0)

            if page == 1:
                total = api_total

            if not announcements:
                break

            for ann in announcements:
                cninfo_id = CninfoClient.get_announcement_id(ann)
                if not cninfo_id:
                    continue

                ann_date_str = CninfoClient.get_ann_date(ann) or target_date
                ts_code = CninfoClient.get_ts_code(ann)
                name = str(ann.get("secName", "") or "")
                title = CninfoClient.get_title(ann)
                pdf_url = CninfoClient.get_pdf_url(ann)

                ok = await save_announcement(cninfo_id, ann_date_str, ts_code, name, title, pdf_url)
                if ok:
                    saved += 1
                else:
                    skipped += 1

            # 检查是否已获取全部
            if page * 100 >= total or len(announcements) < 100:
                break

            page += 1

        except Exception as e:
            print(f"      错误: {e}")
            break

    return {"total": total, "saved": saved, "skipped": skipped}


async def sync_date_batch(client: CninfoClient, dates: list[date]) -> dict:
    """同步一批日期"""
    grand_saved = 0
    grand_skipped = 0
    grand_total = 0
    errors = 0

    for d in dates:
        date_str = d.strftime("%Y%m%d")
        result = await sync_single_day(client, date_str)
        grand_total += result["total"]
        grand_saved += result["saved"]
        grand_skipped += result["skipped"]
        if result["total"] == 0 and result["saved"] == 0:
            errors += 1

    return {"total": grand_total, "saved": grand_saved, "skipped": grand_skipped, "errors": errors}


async def main(start_date_str: str | None = None, end_date_str: str | None = None):
    """主函数"""
    # 计算日期范围
    today = datetime.now()
    end_date = datetime.strptime(end_date_str, "%Y%m%d") if end_date_str else today
    start_date = datetime.strptime(start_date_str, "%Y%m%d") if start_date_str else (today - timedelta(days=730))

    start_str = start_date.strftime("%Y%m%d")
    end_str = end_date.strftime("%Y%m%d")

    print(f"{'=' * 60}")
    print(f"历史公告同步任务")
    print(f"{'=' * 60}")
    print(f"日期范围: {start_str} ~ {end_str}")

    # 获取已有公告数
    existing = await get_existing_count()
    print(f"当前已入库: {existing} 条")
    print()

    # 生成要同步的日期
    trading_days = get_trading_days(start_date.date(), end_date.date())
    total_days = len(trading_days)
    print(f"交易天数: {total_days} 天")
    print(f"每批: {BATCH_DAYS} 天")
    print(f"预计批次: {(total_days + BATCH_DAYS - 1) // BATCH_DAYS} 批")
    print()

    # 创建客户端
    client = CninfoClient()

    # 统计
    grand_total = 0
    grand_saved = 0
    grand_skipped = 0
    batch_num = 0
    last_print = datetime.now()

    print(f"开始同步 (Ctrl+C 可中断，已处理的数据会保留)...")
    print("-" * 60)

    # 分批处理
    for i in range(0, total_days, BATCH_DAYS):
        batch_dates = trading_days[i:i + BATCH_DAYS]
        batch_num += 1

        result = await sync_date_batch(client, batch_dates)

        grand_total += result["total"]
        grand_saved += result["saved"]
        grand_skipped += result["skipped"]

        now = datetime.now()
        if (now - last_print).seconds >= 10 or batch_num == 1:
            progress = (i + BATCH_DAYS) / total_days * 100
            days_done = i + BATCH_DAYS
            print(f"批次 {batch_num:4d}: {batch_dates[0].strftime('%m/%d')}~{batch_dates[-1].strftime('%m/%d')} | "
                  f"本批 {result['total']:5d} 条 | "
                  f"累计 {grand_total:7d} 条 | "
                  f"新增 {grand_saved:6d} | "
                  f"进度 {progress:5.1f}%")
            last_print = now

    print()
    print(f"{'=' * 60}")
    print(f"同步完成!")
    print(f"{'=' * 60}")
    print(f"批次总数: {batch_num}")
    print(f"获取公告: {grand_total} 条")
    print(f"新增入库: {grand_saved} 条")
    print(f"跳过/重复: {grand_skipped} 条")
    print(f"日期范围: {start_str} ~ {end_str}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="历史公告同步")
    parser.add_argument("--start-date", help="起始日期 YYYYMMDD (默认: 2年前)")
    parser.add_argument("--end-date", help="结束日期 YYYYMMDD (默认: 今天)")
    args = parser.parse_args()

    asyncio.run(main(args.start_date, args.end_date))
