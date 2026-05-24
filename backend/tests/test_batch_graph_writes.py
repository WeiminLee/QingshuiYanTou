from __future__ import annotations

from contextlib import contextmanager
from datetime import date


class FakeResult:
    def consume(self) -> None:
        pass


class FakeTx:
    def __init__(self, calls: list[tuple[str, dict]]):
        self.calls = calls

    def run(self, query: str, params: dict):
        self.calls.append((query, params))
        return FakeResult()


def capture_batch_calls(monkeypatch, relations: list[dict]) -> list[tuple[str, dict]]:
    from app.knowledge import relation_service as rs

    calls: list[tuple[str, dict]] = []

    @contextmanager
    def fake_write_transaction():
        yield FakeTx(calls)

    monkeypatch.setattr(rs, "write_transaction", fake_write_transaction)

    result = rs.batch_upsert_relations_unwind(relations)

    assert result["failed"] == 0
    return calls


def test_batch_upsert_relations_merges_by_valid_from_and_dedupes_description(monkeypatch) -> None:
    calls = capture_batch_calls(monkeypatch, [
        {
            "from_entity": "C:300001.SZ",
            "to_entity": "P:abc",
            "text": "公司披露产品已经量产",
            "source_file": "公告A",
            "source_type": "announcement",
            "source_name": "公告A",
            "valid_from": date(2026, 5, 24),
            "weight": 1.0,
        }
    ])

    upsert_query = calls[1][0]
    rows = calls[1][1]["rows"]
    assert "MERGE (a)-[r:RELATES {valid_from: row.valid_from}]->(b)" in upsert_query
    assert "WHERE NOT row.description_entry IN r.descriptions" in upsert_query
    assert rows[0]["description_entry"] == "[公告A]neutral: 公司披露产品已经量产"


def test_batch_upsert_relations_uses_row_valid_from_for_yesterday(monkeypatch) -> None:
    calls = capture_batch_calls(monkeypatch, [
        {
            "from_entity": "C:300001.SZ",
            "to_entity": "P:abc",
            "text": "历史披露",
            "source_file": "公告A",
            "valid_from": date(2024, 1, 10),
        }
    ])

    rows = calls[1][1]["rows"]
    assert rows[0]["yesterday"] == "2024-01-09"


def test_batch_upsert_relations_links_batch_timeline_and_closes_once(monkeypatch) -> None:
    calls = capture_batch_calls(monkeypatch, [
        {
            "from_entity": "C:300001.SZ",
            "to_entity": "P:abc",
            "text": "后续披露",
            "source_file": "公告B",
            "valid_from": date(2024, 3, 1),
        },
        {
            "from_entity": "C:300001.SZ",
            "to_entity": "P:abc",
            "text": "早期披露",
            "source_file": "公告A",
            "valid_from": date(2024, 1, 10),
        },
    ])

    close_query = calls[0][0]
    rows = calls[1][1]["rows"]
    assert "row.close_existing" in close_query
    assert rows[0]["valid_from"] == "2024-01-10"
    assert rows[0]["valid_to"] == "2024-02-29"
    assert rows[0]["close_existing"] is True
    assert rows[1]["valid_from"] == "2024-03-01"
    assert rows[1]["valid_to"] is None
    assert rows[1]["close_existing"] is False


def test_batch_upsert_relations_excludes_batch_valid_froms_from_close(monkeypatch) -> None:
    calls = capture_batch_calls(monkeypatch, [
        {
            "from_entity": "C:300001.SZ",
            "to_entity": "P:abc",
            "text": "早期披露",
            "source_file": "公告A",
            "valid_from": date(2024, 1, 10),
        },
        {
            "from_entity": "C:300001.SZ",
            "to_entity": "P:abc",
            "text": "后续披露",
            "source_file": "公告B",
            "valid_from": date(2024, 3, 1),
        },
    ])

    close_query = calls[0][0]
    rows = calls[1][1]["rows"]
    assert "AND NOT r.valid_from IN row.batch_valid_froms" in close_query
    assert rows[0]["batch_valid_froms"] == ["2024-01-10", "2024-03-01"]
    assert rows[1]["batch_valid_froms"] == ["2024-01-10", "2024-03-01"]


def test_batch_upsert_relations_writes_evidence_and_state_history(monkeypatch) -> None:
    calls = capture_batch_calls(monkeypatch, [
        {
            "from_entity": "C:300001.SZ",
            "to_entity": "P:abc",
            "text": "公司披露产品已经量产",
            "source_file": "公告A",
            "valid_from": date(2024, 1, 10),
            "valid_to": date(2024, 3, 1),
            "evidence_id": "EV:1",
            "evidence_ids": ["EV:1", "EV:2", "EV:2"],
        }
    ])

    upsert_query = calls[1][0]
    rows = calls[1][1]["rows"]
    assert rows[0]["evidence_id"] == "EV:1"
    assert rows[0]["evidence_ids"] == ["EV:1", "EV:2"]
    assert rows[0]["state_history"] == ["2024-01-10~2024-03-01:公司披露产品已经量产"]
    assert "r.evidence_id   = row.evidence_id" in upsert_query
    assert "r.evidence_ids  = row.evidence_ids" in upsert_query
    assert "r.state_history = row.state_history" in upsert_query
    assert "r.evidence_ids = reduce(ids = coalesce(r.evidence_ids, [])" in upsert_query
