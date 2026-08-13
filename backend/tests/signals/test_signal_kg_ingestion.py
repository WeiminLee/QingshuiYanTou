import pytest

from app.signals.evidence_ingestion import extract_evidence_signal_records
from app.signals.extractor import RuleSignalExtractor, SourcePayload
from app.signals.kg_propagation import KGEdge, KGPath


def _mass_production_evidence() -> dict:
    return {
        "evidence_id": "EV:1",
        "source_type": "announcement",
        "source_name": "公告",
        "text_excerpt": "公司 800G 光模块已批量交付客户。",
        "subject_hint": {"title": "中际旭创 800G 光模块批量交付"},
        "metadata": {"tags": ["中际旭创"]},
    }


def test_evidence_signals_prefer_kg_propagation_when_paths_exist():
    paths = {
        "中际旭创": [
            KGPath(
                nodes=["中际旭创", "800G光模块", "光芯片"],
                edges=[
                    KGEdge(src="中际旭创", rel_type="PRODUCES", tgt="800G光模块", weight=0.9, target_type="product"),
                    KGEdge(src="800G光模块", rel_type="UPSTREAM", tgt="光芯片", weight=0.8, target_type="concept"),
                ],
            )
        ]
    }

    signals, propagations = extract_evidence_signal_records(_mass_production_evidence(), kg_paths_by_subject=paths)

    assert signals
    assert propagations
    assert propagations[0]["target_name"] == "光芯片"
    assert propagations[0]["target_type"] == "concept"
    assert propagations[0]["metadata"]["secondary_type"] == "supply_chain_validation"
    assert propagations[0]["metadata"]["path_nodes"] == ["中际旭创", "800G光模块", "光芯片"]


def test_evidence_signals_fall_back_to_lightweight_propagation_when_no_kg_paths():
    signals, propagations = extract_evidence_signal_records(_mass_production_evidence(), kg_paths_by_subject={})

    assert signals
    assert propagations
    assert propagations[0]["relation_path"]
    assert "secondary_type" not in propagations[0]["metadata"]


@pytest.mark.asyncio
async def test_build_kg_paths_by_subject_fetches_once_per_candidate_subject():
    from app.signals.evidence_ingestion import build_kg_paths_by_subject

    payload = SourcePayload(
        source_type="announcement",
        source_id="EV:1",
        title="",
        content="公司 800G 光模块已批量交付客户。",
        summary="",
        published_at=None,
        url=None,
        metadata={"tags": ["中际旭创"]},
    )
    candidates = RuleSignalExtractor().extract(payload)

    class Provider:
        def __init__(self):
            self.calls = []

        async def fetch_paths(self, entity: str, *, max_hops: int = 2):
            self.calls.append((entity, max_hops))
            return [
                KGPath(
                    nodes=[entity, "800G光模块", "光芯片"],
                    edges=[
                        KGEdge(src=entity, rel_type="PRODUCES", tgt="800G光模块", target_type="product"),
                        KGEdge(src="800G光模块", rel_type="UPSTREAM", tgt="光芯片", target_type="concept"),
                    ],
                )
            ]

    provider = Provider()

    paths = await build_kg_paths_by_subject(candidates, provider)

    assert list(paths) == ["中际旭创"]
    assert provider.calls == [("中际旭创", 2)]
    assert paths["中际旭创"][0].nodes[-1] == "光芯片"
