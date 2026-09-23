from __future__ import annotations

from unittest.mock import patch

from app.knowledge.vector_client import (
    VectorRecord,
    build_evidence_vector_record,
    upsert_evidence_chunk_vector,
    write_chunk_vector,
)

EV = {
    "evidence_id": "EV:1",
    "text_excerpt": "公司公告称量产。",
    "source_type": "irm",
    "source_name": "互动易:1",
    "subject_hint": {"ts_code": "300001.SZ"},
}


def test_build_record_returns_none_on_empty_evidence():
    assert build_evidence_vector_record({"evidence_id": "", "text_excerpt": "x"}) is None
    assert build_evidence_vector_record({"evidence_id": "EV:1", "text_excerpt": "   "}) is None


def test_build_record_embeds_and_keeps_payload():
    with patch("app.knowledge.vector_client.get_embedding_model") as m:
        m.return_value.embed.return_value = [0.1, 0.2, 0.3]
        rec = build_evidence_vector_record(EV)
    assert isinstance(rec, VectorRecord)
    assert rec.vector == [0.1, 0.2, 0.3]
    assert rec.payload["evidence_id"] == "EV:1"
    assert rec.payload["source_type"] == "irm"


def test_write_chunk_vector_swallows_errors():
    rec = VectorRecord(id="p1", vector=[0.1], payload={"evidence_id": "EV:1"})
    with patch("app.knowledge.vector_client.get_vector_client") as m:
        m.return_value.upsert.side_effect = RuntimeError("boom")
        assert write_chunk_vector(rec) is False


def test_upsert_evidence_chunk_vector_delegates_to_split_functions():
    with patch(
        "app.knowledge.vector_client.build_evidence_vector_record",
        return_value=VectorRecord(id="p1", vector=[0.1], payload={"evidence_id": "EV:1"}),
    ) as b, patch("app.knowledge.vector_client.write_chunk_vector", return_value=True) as w:
        assert upsert_evidence_chunk_vector(EV) is True
    b.assert_called_once()
    w.assert_called_once()
