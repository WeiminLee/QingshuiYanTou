# backend/tests/test_linklayer_ledger_tools.py
"""台账工具测试：句级锚定校验（SearchAtlas 硬证据闸门）+ 写回 + 水位线。"""
import yaml

from app.knowledge.evidence_service import EvidenceService
from app.knowledge.linklayer.ledger_models import Watermark
from app.reasoning.tools.knowledge.ledger_tools import (
    read_watermark,
    save_finding,
    save_observation,
    validate_supports,
    watermark_tool,
    write_finding_tool,
    write_observation_tool,
)


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _Scalar:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class FakeLedgerSession:
    """台账写回假会话：水位线查询返回预置行，insert 语句全部捕获。"""

    def __init__(self, watermark=None):
        self.watermark = watermark
        self.statements = []
        self.added = []
        self.commits = 0

    async def execute(self, stmt):
        self.statements.append(stmt)
        entities = [d["entity"] for d in getattr(stmt, "column_descriptions", [])]
        if Watermark in entities:
            return _Scalar(self.watermark)
        return _Rows([])

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.commits += 1


async def test_validate_supports_rejects_missing_evidence(monkeypatch):
    async def fake_get_evidence(self, evidence_id):
        return None

    monkeypatch.setattr(EvidenceService, "get_evidence", fake_get_evidence)
    errors = await validate_supports(
        [{"evidence_id": "EV:nonexistent", "span_start": 0, "span_end": 5}], session=None
    )
    assert errors, "无锚点支撑必须被拒绝（SearchAtlas 硬证据闸门）"


async def test_validate_supports_rejects_out_of_range(monkeypatch):
    async def fake_get_evidence(self, evidence_id):
        return {"evidence_id": evidence_id, "text_excerpt": "短文本"}

    monkeypatch.setattr(EvidenceService, "get_evidence", fake_get_evidence)
    errors = await validate_supports(
        [{"evidence_id": "EV:x", "span_start": 100, "span_end": 200}], session=None
    )
    assert errors, "span 越界必须被拒绝"


async def test_validate_supports_rejects_missing_evidence_id():
    errors = await validate_supports([{"span_start": 0, "span_end": 3}], session=None)
    assert errors, "缺少 evidence_id 必须被拒绝"


async def test_validate_supports_accepts_in_range(monkeypatch):
    async def fake_get_evidence(self, evidence_id):
        return {"evidence_id": evidence_id, "text_excerpt": "公司产线已进入量产阶段"}

    monkeypatch.setattr(EvidenceService, "get_evidence", fake_get_evidence)
    errors = await validate_supports(
        [{"evidence_id": "EV:x", "span_start": 0, "span_end": 6}], session=None
    )
    assert errors == []


async def test_save_observation_verifies_and_advances_watermark(monkeypatch):
    async def fake_get_evidence(self, evidence_id):
        return {"evidence_id": evidence_id, "text_excerpt": "公司8英寸抛光硅片产线已进入量产阶段"}

    monkeypatch.setattr(EvidenceService, "get_evidence", fake_get_evidence)
    session = FakeLedgerSession(watermark=None)
    result = await save_observation(
        session,
        subject_ts_code="003026.SZ",
        dimension="产线进展",
        evidence_id="EV:1",
        span_start=0,
        span_end=18,
        stage_raw="量产",
        stage_level=6,
        dimension_scope="8英寸抛光硅片",
        event_date="2026-06-15",
    )
    assert result["ok"] is True
    assert result["obs_id"].startswith("OB:")

    from sqlalchemy.dialects import postgresql

    obs_sql = str(session.statements[0].compile(dialect=postgresql.dialect()))
    assert "ON CONFLICT (obs_id) DO UPDATE" in obs_sql

    wm = session.added[0]
    assert isinstance(wm, Watermark)
    assert wm.max_level == 6
    assert wm.dimension_scope == "8英寸抛光硅片"
    assert wm.first_reached_at is not None
    assert session.commits == 1


async def test_save_observation_does_not_lower_watermark(monkeypatch):
    async def fake_get_evidence(self, evidence_id):
        return {"evidence_id": evidence_id, "text_excerpt": "公司产线尚在建设"}

    monkeypatch.setattr(EvidenceService, "get_evidence", fake_get_evidence)
    session = FakeLedgerSession(
        watermark=Watermark(subject_ts_code="003026.SZ", dimension="产线进展", dimension_scope=None, max_level=6)
    )
    result = await save_observation(
        session,
        subject_ts_code="003026.SZ",
        dimension="产线进展",
        evidence_id="EV:2",
        span_start=0,
        span_end=8,
        stage_raw="建设中",
        stage_level=2,
    )
    assert result["ok"] is True
    assert session.watermark.max_level == 6, "水位线只升不降"
    assert session.watermark.first_reached_at is None, "未破水位线不刷新 first_reached_at"
    assert session.watermark.last_updated_at is not None


