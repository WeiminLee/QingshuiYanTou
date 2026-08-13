"""
同步 THS 同花顺概念板块数据（使用 tinyshare）

数据流：
1. ths_index()     → 全量概念列表 → ths_concepts 表
2. ths_member()    → 按概念获取成分股 → ths_concept_members 表

策略：按概念维度遍历（约2500个概念），比按个股遍历（5500+）更高效。
限速：接口限制 120 次/分钟，控制在 110 次/分钟以内，支持断点续传。
"""

import os
import logging
import sys
import time
from pathlib import Path

import pandas as pd
import tinyshare as ts
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://qingshui:qingshui123@localhost:5433/qingshui")
TUSHARE_TOKEN = os.getenv("TUSHARE_TOKEN", "")

# 限速：每分钟最多 110 次请求（接口限制 120 次/分钟）
RPM_LIMIT = 110
INTERVAL = 60.0 / RPM_LIMIT  # 约 0.545 秒/次

ts.set_token(TUSHARE_TOKEN)
pro = ts.pro_api()


def sync_concept_list(engine):
    """同步全量 THS 概念列表到 ths_concepts 表"""
    logger.info("获取 THS 概念列表...")
    df = pro.ths_index()
    if df is None or len(df) == 0:
        logger.warning("ths_index 返回空数据")
        return 0

    logger.info(f"共获取 {len(df)} 个概念/指数")

    with Session(engine) as session:
        inserted = 0
        for _, row in df.iterrows():
            sql = text("""
                INSERT INTO ths_concepts (ts_code, name, count, exchange, list_date, type)
                VALUES (:ts_code, :name, :count, :exchange, :list_date, :type)
                ON CONFLICT (ts_code)
                DO UPDATE SET
                    name = EXCLUDED.name,
                    count = EXCLUDED.count,
                    exchange = EXCLUDED.exchange,
                    list_date = EXCLUDED.list_date,
                    type = EXCLUDED.type
            """)
            session.execute(sql, {
                "ts_code": row["ts_code"],
                "name": row["name"],
                "count": int(row["count"]) if pd.notna(row.get("count")) else None,
                "exchange": row.get("exchange") if pd.notna(row.get("exchange")) else None,
                "list_date": row.get("list_date") if pd.notna(row.get("list_date")) else None,
                "type": row.get("type") if pd.notna(row.get("type")) else None,
            })
            inserted += 1

        session.commit()
        logger.info(f"概念列表同步完成，共处理 {inserted} 条")
        return inserted


def get_synced_concepts(engine):
    """获取已同步过的概念代码"""
    with Session(engine) as session:
        result = session.execute(text("SELECT ts_code FROM ths_concept_members GROUP BY ts_code"))
        return {r[0] for r in result.fetchall()}


def sync_members_by_concept(engine):
    """按概念维度遍历，获取每个概念的成分股"""
    # 获取所有概念代码
    with Session(engine) as session:
        result = session.execute(text("SELECT ts_code, name FROM ths_concepts"))
        concepts = [(r[0], r[1]) for r in result.fetchall()]

    # 获取已同步过的概念（断点续传）
    synced = get_synced_concepts(engine)
    logger.info(f"共 {len(concepts)} 个概念，已同步 {len(synced)} 个，待同步 {len(concepts) - len(synced)} 个")

    total_members = 0
    errors = 0
    skipped = 0
    request_count = 0
    batch_start = time.time()

    with Session(engine) as session:
        for i, (ts_code, name) in enumerate(concepts):
            if ts_code in synced:
                skipped += 1
                continue

            # 限速控制
            if request_count >= RPM_LIMIT:
                elapsed = time.time() - batch_start
                if elapsed < 60:
                    sleep_time = 60 - elapsed + 1
                    logger.info(f"  达到限速阈值，休眠 {sleep_time:.1f}s ...")
                    time.sleep(sleep_time)
                batch_start = time.time()
                request_count = 0

            try:
                df = pro.ths_member(ts_code=ts_code)
                request_count += 1
                time.sleep(INTERVAL)  # 请求间隔

                if df is not None and len(df) > 0:
                    for _, row in df.iterrows():
                        con_code = row["con_code"]
                        con_name = str(row.get("con_name", ""))[:180] if pd.notna(row.get("con_name")) else None

                        sql = text("""
                            INSERT INTO ths_concept_members (ts_code, con_code, con_name)
                            VALUES (:ts_code, :con_code, :con_name)
                            ON CONFLICT (ts_code, con_code)
                            DO UPDATE SET con_name = EXCLUDED.con_name
                        """)
                        session.execute(sql, {
                            "ts_code": ts_code,
                            "con_code": con_code,
                            "con_name": con_name,
                        })
                        total_members += 1
                else:
                    logger.debug(f"  概念 {ts_code} ({name}) 无成分股")

                # 每个概念提交一次，避免事务失败影响后续
                session.commit()

            except Exception as e:
                session.rollback()
                errors += 1
                if errors <= 5:
                    logger.warning(f"  获取概念 {ts_code} ({name}) 失败: {e}")
                # 遇到限速错误等更久
                if "429" in str(e) or "频次限制" in str(e):
                    logger.info("  遇到限速错误，等待 60s ...")
                    time.sleep(60)
                continue

            # 进度日志
            done = i + 1
            if done % 100 == 0:
                logger.info(f"  进度: {done}/{len(concepts)}, 共获取 {total_members} 条映射, 错误 {errors} 次")

        # 最终提交
        session.commit()

    logger.info(f"概念成分股同步完成，共 {total_members} 条映射，跳过 {skipped} 个，错误 {errors} 次")
    return total_members


def main():
    engine = create_engine(DATABASE_URL)

    # 1. 同步概念列表
    concept_count = sync_concept_list(engine)

    # 2. 按概念维度同步成分股映射
    member_count = sync_members_by_concept(engine)

    # 3. 汇总
    logger.info("=" * 50)
    logger.info("同步完成汇总:")
    logger.info(f"  概念列表: {concept_count} 条")
    logger.info(f"  概念映射: {member_count} 条")
    logger.info("=" * 50)


if __name__ == "__main__":
    main()