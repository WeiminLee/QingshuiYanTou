#!/usr/bin/env python3
"""
互动易（IRM）历史数据同步脚本

支持按股票同步全量历史数据（akshare）。

过滤策略：
- 只保存产业链、供应链、产能、业绩等高价值问答
- 跳过纯问候语、无实质内容的低价值问题

用法:
    # 同步深证（默认）
    python -m scripts.sync_irm_history

    # 指定交易所
    python -m scripts.sync_irm_history --exchange SZ

    # 按股票同步
    python -m scripts.sync_irm_history --stocks 000001,000002

注意事项:
    - 按股票获取全量历史，每只股票间隔 1 秒
    - 使用 MongoDB checkpoint 断点续跑
"""
import argparse
import asyncio
import logging
import random
import sys
import re
from datetime import datetime, timedelta
from pathlib import Path

# 添加 backend 到 path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.database import engine
from app.core.mongodb import get_mongo_db
from app.data_pipeline.progress import IngestionProgressTracker, SUCCESS, PARTIAL
from app.data_pipeline.irm_filter import should_save as should_save_irm
from sqlalchemy import text

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# 并发配置
AKSHARE_CONCURRENCY = 4
AKSHARE_SLEEP_BASE = 1.0
AKSHARE_SLEEP_JITTER = 0.5

# MongoDB checkpoint 配置
CHECKPOINT_COLLECTION = "irm_history_checkpoint"
CHECKPOINT_WINDOW_HOURS = 24


def _safe_str(val) -> str:
    """安全转字符串"""
    if val is None:
        return ""
    try:
        import pandas as pd
        if pd.isna(val):
            return ""
    except (ImportError, TypeError):
        pass
    if hasattr(val, "strftime"):
        try:
            return val.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            pass
    s = str(val)
    return s.strip() if s else ""


def _normalize_ts_code(code: str) -> str:
    """标准化股票代码格式"""
    if not code:
        return ""
    c = code.strip()
    if "." not in c:
        return f"{c}.SH" if c.startswith("6") else f"{c}.SZ"
    prefix, num = c.split(".", 1)
    if prefix.lower() in ("sh", "ss"):
        return f"{num}.SH"
    if prefix.lower() in ("sz",):
        return f"{num}.SZ"
    return c.upper()


def _parse_chinese_date(date_str: str) -> str:
    """解析中文日期格式，返回 YYYYMMDD 格式"""
    if not date_str:
        return ""
    m = re.match(r"(\d{4})年(\d{1,2})月(\d{1,2})日", str(date_str))
    if m:
        return f"{m.group(1)}{int(m.group(2)):02d}{int(m.group(3)):02d}"
    for fmt in ["%Y-%m-%d", "%Y/%m/%d"]:
        try:
            dt = datetime.strptime(date_str[:10], fmt)
            return dt.strftime("%Y%m%d")
        except ValueError:
            continue
    return ""


# ── akshare 数据源 ────────────────────────────────────────

def get_stock_list(exchange: str = "ALL") -> list[dict]:
    """获取股票列表"""
    import akshare as ak

    stocks = []

    if exchange in ("SH", "ALL"):
        try:
            for symbol in ["1", "8"]:  # 主板A股 + 科创板
                df = ak.stock_info_sh_name_code(symbol=symbol)
                for _, row in df.iterrows():
                    code = _safe_str(row.get("证券代码", ""))
                    name = _safe_str(row.get("证券简称", ""))
                    if code.startswith("6"):
                        stocks.append({"ts_code": f"{code}.SH", "name": name})
            logger.info(f"获取到 {len([s for s in stocks if s['ts_code'].endswith('.SH')])} 只上证股票")
        except Exception as e:
            logger.error(f"获取上证股票列表失败: {e}")

    if exchange in ("SZ", "ALL"):
        try:
            df = ak.stock_info_sz_name_code(symbol="A股列表")
            for _, row in df.iterrows():
                code = _safe_str(row.get("A股代码", ""))
                name = _safe_str(row.get("A股简称", ""))
                if code and (code.startswith("0") or code.startswith("3")):
                    stocks.append({"ts_code": f"{code}.SZ", "name": name})
            logger.info(f"获取到 {len([s for s in stocks if s['ts_code'].endswith('.SZ')])} 只深证股票")
        except Exception as e:
            logger.error(f"获取深证股票列表失败: {e}")

    return stocks


def fetch_akshare_by_stock(symbol: str, exchange: str) -> list[dict]:
    """按股票获取 akshare 互动易数据"""
    import akshare as ak

    try:
        if exchange == "SH":
            df = ak.stock_sns_sseinfo(symbol=symbol)
        else:
            df = ak.stock_irm_cninfo(symbol=symbol)

        if df is None or len(df) == 0:
            return []

        records = []
        for _, row in df.iterrows():
            if exchange == "SH":
                answer = _safe_str(row.get("回答", ""))
                question_time_key = "问题时间"
                answer_time_key = "回答时间"
                question_key = "问题"
            else:
                answer = _safe_str(row.get("回答内容", ""))
                question_time_key = "提问时间"
                answer_time_key = "更新时间"
                question_key = "问题"

            if not answer:
                continue

            records.append({
                "stock_code": symbol,
                "stock_name": _safe_str(row.get("公司简称", "")),
                "question": _safe_str(row.get(question_key, "")),
                "answer": answer,
                "question_time": _safe_str(row.get(question_time_key, "")),
                "answer_time": _safe_str(row.get(answer_time_key, "")),
                "exchange": exchange,
            })

        return records

    except Exception as e:
        logger.warning(f"akshare {exchange} {symbol} 失败: {e}")
        return []


