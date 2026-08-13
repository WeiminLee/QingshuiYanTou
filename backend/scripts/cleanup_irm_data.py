"""
清理互动易（IRM）低质量数据

使用改进后的 irm_filter 逻辑，删除数据库中已存在的低质量问答数据：
- 模板回答（"感谢您的关注"等）
- 回答太短（<15字符）
- 股东人数类问题无具体数字
- 纯股价/建议/问候类无实质内容

用法：
    python -m scripts.cleanup_irm_data          # dry-run，只统计
    python -m scripts.cleanup_irm_data --apply   # 实际删除
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import datetime

from sqlalchemy import text

from app.core.database import engine
from app.data_pipeline.irm_filter import classify_content

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("cleanup_irm")


async def scan_and_clean(dry_run: bool = True) -> None:
    """扫描并清理低质量IRM数据"""

    # 1. 获取总条数
    async with engine.connect() as conn:
        r = await conn.execute(
            text("SELECT COUNT(*) FROM announcements WHERE announcement_type LIKE 'irm:%'")
        )
        total = r.scalar()

    logger.info("IRM 数据总条数: %s", f"{total:,}")

    # 2. 分批扫描，收集需要删除的 ID
    offset = 0
    batch_size = 10000
    delete_ids: list[int] = []
    delete_reasons: dict[str, int] = {}

    async with engine.connect() as conn:
        while offset < total:
            r = await conn.execute(
                text(
                    """SELECT id, title, type FROM announcements 
                    WHERE announcement_type LIKE 'irm:%' 
                    ORDER BY id LIMIT :limit OFFSET :offset"""
                ),
                {"limit": batch_size, "offset": offset},
            )
            rows = r.fetchall()
            if not rows:
                break

            for row in rows:
                doc_type, action = classify_content(row[1] or "", row[2] or "")
                if action != "save":
                    delete_ids.append(row[0])
                    delete_reasons[doc_type] = delete_reasons.get(doc_type, 0) + 1

            offset += batch_size
            logger.info("  已扫描 %s/%s...", f"{offset:,}", f"{total:,}")

    to_delete = len(delete_ids)

    if to_delete == 0:
        logger.info("没有需要删除的数据。")
        return

    logger.info("=" * 50)
    logger.info("需要删除: %s 条 (%s%%)", f"{to_delete:,}", to_delete * 100 // total)
    logger.info("=" * 50)
    for reason, cnt in sorted(delete_reasons.items(), key=lambda x: -x[1]):
        logger.info("  %-30s: %s (%s%%)", reason, f"{cnt:,}", cnt * 100 // to_delete)

    if dry_run:
        logger.info("\nDry-run 模式，未实际删除。使用 --apply 参数执行删除。")
        return

    # 3. 分批删除
    logger.info("\n正在删除...")
    batch_size_delete = 5000
    deleted_count = 0

    async with engine.connect() as conn:
        async with conn.begin():
            for i in range(0, len(delete_ids), batch_size_delete):
                batch = delete_ids[i : i + batch_size_delete]
                r = await conn.execute(
                    text(
                        """DELETE FROM announcements 
                        WHERE id = ANY(:ids) 
                        AND announcement_type LIKE 'irm:%'"""
                    ),
                    {"ids": batch},
                )
                deleted_count += r.rowcount
                logger.info(
                    "  已删除 %s/%s...", f"{deleted_count:,}", f"{to_delete:,}"
                )

    logger.info("\n✅ 清理完成！共删除 %s 条低质量 IRM 数据。", f"{deleted_count:,}")


def main() -> None:
    parser = argparse.ArgumentParser(description="清理互动易低质量数据")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="实际执行删除（默认 dry-run 只统计）",
    )
    args = parser.parse_args()

    dry_run = not args.apply
    if dry_run:
        logger.info("⚠️  Dry-run 模式，只统计不删除。")
    else:
        logger.info("⚠️  执行模式，将实际删除数据！")
        confirm = input("确认删除？(yes/no): ")
        if confirm.lower() != "yes":
            logger.info("已取消。")
            sys.exit(0)

    asyncio.run(scan_and_clean(dry_run=dry_run))


if __name__ == "__main__":
    main()