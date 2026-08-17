#!/usr/bin/env python3
"""Idempotent schema repair for long-running cloud deployments.

This script covers older server databases that predate part of the Alembic
history and may not have an ``alembic_version`` table. It only creates missing
tables/columns and never drops or rewrites existing data.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.database import engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS users (
        user_id VARCHAR(64) PRIMARY KEY,
        display_name VARCHAR(128) NOT NULL,
        is_active BOOLEAN NOT NULL DEFAULT TRUE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS portfolio_positions (
        id BIGSERIAL PRIMARY KEY,
        user_id VARCHAR(64) NOT NULL REFERENCES users(user_id),
        ts_code VARCHAR(16) NOT NULL,
        stock_name VARCHAR(64) NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CONSTRAINT uq_portfolio_user_ts_code UNIQUE (user_id, ts_code)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_portfolio_positions_user_id
    ON portfolio_positions (user_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS ths_concepts (
        ts_code VARCHAR(20) PRIMARY KEY,
        name VARCHAR(100) NOT NULL,
        count INTEGER,
        exchange VARCHAR(10),
        list_date DATE,
        type VARCHAR(10)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ths_concept_members (
        id SERIAL PRIMARY KEY,
        ts_code VARCHAR(20) NOT NULL,
        con_code VARCHAR(20) NOT NULL,
        con_name VARCHAR(50),
        in_date DATE
    )
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_ths_member_unique
    ON ths_concept_members (ts_code, con_code)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_ths_member_concept
    ON ths_concept_members (ts_code)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_ths_member_stock
    ON ths_concept_members (con_code)
    """,
    "ALTER TABLE company_profiles ADD COLUMN IF NOT EXISTS com_name VARCHAR(200)",
    "ALTER TABLE company_profiles ADD COLUMN IF NOT EXISTS com_id VARCHAR(50)",
    "ALTER TABLE company_profiles ADD COLUMN IF NOT EXISTS chairman VARCHAR(100)",
    "ALTER TABLE company_profiles ADD COLUMN IF NOT EXISTS manager VARCHAR(100)",
    "ALTER TABLE company_profiles ADD COLUMN IF NOT EXISTS secretary VARCHAR(100)",
    "ALTER TABLE company_profiles ADD COLUMN IF NOT EXISTS reg_capital VARCHAR(100)",
    "ALTER TABLE company_profiles ADD COLUMN IF NOT EXISTS setup_date VARCHAR(50)",
    "ALTER TABLE company_profiles ADD COLUMN IF NOT EXISTS province VARCHAR(50)",
    "ALTER TABLE company_profiles ADD COLUMN IF NOT EXISTS city VARCHAR(50)",
    "ALTER TABLE company_profiles ADD COLUMN IF NOT EXISTS introduction TEXT",
    "ALTER TABLE company_profiles ADD COLUMN IF NOT EXISTS website VARCHAR(200)",
    "ALTER TABLE company_profiles ADD COLUMN IF NOT EXISTS email VARCHAR(200)",
    "ALTER TABLE company_profiles ADD COLUMN IF NOT EXISTS office TEXT",
    "ALTER TABLE company_profiles ADD COLUMN IF NOT EXISTS employees INTEGER",
    "ALTER TABLE company_profiles ADD COLUMN IF NOT EXISTS exchange VARCHAR(10)",
)


async def ensure_schema() -> int:
    async with engine.begin() as conn:
        for statement in SCHEMA_STATEMENTS:
            await conn.execute(text(statement))
    logger.info("cloud schema ensured: %d statements", len(SCHEMA_STATEMENTS))
    return len(SCHEMA_STATEMENTS)


def main() -> None:
    asyncio.run(ensure_schema())


if __name__ == "__main__":
    main()
