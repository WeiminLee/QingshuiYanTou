from __future__ import annotations

import asyncio


def test_extract_evidence_async_passes_evidence_id_to_relations(monkeypatch) -> None:
    from app.knowledge import kg_extractor as kg

    captured_relations: list[dict] = []

    async def fake_rag_extract_async(*args, **kwargs):
        return (
            [
                {"entity_name": "测试公司", "entity_type": "Company", "description": "公告主体"},
                {"entity_name": "测试产品", "entity_type": "Product", "description": "新产品"},
            ],
            [
                {
                    "src_id": "测试公司",
                    "tgt_id": "测试产品",
                    "description": "测试公司披露测试产品已经量产",
                    "weight": 10,
                }
            ],
        )

    def fake_upsert_company(**kwargs):
        return kwargs, True

    def fake_upsert_entity(**kwargs):
        return kwargs, True

    def fake_upsert_relates_v4(**kwargs):
        captured_relations.append(kwargs)
        return kwargs, True

    monkeypatch.setattr(kg, "rag_extract_async", fake_rag_extract_async)
    monkeypatch.setattr(kg, "upsert_company", fake_upsert_company)
    monkeypatch.setattr(kg, "upsert_entity", fake_upsert_entity)
    monkeypatch.setattr(kg, "upsert_relates_v4", fake_upsert_relates_v4)
    monkeypatch.setattr(kg, "upsert_entity_vector", lambda **kwargs: True)
    monkeypatch.setattr(kg, "upsert_relation_vector", lambda **kwargs: True)
    monkeypatch.setattr(kg, "_source_confidence", lambda source_type: (0.95, kg.ConfidenceTier.TIER1_OFFICIAL))

    result = asyncio.run(kg.extract_evidence_async({
        "evidence_id": "EV:trace",
        "source_type": "announcement",
        "source_name": "测试公告",
        "source_id": "ann-1",
        "text_excerpt": "测试公司披露测试产品已经量产。",
        "subject_hint": {"ts_code": "300001.SZ"},
    }))

    assert result["relations_created"] == 1
    assert captured_relations[0]["evidence_id"] == "EV:trace"
    assert captured_relations[0]["evidence_ids"] == ["EV:trace"]
