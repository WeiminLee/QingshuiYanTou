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


def test_scan_dimension_sql_joins_scope():
    from app.knowledge.linklayer.queries import build_scan_dimension_sql

    stmt, params = build_scan_dimension_sql(dimension="毛利率", scope="8英寸抛光硅片")
    assert params == {"dimension": "毛利率", "scope": "8英寸抛光硅片"}


def test_scan_dimension_sql_explicit_joins():
    """横截面骨架：dimension 链路 join subject 链路，scope 走 IN 子查询。"""
    from sqlalchemy.dialects import postgresql

    from app.knowledge.linklayer.queries import build_scan_dimension_sql

    stmt, _ = build_scan_dimension_sql(dimension="毛利率", scope="8英寸抛光硅片")
    compiled = str(stmt.compile(dialect=postgresql.dialect()))
    assert compiled.count("link_links AS") == 2  # l + l2（dimension 链路 + subject 链路）
    assert compiled.count("link_keywords AS") == 2  # k + sk
    assert compiled.count("evidence_id IN (SELECT") == 1  # scope 交集
    assert "ORDER BY" in compiled.upper()


@pytest.mark.asyncio
async def test_scan_dimension_none_dimension_returns_empty():
    """theme 类 gold 条目以 dimension=None 调入：返回空结果 + note，不触碰 DB。"""
    result = await queries_mod.scan_dimension(None)
    assert result["items"] == []
    assert result["count"] == 0
    assert result["note"]


@pytest.mark.asyncio
async def test_scan_dimension_maps_rows_to_items(monkeypatch):
    """横截面结果映射：subject / evidence_id / published_at。"""
    from datetime import UTC, datetime

    published = datetime(2026, 6, 15, tzinfo=UTC)
    session = _StubSession([[("003026.SZ", "EV:1", published), ("中际旭创", "EV:2", None)]])
    monkeypatch.setattr(queries_mod, "async_session", lambda: session)

    result = await queries_mod.scan_dimension("毛利率", scope="8英寸抛光硅片")
    assert result["count"] == 2
    assert result["items"][0] == {
        "subject": "003026.SZ",
        "evidence_id": "EV:1",
        "published_at": "2026-06-15 00:00:00+00:00",
    }
    assert result["items"][1]["published_at"] is None
    assert result["dimension"] == "毛利率"
    assert result["scope"] == "8英寸抛光硅片"


@pytest.mark.asyncio
async def test_lookup_products_aggregates_scope_layer(monkeypatch):
    """单跳聚合：公司 → 同 evidence 的 scope 层关键字。"""
    from sqlalchemy.dialects import postgresql

    session = _StubSession([[("8英寸抛光硅片", 3, None)]])
    monkeypatch.setattr(queries_mod, "async_session", lambda: session)

    result = await queries_mod.lookup_products("003026.SZ", top_k=20)
    assert result == [{"norm_text": "8英寸抛光硅片", "mention_count": 3, "last_seen": None}]

    compiled = str(session.statements[0].compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "'subject'" in compiled and "'scope'" in compiled  # anchor/target 层接线
    assert "GROUP BY" in compiled and "LIMIT 20" in compiled


@pytest.mark.asyncio
async def test_lookup_players_aggregates_subject_layer(monkeypatch):
    """单跳聚合（反向）：产品关键字 → 同 evidence 的 subject 层公司。"""
    from sqlalchemy.dialects import postgresql

    session = _StubSession([[("003026.SZ", 2, None)]])
    monkeypatch.setattr(queries_mod, "async_session", lambda: session)

    result = await queries_mod.lookup_players("8英寸抛光硅片", top_k=10)
    assert result == [{"norm_text": "003026.SZ", "mention_count": 2, "last_seen": None}]

    compiled = str(session.statements[0].compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "'scope'" in compiled and "'subject'" in compiled
    assert "LIMIT 10" in compiled


@pytest.mark.asyncio
async def test_backfill_rolls_back_session_and_continues_after_db_error(monkeypatch, capsys):
    """回填循环：单条 DB 异常后 rollback 会话，且不中断后续条目。

    DBAPI 错误会把 SQLAlchemy session 置为 pending-rollback，不回滚的话
    "单条失败不中断"会退化成"首个 DB 错误拖垮整批"。
    """
    import sys

    import scripts.backfill_keyword_links as backfill_mod
    from app.core import database as db_mod
    from app.knowledge.linklayer import ingest as ingest_mod

    class _RollbackSession:
        def __init__(self):
            self.rollbacks = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def rollback(self):
            self.rollbacks += 1

    calls = []

    async def fake_ingest(evidence_id, *, _session=None, **_kwargs):
        calls.append(evidence_id)
        if evidence_id == "EV:bad":
            raise RuntimeError("模拟 DB 异常")
        return {"links": 1, "keywords": 1, "llm_used": False}

    async def fake_collect(svc, limit):
        return ["EV:bad", "EV:good"]

    session = _RollbackSession()
    monkeypatch.setattr(backfill_mod, "_collect_evidence_ids", fake_collect)
    monkeypatch.setattr(db_mod, "async_session", lambda: session)
    monkeypatch.setattr(ingest_mod, "ingest_evidence", fake_ingest)
    monkeypatch.setattr(sys, "argv", ["backfill_keyword_links.py"])

    await backfill_mod.main()

    out = capsys.readouterr().out
    assert calls == ["EV:bad", "EV:good"]  # 失败后继续处理
    assert session.rollbacks == 1  # 恰好回滚一次
    assert "FAIL EV:bad" in out
    assert "EV:good: {'links': 1" in out
    assert "done=1 failed=1" in out
