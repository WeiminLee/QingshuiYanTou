# backend/tests/test_linklayer_models.py
"""链接层模型测试：ID 生成 + 表结构约束。"""
from app.knowledge.linklayer.models import Keyword, Link, make_keyword_id


def test_make_keyword_id_deterministic():
    a = make_keyword_id("subject", "300308.SZ")
    b = make_keyword_id("subject", "300308.SZ")
    assert a == b and a.startswith("KW:")
    assert make_keyword_id("scope", "300308.SZ") != a  # 不同层不同 ID


def test_link_keywords_unique_layer_norm():
    from sqlalchemy import UniqueConstraint

    unique_columns = [
        tuple(col.name for col in constraint.columns)
        for constraint in Keyword.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    ]
    assert ("layer", "norm_text") in unique_columns


def test_link_table_pk_columns():
    pk = {c.name for c in Link.__table__.primary_key.columns}
    assert pk == {"keyword_id", "evidence_id", "span_start"}
