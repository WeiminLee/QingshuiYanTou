#!/usr/bin/env python3
"""
Minishare IRM 历史数据回补脚本

使用 minishare 接口回补互动易历史数据（深交所+上交所）。

用法:
    python -m scripts.sync_minishare_irm_history [--start-date YYYYMMDD] [--end-date YYYYMMDD]

示例:
    # 回补过去两年（默认）
    python -m scripts.sync_minishare_irm_history

    # 回补指定日期范围
    python -m scripts.sync_minishare_irm_history --start-date 20230101 --end-date 20260615
"""
import argparse
import asyncio
import sys
from datetime import datetime, timedelta
from pathlib import Path

# 添加 backend 到 path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.data_pipeline.fetcher import DataFetcher
from app.data_pipeline.backfill_config import load_backfill_settings


async def main(start_date_str: str | None = None, end_date_str: str | None = None,
               scope: str | None = None):
    """主函数

    默认起始/结束日期来自 app.data_pipeline.backfill_config。
    """
    import os
    if scope:
        os.environ["BACKFILL_SCOPE"] = scope
    from app.data_pipeline.backfill_config import reset_settings_cache
    reset_settings_cache()
    cfg = load_backfill_settings()

    today = datetime.now()
    end_date = datetime.strptime(end_date_str, "%Y%m%d") if end_date_str else datetime.strptime(cfg.end_date, "%Y%m%d")
    start_date = datetime.strptime(start_date_str, "%Y%m%d") if start_date_str else datetime.strptime(cfg.start_date, "%Y%m%d")

    start_str = start_date.strftime("%Y%m%d")
    end_str = end_date.strftime("%Y%m%d")

    print(f"{'=' * 60}")
    print(f"Minishare IRM (互动易) 历史回补")
    print(f"{'=' * 60}")
    print(f"日期范围: {start_str} ~ {end_str}")
    print()

    fetcher = DataFetcher()

    print("开始同步...")
    result = await fetcher.fetch_irm()

    print()
    print(f"{'=' * 60}")
    print(f"同步完成!")
    print(f"{'=' * 60}")
    print(f"总天数: {result.get('total_days', 0)}")
    print(f"新增入库: {result.get('success', 0)} 条")
    print(f"跳过/重复: {result.get('skipped', 0)} 条")
    print(f"失败: {result.get('fail', 0)} 条")

    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Minishare IRM 历史回补")
    parser.add_argument("--start-date", help="起始日期 YYYYMMDD (默认: backfill_config 中的 BACKFILL_START_DATE)")
    parser.add_argument("--end-date", help="结束日期 YYYYMMDD (默认: 今天)")
    parser.add_argument("--scope", choices=["tech_mvp", "all"], default=None,
                        help="覆盖 BACKFILL_SCOPE 配置")
    args = parser.parse_args()

    asyncio.run(main(args.start_date, args.end_date, args.scope))
