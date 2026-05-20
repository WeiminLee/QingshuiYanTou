"""
索引现有存储数据

从 /home/workspace/data_access_mvp/storage 扫描已下载的 PDF 文件，
将元数据写入 MongoDB（reports / notices 集合），避免重复下载。

用法:
    python -m scripts.index_existing_storage
"""
import asyncio
import re
from datetime import datetime
from pathlib import Path

from motor.motor_asyncio import AsyncIOMotorClient

# 存储根目录（软链接指向 /home/workspace/data_access_mvp/storage）
STORAGE_ROOT = Path(__file__).resolve().parent.parent / "storage"
MONGODB_URL = "mongodb://qingshui:qingshui123@localhost:27018/qingshui?authSource=admin"


def format_date(date_str: str) -> str:
    """格式化日期字符串为 YYYY-MM-DD"""
    if date_str and len(date_str) >= 8:
        return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
    return ""


def parse_report_filename(filename: str) -> dict:
    """
    从研报文件名解析元数据。

    文件名格式: report_H3_AP202604091821077600_1.pdf_机构名_标题_日期.pdf
    """
    # 匹配日期模式: YYYYMMDD
    date_match = re.search(r"(\d{8})", filename)
    trade_date = date_match.group(1) if date_match else ""

    # 提取机构名称
    parts = filename.split("_")
    inst_csname = parts[3] if len(parts) > 3 else ""

    return {
        "filename": filename,
        "trade_date": format_date(trade_date),
        "inst_csname": inst_csname,
    }


def parse_notice_filename(filename: str) -> dict:
    """
    从公告文件名解析元数据。

    文件名格式: announcement_{announcementId}.pdf
    """
    # 巨潮格式
    notice_match = re.search(r"announcement_(\d+)\.pdf", filename, re.IGNORECASE)
    if notice_match:
        return {
            "notice_id": notice_match.group(1),
            "filename": filename,
        }

    return {"filename": filename}


async def index_reports(client: AsyncIOMotorClient) -> int:
    """扫描研报并写入 MongoDB"""
    db = client.qingshui
    reports_dir = STORAGE_ROOT / "reports"
    count = 0

    if not reports_dir.exists():
        print(f"研报目录不存在: {reports_dir}")
        return 0

    # 批量插入缓冲
    batch = []
    BATCH_SIZE = 500

    for ts_dir in reports_dir.iterdir():
        if not ts_dir.is_dir():
            continue
        ts_code = ts_dir.name

        for month_dir in ts_dir.iterdir():
            if not month_dir.is_dir():
                continue

            for pdf_file in month_dir.glob("*.pdf"):
                meta = parse_report_filename(pdf_file.name)
                doc = {
                    "ts_code": ts_code,
                    "trade_date": meta.get("trade_date", ""),
                    "inst_csname": meta.get("inst_csname", ""),
                    "file_path": str(pdf_file),
                    "file_name": pdf_file.name,
                    "file_size": pdf_file.stat().st_size,
                    "indexed_at": datetime.now(),
                    "source": "existing_storage",
                }
                batch.append(doc)

                if len(batch) >= BATCH_SIZE:
                    result = await db.reports.insert_many(batch)
                    count += len(result.inserted_ids)
                    print(f"已索引 {count} 条研报...")
                    batch = []

    # 插入剩余
    if batch:
        result = await db.reports.insert_many(batch)
        count += len(result.inserted_ids)

    print(f"研报索引完成: {count} 条")
    return count


async def index_notices(client: AsyncIOMotorClient) -> int:
    """扫描公告并写入 MongoDB"""
    db = client.qingshui
    notices_dir = STORAGE_ROOT / "notices"
    count = 0

    if not notices_dir.exists():
        print(f"公告目录不存在: {notices_dir}")
        return 0

    batch = []
    BATCH_SIZE = 500

    for ts_dir in notices_dir.iterdir():
        if not ts_dir.is_dir():
            continue
        ts_code = ts_dir.name

        for month_dir in ts_dir.iterdir():
            if not month_dir.is_dir():
                continue

            for pdf_file in month_dir.glob("*.pdf"):
                meta = parse_notice_filename(pdf_file.name)
                doc = {
                    "ts_code": ts_code,
                    "notice_id": meta.get("notice_id", ""),
                    "file_path": str(pdf_file),
                    "file_name": pdf_file.name,
                    "file_size": pdf_file.stat().st_size,
                    "indexed_at": datetime.now(),
                    "source": "existing_storage",
                }
                batch.append(doc)

                if len(batch) >= BATCH_SIZE:
                    result = await db.notices.insert_many(batch)
                    count += len(result.inserted_ids)
                    print(f"已索引 {count} 条公告...")
                    batch = []

    # 插入剩余
    if batch:
        result = await db.notices.insert_many(batch)
        count += len(result.inserted_ids)

    print(f"公告索引完成: {count} 条")
    return count


async def main():
    print("=" * 50)
    print("开始索引现有存储数据")
    print(f"存储目录: {STORAGE_ROOT}")
    print("=" * 50)

    client = AsyncIOMotorClient(MONGODB_URL)

    # 索引研报
    reports_count = await index_reports(client)

    # 索引公告
    notices_count = await index_notices(client)

    client.close()

    print("=" * 50)
    print(f"索引完成！共 {reports_count} 条研报，{notices_count} 条公告")
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(main())
