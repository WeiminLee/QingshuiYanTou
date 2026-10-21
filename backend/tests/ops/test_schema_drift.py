"""三源 schema 一致性检查的单元测试（纯逻辑，不连库）。"""

from __future__ import annotations

import sqlalchemy as sa

from app.ops.schema_drift import compare_schema


def _metadata() -> sa.MetaData:
    md = sa.MetaData()
    sa.Table("t_aligned", md, sa.Column("id", sa.Integer, primary_key=True), sa.Column("name", sa.String(20)))
    sa.Table("t_model_extra", md, sa.Column("id", sa.Integer, primary_key=True), sa.Column("ghost", sa.String(10)))
    sa.Table("t_db_extra", md, sa.Column("id", sa.Integer, primary_key=True))
    sa.Table("t_missing", md, sa.Column("id", sa.Integer, primary_key=True))
    return md


def _live(**overrides: set[str]) -> dict[str, set[str]]:
    """生产库全量视图；默认与模型一致，按需覆盖。"""
    base = {
        "t_aligned": {"id", "name"},
        "t_model_extra": {"id", "ghost"},
        "t_db_extra": {"id"},
        "t_missing": {"id"},
    }
    base.update(overrides)
    return base


def test_aligned_table_produces_no_drift() -> None:
    report = compare_schema(_metadata(), _live())

    assert report.missing_tables == []
    assert report.model_only_columns == {}
    assert report.db_only_columns == {}
    assert report.has_unsafe_drift is False


def test_model_only_column_is_flagged_as_unsafe() -> None:
    report = compare_schema(_metadata(), _live(t_model_extra={"id"}))

    assert report.model_only_columns["t_model_extra"] == ["ghost"]
    assert report.has_unsafe_drift is True


def test_db_only_column_is_flagged_but_not_unsafe() -> None:
    report = compare_schema(_metadata(), _live(t_db_extra={"id", "legacy_column"}))

    assert report.db_only_columns["t_db_extra"] == ["legacy_column"]
    assert report.model_only_columns == {}
    assert report.has_unsafe_drift is False


def test_missing_table_is_unsafe() -> None:
    live = _live()
    del live["t_missing"]
    report = compare_schema(_metadata(), live)

    assert report.missing_tables == ["t_missing"]
    assert report.has_unsafe_drift is True


def test_report_serializes_to_dict() -> None:
    report = compare_schema(_metadata(), _live(t_model_extra={"id"}))
    payload = report.as_dict()

    assert payload["unsafe"] is True
    assert payload["model_only_columns"]["t_model_extra"] == ["ghost"]