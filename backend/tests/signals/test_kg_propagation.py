from datetime import UTC, datetime

from app.signals.extractor import SignalCandidate
from app.signals.kg_propagation import KGEdge, KGPath, build_kg_propagations, neo4j_rows_to_paths


def _candidate(signal_type: str = "mass_production") -> SignalCandidate:
    return SignalCandidate(
        source_type="announcement",
        source_id="EV:800g",
        source_title="800G 光模块批量交付",
        source_url=None,
        published_at=datetime(2026, 7, 22, tzinfo=UTC),
        subject_name="中际旭创",
        subject_type="company",
        signal_type=signal_type,
        polarity="positive",
        strength=88,
        confidence=0.9,
        summary="800G 光模块批量交付",
        evidence_excerpt="公司 800G 光模块已批量交付客户。",
        metadata={"evidence_id": "EV:800g"},
        value_score=90,
    )


def test_build_kg_propagations_creates_secondary_signal_from_two_hop_path():
    path = KGPath(
        nodes=["中际旭创", "800G光模块", "光芯片"],
        edges=[
            KGEdge(src="中际旭创", rel_type="PRODUCES", tgt="800G光模块", weight=0.9, target_type="product"),
            KGEdge(src="800G光模块", rel_type="UPSTREAM", tgt="光芯片", weight=0.8, target_type="concept"),
        ],
    )

    propagations = build_kg_propagations(_candidate(), [path])

    assert len(propagations) == 1
    assert propagations[0].target_name == "光芯片"
    assert propagations[0].target_type == "concept"
    assert propagations[0].direction == "beneficiary"
    assert propagations[0].metadata["secondary_type"] == "supply_chain_validation"
    assert propagations[0].metadata["path_nodes"] == ["中际旭创", "800G光模块", "光芯片"]
    assert propagations[0].metadata["path_hops"] == 2


def test_build_kg_propagations_drops_paths_deeper_than_two_hops():
    path = KGPath(
        nodes=["A", "B", "C", "D"],
        edges=[
            KGEdge(src="A", rel_type="RELATES", tgt="B"),
            KGEdge(src="B", rel_type="RELATES", tgt="C"),
            KGEdge(src="C", rel_type="RELATES", tgt="D"),
        ],
    )

    assert build_kg_propagations(_candidate(), [path]) == []


def test_neo4j_rows_to_paths_converts_two_hop_records():
    rows = [
        {
            "path_nodes": ["中际旭创", "800G光模块", "光芯片"],
            "edges": [
                {
                    "src": "中际旭创",
                    "tgt": "800G光模块",
                    "type": "RELATES",
                    "text": "生产 800G 光模块",
                    "weight": 0.9,
                    "target_labels": ["Product"],
                },
                {
                    "src": "800G光模块",
                    "tgt": "光芯片",
                    "type": "RELATES",
                    "text": "上游依赖光芯片",
                    "weight": 0.8,
                    "target_labels": ["Concept"],
                },
            ],
            "hops": 2,
        }
    ]

    paths = neo4j_rows_to_paths(rows)

    assert paths == [
        KGPath(
            nodes=["中际旭创", "800G光模块", "光芯片"],
            edges=[
                KGEdge(
                    src="中际旭创",
                    rel_type="RELATES",
                    tgt="800G光模块",
                    weight=0.9,
                    text="生产 800G 光模块",
                    target_type="product",
                ),
                KGEdge(
                    src="800G光模块",
                    rel_type="RELATES",
                    tgt="光芯片",
                    weight=0.8,
                    text="上游依赖光芯片",
                    target_type="concept",
                ),
            ],
        )
    ]
