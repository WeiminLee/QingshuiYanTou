"""三源 schema 一致性：模型声明 / alembic head / 生产库实际列。

背景见 docs/待办.md F1~F5：模型、alembic 迁移链、生产库三者长期存在漂移，
曾直接导致 concept_top 500（模型声明了库中不存在的列）。

本模块只做**报告**，不改任何结构；「模型声明 > 库」是危险方向（会 500），
「库 > 模型」是认知债（不炸，但要知道）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import sqlalchemy as sa


@dataclass
class DriftReport:
    """一次三源比对的结果。"""

    missing_tables: list[str] = field(default_factory=list)
    model_only_columns: dict[str, list[str]] = field(default_factory=dict)
    db_only_columns: dict[str, list[str]] = field(default_factory=dict)

    @property
    def has_unsafe_drift(self) -> bool:
        """模型声明超出库（含整表缺失）——会触发 UndefinedColumnError / UndefinedTableError。"""
        return bool(self.missing_tables) or bool(self.model_only_columns)

    def as_dict(self) -> dict[str, Any]:
        return {
            "missing_tables": self.missing_tables,
            "model_only_columns": self.model_only_columns,
            "db_only_columns": self.db_only_columns,
            "unsafe": self.has_unsafe_drift,
        }


def compare_schema(model_metadata: sa.MetaData, live: dict[str, set[str]]) -> DriftReport:
    """比对 SQLAlchemy 模型元数据与生产库实际结构。

    Args:
        model_metadata: 模型侧 MetaData（通常 `Base.metadata`）。
        live: {表名: {列名}}，由 `read_live_columns` 从 information_schema 读取。
    """
    report = DriftReport()
    for table_name, table in sorted(model_metadata.tables.items()):
        model_cols = {c.name for c in table.columns}
        if table_name not in live:
            report.missing_tables.append(table_name)
            continue
        db_cols = live[table_name]
        extra = model_cols - db_cols
        if extra:
            report.model_only_columns[table_name] = sorted(extra)
        lagging = db_cols - model_cols
        if lagging:
            report.db_only_columns[table_name] = sorted(lagging)
    return report


def read_live_columns(conn: sa.ConnectionLike, schema: str | None = None) -> dict[str, set[str]]:
    """从 information_schema 读出 {表名: 列名集合}。"""
    sql = sa.text(
        "SELECT table_name, column_name FROM information_schema.columns "
        "WHERE table_schema = COALESCE(:schema, current_schema())"
    )
    rows = conn.execute(sql, {"schema": schema}).all()
    live: dict[str, set[str]] = {}
    for table_name, column_name in rows:
        live.setdefault(table_name, set()).add(column_name)
    return live