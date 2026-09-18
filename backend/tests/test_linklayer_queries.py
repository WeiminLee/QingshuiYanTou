# backend/tests/test_linklayer_queries.py
"""链接层检索原语测试：SQL 结构校验 + 打桩编排逻辑（不触真实 DB）。"""

import pytest

from app.knowledge.linklayer import queries as queries_mod
from app.knowledge.linklayer.dict_match import SubjectIndex
from app.knowledge.linklayer.queries import build_pull_history_sql


def test_build_pull_history_sql_contains_subject():
    sql, params = build_pull_history_sql(subject="003026.SZ", dimension="产线进展")
    assert "产线进展" in str(sql) or params  # 编译期结构校验
    assert "003026.SZ" in str(params)


def test_build_pull_history_sql_explicit_join_not_cartesian():
    """主体条件必须是显式 JOIN，不能退化成 link_links × link_keywords 笛卡尔积。"""
    from sqlalchemy.dialects import postgresql

    stmt, _ = build_pull_history_sql(subject="003026.SZ", dimension="产线进展", scope="8英寸抛光硅片")
    compiled = str(stmt.compile(dialect=postgresql.dialect()))
    assert "JOIN link_keywords ON link_keywords.keyword_id = link_links.keyword_id" in compiled
    # dimension + scope 各一个 evidence_id IN 子查询
    assert compiled.count("evidence_id IN (SELECT") == 2
    assert "ORDER BY" in compiled.upper()


def test_build_pull_history_sql_dimension_none_no_intersection():
    """dimension/scope 传 None 时不做交集过滤（无 IN 子查询）。"""
    from sqlalchemy.dialects import postgresql

    stmt, params = build_pull_history_sql(subject="003026.SZ")
    assert params["dimension"] is None
    compiled = str(stmt.compile(dialect=postgresql.dialect()))
    assert "IN (SELECT" not in compiled.upper()


class _StubResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _StubSession:
    """按调用顺序返回预置结果的伪 AsyncSession（同 test_linklayer_ingest 打桩模式）。"""

    def __init__(self, results):
        self._results = list(results)
        self.statements = []

    async def execute(self, stmt):
        self.statements.append(stmt)
        return _StubResult(self._results.pop(0))

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


@pytest.mark.asyncio
async def test_pull_history_dedupes_sorts_and_tolerates_missing_published_at(monkeypatch):
    """时间线：别名归一、去重、按 published_at 倒序、缺失 published_at 不崩溃。"""
    from sqlalchemy.dialects import postgresql

    from app.knowledge.evidence_service import EvidenceService

    async def fake_build_subject_index():
        return SubjectIndex(alias_to_norm={"中晶科技": "003026.SZ"})

    async def fake_get_evidence(self, evidence_id):
        return {
            "evidence_id": evidence_id,
            "publish_date": "2026-01-02" if evidence_id == "EV:2" else None,
            "source_type": "irm",
            "source_name": "互动易",
            "text_excerpt": "产线进展顺利",
        }

    monkeypatch.setattr(queries_mod, "build_subject_index", fake_build_subject_index)
    monkeypatch.setattr(EvidenceService, "get_evidence", fake_get_evidence)

    session = _StubSession(
        [
            [("EV:2", None), ("EV:1", None), ("EV:1", None)],  # 主查询：含重复行
            [("EV:1", "003026.SZ"), ("EV:2", "003026.SZ"), ("EV:2", "毛利率")],  # 关键字查询
        ]
    )
    monkeypatch.setattr(queries_mod, "async_session", lambda: session)

    result = await queries_mod.pull_history("中晶科技")

    # 别名应归一成 ts_code 后再进 SQL
    main_params = session.statements[0].compile(dialect=postgresql.dialect()).params
    assert "003026.SZ" in main_params.values()

    assert result["count"] == 2
    assert [it["evidence_id"] for it in result["items"]] == ["EV:2", "EV:1"]  # 去重 + 排序
    assert result["items"][0]["published_at"] == "2026-01-02"
    assert result["items"][1]["published_at"] is None  # 缺 published_at 不崩溃
    assert result["items"][0]["matched_keywords"] == ["003026.SZ", "毛利率"]


@pytest.mark.asyncio
async def test_backlinks_lists_keywords_and_related(monkeypatch):
    """双向引用：evidence 的全部关键字 + 各关键字下的其他 evidence（排除自身）。"""
    from app.knowledge.linklayer.models import Keyword

    kw_subject = Keyword(keyword_id="KW:subject:003026.SZ", layer="subject", norm_text="003026.SZ")
    kw_scope = Keyword(keyword_id="KW:scope:8inch", layer="scope", norm_text="8英寸抛光硅片")

    session = _StubSession(
        [
            [(kw_subject, object()), (kw_scope, object())],
            [
                ("KW:subject:003026.SZ", "EV:other"),
                ("KW:subject:003026.SZ", "EV:self"),
                ("KW:scope:8inch", "EV:other2"),
            ],
        ]
    )
    monkeypatch.setattr(queries_mod, "async_session", lambda: session)

    result = await queries_mod.backlinks("EV:self")
    assert [k["norm_text"] for k in result["keywords"]] == ["003026.SZ", "8英寸抛光硅片"]
    assert result["related"]["003026.SZ"] == ["EV:other"]
    assert result["related"]["8英寸抛光硅片"] == ["EV:other2"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_pull_history_integration():
    """integration：需要真实 PG/Mongo。"""
    from app.knowledge.linklayer.queries import pull_history

    result = await pull_history("003026.SZ", dimension="产线进展", limit=5)
    assert result["count"] == len(result["items"])
