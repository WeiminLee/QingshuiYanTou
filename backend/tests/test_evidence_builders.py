"""Tests for mechanical Evidence builders."""

from app.knowledge.evidence_builders import build_file_evidence, build_irm_evidence


def test_build_file_evidence_carries_source_ref_and_limits_chunks() -> None:
    text = "\n\n".join([f"段落{i} 公司公告称产品量产。" for i in range(20)])
    file_info = {
        "file_path": "/tmp/a.pdf",
        "file_hash": "abc",
        "file_type": "pdf",
        "file_name": "公告.pdf",
        "title": "测试公告",
        "ts_code": "300001.SZ",
    }
    evidence = build_file_evidence(
        file_info, text, "announcement", "contract", "300001.SZ", chunk_max_tokens=20, max_chunks=2
    )
    assert len(evidence) == 2
    first = evidence[0]
    assert first.source_type == "announcement"
    assert first.source_name == "测试公告"
    assert first.subject_hint["ts_code"] == "300001.SZ"
    assert first.source_ref["file_path"] == "/tmp/a.pdf"
    assert first.source_ref["file_hash"] == "abc"
    assert first.source_ref["file_type"] == "pdf"
    assert first.source_ref["doc_type"] == "contract"
    assert first.source_ref["source_type"] == "announcement"
    assert "chunk_id" in first.source_ref
    assert "heading" in first.source_ref


def test_build_irm_evidence_shape() -> None:
    ev = build_irm_evidence(
        {
            "ts_code": "300001.SZ",
            "company_name": "测试公司",
            "question": "产品进展？",
            "answer": "已进入量产阶段。",
            "cninfo_id": "irm-1",
            "ann_date": "20260521",
        }
    )
    assert ev.source_type == "irm"
    assert ev.source_name == "互动易:irm-1"
    assert ev.source_id == "irm-1"
    assert "问题：产品进展？" in ev.text_excerpt
    assert "回答：已进入量产阶段。" in ev.text_excerpt
    assert ev.confidence == 0.85
    assert ev.subject_hint == {"ts_code": "300001.SZ", "company_name": "测试公司"}
    assert ev.source_ref["record_key"] == "irm-1"


def test_build_irm_evidence_without_cninfo_uses_stable_record_key() -> None:
    rec = {"ts_code": "300001.SZ", "company_name": "测试公司", "question": "Q", "answer": "A"}
    ev1 = build_irm_evidence(rec)
    ev2 = build_irm_evidence(rec)
    assert ev1.source_id == ev2.source_id
    assert ev1.source_ref["record_key"] == ev2.source_ref["record_key"]


def test_builders_do_not_emit_investment_judgment_fields() -> None:
    ev = build_irm_evidence({"question": "Q", "answer": "A"})
    payload_keys = set(ev.subject_hint) | set(ev.source_ref) | set(ev.metadata)
    forbidden = {"expected_alpha", "mispriced", "buy", "sell", "recommendation"}
    assert payload_keys.isdisjoint(forbidden)