async def test_save_observation_rejects_bad_anchor(monkeypatch):
    async def fake_get_evidence(self, evidence_id):
        return {"evidence_id": evidence_id, "text_excerpt": "短文本"}

    monkeypatch.setattr(EvidenceService, "get_evidence", fake_get_evidence)
    session = FakeLedgerSession()
    result = await save_observation(
        session,
        subject_ts_code="003026.SZ",
        dimension="产线进展",
        evidence_id="EV:1",
        span_start=0,
        span_end=100,
    )
    assert result["ok"] is False
    assert result["errors"]
    assert session.commits == 0


async def test_save_observation_rejects_bad_date(monkeypatch):
    async def fake_get_evidence(self, evidence_id):
        return {"evidence_id": evidence_id, "text_excerpt": "公司产线已进入量产阶段"}

    monkeypatch.setattr(EvidenceService, "get_evidence", fake_get_evidence)
    result = await save_observation(
        FakeLedgerSession(),
        subject_ts_code="003026.SZ",
        dimension="产线进展",
        evidence_id="EV:1",
        span_start=0,
        span_end=8,
        event_date="not-a-date",
    )
    assert result["ok"] is False


async def test_save_finding_requires_supports():
    result = await save_finding(
        FakeLedgerSession(),
        subject_ts_code="003026.SZ",
        dimension="产线进展",
        kind="progression",
        judgment="中晶科技产线从调试进入量产",
        supports=[],
    )
    assert result["ok"] is False
    assert result["errors"]


async def test_save_finding_rejects_unanchored_support(monkeypatch):
    async def fake_get_evidence(self, evidence_id):
        return None

    monkeypatch.setattr(EvidenceService, "get_evidence", fake_get_evidence)
    result = await save_finding(
        FakeLedgerSession(),
        subject_ts_code="003026.SZ",
        dimension="产线进展",
        kind="progression",
        judgment="中晶科技产线从调试进入量产",
        supports=[{"evidence_id": "EV:missing", "span_start": 0, "span_end": 5}],
    )
    assert result["ok"] is False


async def test_save_finding_writes_with_deterministic_id(monkeypatch):
    async def fake_get_evidence(self, evidence_id):
        return {"evidence_id": evidence_id, "text_excerpt": "公司8英寸抛光硅片产线已进入量产阶段"}

    monkeypatch.setattr(EvidenceService, "get_evidence", fake_get_evidence)
    supports = [
        {"obs_id": "OB:a", "evidence_id": "EV:1", "span_start": 0, "span_end": 18},
        {"obs_id": "OB:b", "evidence_id": "EV:2", "span_start": 3, "span_end": 12},
    ]
    session = FakeLedgerSession()
    result = await save_finding(
        session,
        subject_ts_code="003026.SZ",
        dimension="产线进展",
        kind="progression",
        judgment="中晶科技产线从调试进入量产",
        supports=supports,
        dimension_scope="8英寸抛光硅片",
        to_state={"stage": "量产", "level": 6},
        confidence=0.8,
    )
    assert result["ok"] is True
    assert result["finding_id"].startswith("FD:")

    from sqlalchemy.dialects import postgresql

    sql = str(session.statements[0].compile(dialect=postgresql.dialect()))
    assert "ON CONFLICT (finding_id) DO UPDATE" in sql
    assert session.commits == 1


async def test_read_watermark_found_and_missing():
    session = FakeLedgerSession(
        watermark=Watermark(subject_ts_code="003026.SZ", dimension="产线进展", dimension_scope=None, max_level=5)
    )
    found = await read_watermark("003026.SZ", "产线进展", None, session)
    assert found["found"] is True
    assert found["watermark"]["max_level"] == 5

    missing = await read_watermark("003026.SZ", "客户认证", None, FakeLedgerSession())
    assert missing["found"] is False
    assert missing["watermark"] == {}


def test_tool_names():
    assert write_observation_tool.name == "write_observation"
    assert write_finding_tool.name == "write_finding"
    assert watermark_tool.name == "watermark"


def test_registry_has_ledger_tools():
    from pathlib import Path

    cfg = yaml.safe_load(
        (Path(__file__).parent.parent / "app" / "reasoning" / "registry" / "config.yaml").read_text(encoding="utf-8")
    )
    tools = {t["name"]: t for t in cfg["tools"]}
    for name in ("write_observation", "write_finding", "watermark"):
        assert name in tools, f"registry 缺少工具 {name}"
        assert tools[name]["group"] == "knowledge"


def test_ledger_tools_resolve_and_register():
    from app.reasoning.registry.loader import load_tools_from_config

    configs = load_tools_from_config()
    names = {cfg.name for cfg in configs}
    for name in ("write_observation", "write_finding", "watermark"):
        assert name in names, f"loader 未注册工具 {name}（检查 config.yaml 的 use: 路径）"
