"""三源 schema 一致性检查（模型声明 / alembic head / 生产库实际列）。

用法（chemagent，容器内）：
    docker exec -e PYTHONPATH=/app qingshui_backend python -m scripts.check_schema_drift
    # 有危险漂移时退出码 1，可直接进 cron/CI

只读：只查 information_schema 与 alembic_version，不改结构。
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import text  # noqa: E402

# 必须先 import 模型模块，表才会注册到 Base.metadata（否则元数据为空）
import app.models.models  # noqa: E402,F401
from app.core.database import Base, engine  # noqa: E402
from app.ops.schema_drift import compare_schema, read_live_columns  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("schema-drift")


async def collect() -> tuple[dict[str, set[str]], str | None, int]:
    async with engine.connect() as conn:
        live = await conn.run_sync(read_live_columns)
        version = (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalar_one_or_none()
    return live, version, len(Base.metadata.tables)


def main() -> int:
    parser = argparse.ArgumentParser(description="三源 schema 一致性检查（只读）")
    parser.add_argument("--quiet", action="store_true", help="仅在有问题时输出")
    args = parser.parse_args()

    live, version, model_tables = asyncio.run(collect())
    report = compare_schema(Base.metadata, live)

    if not args.quiet:
        logger.info("模型表 %d · 库表 %d · alembic head %s", model_tables, len(live), version)

    for table in report.missing_tables:
        logger.error("缺表      %-28s 模型已声明、库中不存在（整实体查询会 UndefinedTableError）", table)
    for table, cols in report.model_only_columns.items():
        logger.error("模型多余  %-28s %s（整实体查询会 UndefinedColumnError）", table, cols)
    for table, cols in report.db_only_columns.items():
        logger.warning("库多余    %-28s %s（不炸，属认知债）", table, cols)

    if report.has_unsafe_drift:
        logger.error("结论：存在危险漂移")
        return 1
    logger.info("结论：无危险漂移（模型声明未超出生产库）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())