# ── 数据库保存 ────────────────────────────────────────────

async def save_irm_record(ts_code: str, rec: dict) -> bool | None:
    """保存单条互动易记录到数据库（过滤后）"""
    import hashlib

    question = str(rec.get("question") or "").strip()
    answer = str(rec.get("answer") or "").strip()
    if not question or not answer:
        return None  # 静默跳过空问答

    # 关键词过滤
    if not should_save_irm(question, answer):
        return None  # 静默跳过不匹配的记录

    question_time = str(rec.get("question_time") or "").strip()
    exchange = str(rec.get("exchange", "SH"))

    # 生成唯一 ID
    q_hash = hashlib.md5(question.encode("utf-8", errors="replace")).hexdigest()[:10]
    ann_id = f"irm_{exchange}_{ts_code}_{question_time}_{q_hash}"

    # 解析日期
    ann_date_obj = datetime.now().date()
    if question_time:
        date_str = _parse_chinese_date(question_time)
        if date_str:
            try:
                ann_date_obj = datetime.strptime(date_str, "%Y%m%d").date()
            except ValueError:
                pass

    sql = """
    INSERT INTO announcements (
        ann_date, ts_code, name, title, type,
        cninfo_id, announcement_type,
        source_type, source_name, confidence_tier
    ) VALUES (
        :ann_date, :ts_code, :name, :title, :type,
        :cninfo_id, :announcement_type,
        :source_type, :source_name, :confidence_tier
    )
    ON CONFLICT (cninfo_id) DO NOTHING
    """

    try:
        async with engine.begin() as conn:
            result = await conn.execute(
                text(sql),
                {
                    "ann_date": ann_date_obj,
                    "ts_code": ts_code,
                    "name": rec.get("stock_name") or None,
                    "title": question[:500],
                    "type": answer,
                    "cninfo_id": ann_id,
                    "announcement_type": f"irm:{exchange}",
                    "source_type": "irm_history",
                    "source_name": "上证e互动" if exchange == "SH" else "深证互动易",
                    "confidence_tier": "Tier2",
                },
            )
        return True if result.rowcount and result.rowcount > 0 else None
    except Exception as e:
        logger.warning(f"保存失败 [{ann_id}]: {e}")
        return False


# ── Checkpoint ────────────────────────────────────────────

async def _ensure_checkpoint_index() -> None:
    try:
        db = get_mongo_db()
        col = db[CHECKPOINT_COLLECTION]
        # 索引已存在会忽略错误
    except Exception as e:
        logger.debug(f"checkpoint 索引检查完成")


async def _filter_pending_stocks(ts_codes: list[str]) -> list[str]:
    """过滤掉 24 小时内已成功的股票"""
    if not ts_codes:
        return []
    try:
        db = get_mongo_db()
        cutoff = datetime.now() - timedelta(hours=CHECKPOINT_WINDOW_HOURS)
        cursor = db[CHECKPOINT_COLLECTION].find(
            {
                "ts_code": {"$in": ts_codes},
                "last_success_at": {"$gt": cutoff},
            },
            {"ts_code": 1, "_id": 0},
        )
        # 异步迭代 cursor
        done_set = set()
        async for doc in cursor:
            done_set.add(doc["ts_code"])
        if done_set:
            logger.info(f"checkpoint 跳过 {len(done_set)}/{len(ts_codes)} 只股票")
        return [c for c in ts_codes if c not in done_set]
    except Exception as e:
        logger.warning(f"checkpoint 过滤失败: {e}")
        return ts_codes


async def _save_checkpoint(
    checkpoint_key: str | None = None,
    ts_code: str | None = None,
    success: bool = False,
) -> None:
    try:
        db = get_mongo_db()
        now = datetime.now()
        update = {"last_attempt_at": now}
        if success:
            update["status"] = "done"
            update["last_success_at"] = now
        else:
            update["status"] = "retry"

        where = {}
        if checkpoint_key:
            where["checkpoint_key"] = checkpoint_key
        elif ts_code:
            where["ts_code"] = ts_code
        else:
            return  # 必须有一个 key

        await db[CHECKPOINT_COLLECTION].update_one(where, {"$set": update}, upsert=True)
    except Exception as e:
        logger.debug(f"checkpoint 写入失败: {e}")  # 降低日志级别


# ── akshare 同步（按股票）──────────────────────────────────

