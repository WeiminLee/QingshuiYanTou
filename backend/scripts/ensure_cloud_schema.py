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
    """
    CREATE TABLE IF NOT EXISTS events (
        id BIGSERIAL PRIMARY KEY,
        event_id VARCHAR(32) NOT NULL UNIQUE,
        title TEXT NOT NULL,
        summary TEXT,
        content TEXT,
        source VARCHAR(32) NOT NULL DEFAULT 'cls',
        url TEXT,
        publish_at TIMESTAMPTZ NOT NULL,
        ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        metadata JSONB NOT NULL DEFAULT '{}'::jsonb
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_events_publish_at ON events (publish_at)",
    "CREATE INDEX IF NOT EXISTS idx_events_source ON events (source)",
    "CREATE INDEX IF NOT EXISTS idx_events_tags ON events USING gin (metadata jsonb_path_ops)",
    """
    CREATE TABLE IF NOT EXISTS signals (
        id BIGSERIAL PRIMARY KEY,
        signal_id VARCHAR(40) NOT NULL UNIQUE,
        source_type VARCHAR(32) NOT NULL,
        source_id VARCHAR(128) NOT NULL,
        source_title TEXT,
        source_url TEXT,
        published_at TIMESTAMPTZ,
        signal_kind VARCHAR(24) NOT NULL DEFAULT 'observed',
        event_date DATE,
        detected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        subject_name TEXT NOT NULL,
        subject_type VARCHAR(32) NOT NULL,
        signal_type VARCHAR(64) NOT NULL,
        polarity VARCHAR(16) NOT NULL,
        strength INTEGER NOT NULL,
        confidence NUMERIC(4, 3) NOT NULL,
        freshness_score INTEGER NOT NULL,
        value_score INTEGER NOT NULL,
        summary TEXT NOT NULL,
        evidence_excerpt TEXT,
        status VARCHAR(24) NOT NULL DEFAULT 'new',
        metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "ALTER TABLE signals ADD COLUMN IF NOT EXISTS signal_kind VARCHAR(24) NOT NULL DEFAULT 'observed'",
    "ALTER TABLE signals ADD COLUMN IF NOT EXISTS event_date DATE",
    "CREATE INDEX IF NOT EXISTS idx_signals_value_score ON signals (value_score, published_at)",
    "CREATE INDEX IF NOT EXISTS idx_signals_kind_value ON signals (signal_kind, value_score, published_at)",
    "CREATE INDEX IF NOT EXISTS idx_signals_event_date ON signals (event_date)",
    "CREATE INDEX IF NOT EXISTS idx_signals_source ON signals (source_type, source_id)",
    "CREATE INDEX IF NOT EXISTS idx_signals_subject ON signals (subject_type, subject_name)",
    "CREATE INDEX IF NOT EXISTS idx_signals_status ON signals (status)",
    "CREATE INDEX IF NOT EXISTS idx_signals_metadata_gin ON signals USING gin (metadata jsonb_path_ops)",
    """
    CREATE TABLE IF NOT EXISTS signal_propagations (
        id BIGSERIAL PRIMARY KEY,
        propagation_id VARCHAR(48) NOT NULL UNIQUE,
        signal_id VARCHAR(40) NOT NULL REFERENCES signals(signal_id) ON DELETE CASCADE,
        target_name TEXT NOT NULL,
        target_type VARCHAR(32) NOT NULL,
        relation_path TEXT NOT NULL,
        direction VARCHAR(24) NOT NULL,
        impact_horizon VARCHAR(24) NOT NULL,
        confidence NUMERIC(4, 3) NOT NULL,
        reasoning TEXT NOT NULL,
        evidence_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
        metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_signal_propagations_signal_id ON signal_propagations (signal_id)",
    "CREATE INDEX IF NOT EXISTS idx_signal_propagations_target ON signal_propagations (target_type, target_name)",
    "CREATE INDEX IF NOT EXISTS idx_signal_propagations_direction ON signal_propagations (direction)",
    """
    CREATE TABLE IF NOT EXISTS catalyst_events (
        id BIGSERIAL PRIMARY KEY,
        event_id VARCHAR(40) NOT NULL UNIQUE,
        event_type VARCHAR(40) NOT NULL,
        title TEXT NOT NULL,
        event_date DATE NOT NULL,
        event_time TIME,
        timezone VARCHAR(64) NOT NULL DEFAULT 'Asia/Shanghai',
        source_type VARCHAR(40) NOT NULL,
        source_id VARCHAR(128),
        source_url TEXT,
        importance INTEGER NOT NULL,
        subjects JSONB NOT NULL DEFAULT '[]'::jsonb,
        status VARCHAR(24) NOT NULL DEFAULT 'scheduled',
        metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_catalyst_events_event_date ON catalyst_events (event_date)",
    "CREATE INDEX IF NOT EXISTS idx_catalyst_events_status ON catalyst_events (status)",
    "CREATE INDEX IF NOT EXISTS idx_catalyst_events_source ON catalyst_events (source_type, source_id)",
    "CREATE INDEX IF NOT EXISTS idx_catalyst_events_subjects_gin ON catalyst_events USING gin (subjects jsonb_path_ops)",
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
