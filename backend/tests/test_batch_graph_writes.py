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


def test_batch_upsert_relations_merges_by_valid_from_and_dedupes_description(monkeypatch) -> None:
    from app.knowledge import relation_service as rs

    calls: list[tuple[str, dict]] = []

    @contextmanager
    def fake_write_transaction():
        yield FakeTx(calls)

    monkeypatch.setattr(rs, "write_transaction", fake_write_transaction)

    result = rs.batch_upsert_relations_unwind([
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

    assert result["failed"] == 0
    upsert_query = calls[1][0]
    rows = calls[1][1]["rows"]
    assert "MERGE (a)-[r:RELATES {valid_from: row.valid_from}]->(b)" in upsert_query
    assert "WHERE NOT row.description_entry IN r.descriptions" in upsert_query
    assert rows[0]["description_entry"] == "[公告A]neutral: 公司披露产品已经量产"
