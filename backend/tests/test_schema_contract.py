"""schema 契约：ConceptLimit 模型列集必须被 init_database.py 建表 DDL 覆盖。

基准落在仓库内 scripts/init_database.py 的权威 DDL（不连生产库）。
2026-10-15 修复背景：模型曾声明 days/up_stat/cons_nums/rank 而引导 DDL 缺失，
导致 ORM 整实体 SELECT 抛 UndefinedColumnError（concept_top 500）。本测试
挡住"模型声明超出建表 DDL"这一类漂移的复发。
"""

from __future__ import annotations

import re
from pathlib import Path

from app.models.models import ConceptLimit

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_INIT_DB_PATH = _BACKEND_ROOT / "scripts" / "init_database.py"


def _init_ddl_columns(table: str) -> set[str]:
    """从 init_database.py 提取指定表的 CREATE TABLE 列集（纯文本解析）。"""
    src = _INIT_DB_PATH.read_text(encoding="utf-8")
    block = re.search(
        rf"CREATE TABLE IF NOT EXISTS {table}\s*\((.*?)\)\s*;",
        src,
        re.S,
    )
    assert block, f"init_database.py 中找不到 CREATE TABLE {table}"
    cols: set[str] = set()
    for line in block.group(1).splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith(("UNIQUE", "CONSTRAINT", "PRIMARY KEY", "FOREIGN KEY", "CHECK")):
            continue
        col = line.split()[0].strip('"')
        if col and col != ")":
            cols.add(col)
    return cols


def test_concept_limit_model_columns_within_init_ddl():
    model_cols = {c.name for c in ConceptLimit.__table__.columns}
    init_cols = _init_ddl_columns("concept_limit")

    # 模型不得声明建表 DDL 之外的列（会 500 的漂移）
    assert model_cols - init_cols == set(), (
        f"ConceptLimit 模型声明了 init_database.py 未创建的列: "
        f"{sorted(model_cols - init_cols)}"
    )
    # DDL 多出的列只允许服务端默认值列 created_at（模型刻意不映射）
    assert init_cols - model_cols <= {"created_at"}, (
        f"init_database.py 新增了模型未覆盖的列: {sorted(init_cols - model_cols)}"
    )
