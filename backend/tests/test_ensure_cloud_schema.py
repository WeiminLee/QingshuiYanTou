"""Tests for the cloud schema repair script."""

from scripts.ensure_cloud_schema import SCHEMA_STATEMENTS


def _schema_sql() -> str:
    return "\n".join(SCHEMA_STATEMENTS).lower()


def test_schema_repair_covers_company_profile_runtime_columns():
    sql = _schema_sql()

    assert "alter table company_profiles" in sql
    assert "add column if not exists com_name" in sql
    assert "add column if not exists chairman" in sql
    assert "add column if not exists exchange" in sql


def test_schema_repair_creates_runtime_tables():
    sql = _schema_sql()

    assert "create table if not exists users" in sql
    assert "create table if not exists portfolio_positions" in sql
    assert "create table if not exists ths_concepts" in sql
    assert "create table if not exists ths_concept_members" in sql
