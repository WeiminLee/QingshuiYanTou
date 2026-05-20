import asyncio
from sqlalchemy import text
from app.core.database import async_session
from pymongo import MongoClient

OPTICAL_CODES = [
    "300308.SZ", "300502.SZ", "002281.SZ", "603083.SH",
    "300394.SZ", "688498.SH", "688048.SH", "688313.SH",
    "300757.SZ", "688205.SH", "688195.SH", "300620.SZ",
]

_mongo_client = None

def get_sync_db():
    global _mongo_client
    if _mongo_client is None:
        _mongo_client = MongoClient(
            "mongodb://qingshui:qingshui123@localhost:27017/qingshui?authSource=admin",
            serverSelectionTimeoutMS=5000
        )
    return _mongo_client["qingshui"]


async def main():
    sync_db = get_sync_db()

    async with async_session() as sess:
        for ts_code in OPTICAL_CODES:
            # 日线数据
            result = await sess.execute(
                text("""
                    SELECT COUNT(*), MAX(trade_date), MIN(trade_date)
                    FROM daily_data WHERE ts_code = :ts_code
                """),
                {"ts_code": ts_code}
            )
            row = result.fetchone()
            count, max_date, min_date = row[0], row[1], row[2]

            result2 = await sess.execute(
                text("SELECT close, pct_chg FROM daily_data WHERE ts_code = :ts_code ORDER BY trade_date DESC LIMIT 1"),
                {"ts_code": ts_code}
            )
            last = result2.fetchone()

            status = "✅" if count > 100 else ("⚠️" if count > 0 else "❌")
            last_info = f"close={last[0]}, pct={last[1]:.2f}%" if last else "无数据"
            print(f"{status} {ts_code} | {count:>6} 条 | {min_date}~{max_date} | {last_info}")

            # 公告数量
            result3 = await sess.execute(
                text("SELECT COUNT(*) FROM announcements WHERE ts_code = :ts_code"),
                {"ts_code": ts_code}
            )
            ann_count = result3.scalar()
            print(f"   公告: {ann_count} 条")

            # 互动易数量
            qa_count = sync_db["qa_interactive"].count_documents({"ts_code": ts_code})
            print(f"   互动易: {qa_count} 条")

            # 财联社
            cls_count = sync_db["cls_news"].count_documents({"ts_code": ts_code})
            print(f"   财联社: {cls_count} 条")
            print()

if __name__ == "__main__":
    asyncio.run(main())