async def sync_by_stock(
    exchange: str = "SZ",
    ts_codes: list[str] | None = None,
) -> dict:
    """按股票同步（akshare）"""

    tracker = IngestionProgressTracker(
        source="irm_history",
        task_name="irm_by_stock",
        scope=f"{exchange}_all" if not ts_codes else "custom",
    )
    await tracker.ensure_tables()
    await _ensure_checkpoint_index()

    # 获取股票列表
    if ts_codes is None:
        stock_list = get_stock_list(exchange)
        ts_codes = [s["ts_code"] for s in stock_list]
        # 白名单过滤：scope=tech_mvp 时仅同步白名单股票
        from app.data_pipeline.backfill_config import load_backfill_settings
        bf_cfg = load_backfill_settings()
        if bf_cfg.scope == "tech_mvp" and bf_cfg.ts_codes:
            before = len(ts_codes)
            ts_codes = [c for c in ts_codes if c in bf_cfg.ts_codes]
            logger.info(
                "sync_by_stock: backfill scope=tech_mvp, %d/%d 命中白名单",
                len(ts_codes), before,
            )
        else:
            logger.info(f"将同步 {len(ts_codes)} 只股票")
    else:
        ts_codes = [_normalize_ts_code(c) for c in ts_codes]
        logger.info(f"将同步 {len(ts_codes)} 只指定股票")

    # 过滤已完成的
    ts_codes = await _filter_pending_stocks(ts_codes)
    total = len(ts_codes)
    logger.info(f"实际需要同步: {total} 只")

    run_ctx = await tracker.start_run(
        from_watermark="20130701",
        to_watermark=datetime.now().strftime("%Y%m%d"),
        metadata={"source": "akshare", "exchange": exchange},
    )

    semaphore = asyncio.Semaphore(AKSHARE_CONCURRENCY)
    counters = {"processed": 0, "success": 0, "fail": 0, "filtered": 0}
    lock = asyncio.Lock()

    async def worker(code: str):
        numeric = "".join(filter(str.isdigit, code))
        exch = "SH" if numeric.startswith("6") else "SZ"

        async with semaphore:
            try:
                records = await asyncio.to_thread(fetch_akshare_by_stock, numeric, exch)
            except Exception as e:
                logger.warning(f"获取 {code} 失败: {e}")
                await _save_checkpoint(ts_code=code, success=False)
                async with lock:
                    counters["processed"] += 1
                    counters["fail"] += 1
                return

            saved = 0
            filtered = 0
            for rec in records:
                ok = await save_irm_record(code, rec)
                if ok is True:
                    saved += 1
                elif ok is None:
                    filtered += 1

            await _save_checkpoint(ts_code=code, success=True)

            async with lock:
                counters["processed"] += 1
                counters["success"] += saved
                counters["filtered"] += filtered
                snapshot = dict(counters)

            await asyncio.sleep(AKSHARE_SLEEP_BASE + random.random() * AKSHARE_SLEEP_JITTER)

            if snapshot["processed"] % 50 == 0:
                logger.info(f"进度: {snapshot['processed']}/{total} (入库:{snapshot['success']} 过滤:{snapshot['filtered']})")

    await asyncio.gather(*(worker(c) for c in ts_codes))

    final_status = SUCCESS if counters["fail"] == 0 else PARTIAL
    await tracker.finish_run(
        run_ctx,
        status=final_status,
        total_items=total,
        processed_items=counters["processed"],
        success_count=counters["success"],
        skipped_count=0,
        downloaded_count=0,
        fail_count=counters["fail"],
        last_item_id=ts_codes[-1] if ts_codes else None,
    )

    return {
        "total": total,
        "success": counters["success"],
        "filtered": counters["filtered"],
        "fail": counters["fail"],
        "source": "akshare",
    }


# ── 主入口 ────────────────────────────────────────────────

async def main(
    exchange: str = "ALL",
    stocks_str: str | None = None,
):
    """主函数"""
    today = datetime.now()

    print(f"{'=' * 60}")
    print(f"互动易历史同步")
    print(f"{'=' * 60}")
    print(f"交易所: {exchange}")
    print(f"执行时间: {today.strftime('%Y-%m-%d')}")

    # akshare 按股票同步
    if stocks_str:
        codes = [c.strip() for c in stocks_str.split(",") if c.strip()]
        ts_codes = [_normalize_ts_code(c) for c in codes]
        print(f"指定股票: {len(ts_codes)} 只")
    else:
        ts_codes = None

    print()
    print("开始同步...")
    result = await sync_by_stock(exchange=exchange, ts_codes=ts_codes)

    print()
    print(f"{'=' * 60}")
    print(f"同步完成!")
    print(f"{'=' * 60}")
    print(f"总任务数: {result.get('total', 0)}")
    print(f"新增入库: {result.get('success', 0)} 条")
    print(f"过滤跳过: {result.get('filtered', 0)} 条")
    print(f"失败: {result.get('fail', 0)}")
    print(f"数据源: {result.get('source', 'N/A')}")

    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="互动易历史同步")
    parser.add_argument(
        "--exchange",
        choices=["SH", "SZ", "ALL"],
        default="ALL",
        help="交易所",
    )
    parser.add_argument(
        "--stocks",
        help="股票代码，逗号分隔",
    )
    args = parser.parse_args()

    asyncio.run(main(
        exchange=args.exchange,
        stocks_str=args.stocks,
    ))
