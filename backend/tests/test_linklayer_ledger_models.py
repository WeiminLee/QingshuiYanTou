# backend/tests/test_linklayer_ledger_models.py
"""台账模型测试：ID 生成 + 表结构约束。"""
from sqlalchemy import UniqueConstraint

from app.knowledge.linklayer.ledger_models import (
    Finding,
    Observation,
    Watermark,
    make_finding_id,
    make_obs_id,
)


def test_make_obs_id_deterministic():
    a = make_obs_id("EV:x", "003026.SZ", "产线进展", "8英寸抛光硅片")
    b = make_obs_id("EV:x", "003026.SZ", "产线进展", "8英寸抛光硅片")
    assert a == b and a.startswith("OB:")


def test_make_obs_id_scope_optional():
    """scope=None 与空串等价（同一证据主体维度下 scope 缺省只产一条观察）。"""
    assert make_obs_id("EV:x", "003026.SZ", "产线进展", None) == make_obs_id("EV:x", "003026.SZ", "产线进展", "")
    assert make_obs_id("EV:x", "003026.SZ", "产线进展", None) != make_obs_id("EV:x", "003026.SZ", "产线进展", "8英寸抛光硅片")


def test_make_finding_id_deterministic():
    a = make_finding_id("003026.SZ", "产线进展", 6, "OB:abc,OB:def")
    b = make_finding_id("003026.SZ", "产线进展", 6, "OB:abc,OB:def")
    assert a == b and a.startswith("FD:")
    assert a != make_finding_id("003026.SZ", "产线进展", 5, "OB:abc,OB:def")


def test_observation_pk_and_indexes():
    assert Observation.__tablename__ == "observations"
    assert Finding.__tablename__ == "findings"
    assert Watermark.__tablename__ == "watermarks"


def test_observation_unique_obs_id():
    uniques = [
        tuple(col.name for col in constraint.columns)
        for constraint in Observation.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    ]
    assert ("obs_id",) in uniques


def test_finding_unique_finding_id():
    uniques = [
        tuple(col.name for col in constraint.columns)
        for constraint in Finding.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    ]
    assert ("finding_id",) in uniques


def test_watermark_pk_columns():
    pk = {c.name for c in Watermark.__table__.primary_key.columns}
    assert pk == {"subject_ts_code", "dimension", "dimension_scope"}
