# backend/tests/test_linklayer_normalize.py
"""归一化测试：纯逻辑部分（subject canonicalize + ensure_keyword SQL 打桩）。"""
import pytest

from app.knowledge.linklayer.dict_match import SubjectIndex
from app.knowledge.linklayer.normalize import canonicalize_subject


def test_canonicalize_subject_by_alias():
    idx = SubjectIndex(alias_to_norm={"中晶科技": "003026.SZ"})
    assert canonicalize_subject("中晶科技", idx) == "003026.SZ"


def test_canonicalize_subject_miss():
    idx = SubjectIndex(alias_to_norm={})
    assert canonicalize_subject("不存在的公司", idx) is None


class _StubSession:
    """记录 execute 语句的伪 AsyncSession。"""

    def __init__(self):
        self.executed = []

    async def execute(self, stmt):
        self.executed.append(stmt)


def _params(stmt) -> dict:
    from sqlalchemy.dialects import postgresql

    return dict(stmt.compile(dialect=postgresql.dialect()).params)


@pytest.mark.parametrize(
    "layer,norm_text,source,expected_status",
    [
        ("subject", "003026.SZ", "dictionary", "active"),
        ("dimension", "毛利率", "dictionary", "active"),
        ("scope", "8英寸抛光硅片", "llm", "candidate"),
]
)
async def test_ensure_keyword_status_lifecycle(layer, norm_text, source, expected_status):
    from app.knowledge.linklayer.models import make_keyword_id
    from app.knowledge.linklayer.normalize import ensure_keyword

    session = _StubSession()
    keyword_id = await ensure_keyword(session, layer, norm_text, source=source)
    assert keyword_id == make_keyword_id(layer, norm_text)

    compiled = str(session.executed[0].compile(dialect=_pg_dialect()))
    assert "ON CONFLICT" in compiled.upper() and "DO NOTHING" in compiled.upper()
    assert _params(session.executed[0])["status"] == expected_status


def _pg_dialect():
    from sqlalchemy.dialects import postgresql

    return postgresql.dialect()
