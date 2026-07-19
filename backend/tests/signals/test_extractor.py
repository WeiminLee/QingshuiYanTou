from datetime import UTC, datetime

from app.signals.extractor import (
    RuleSignalExtractor,
    SignalCandidate,
    SourcePayload,
    stable_signal_id,
)
from app.signals.propagation import build_lightweight_propagations


def test_stable_signal_id_is_deterministic():
    candidate = SignalCandidate(
        source_type="news",
        source_id="EV:abc",
        source_title="十五五规划强调算力基础设施",
        source_url=None,
        published_at=datetime(2026, 7, 13, tzinfo=UTC),
        subject_name="算力基础设施",
        subject_type="policy",
        signal_type="policy",
        polarity="positive",
        strength=82,
        confidence=0.72,
        summary="十五五规划强调算力基础设施",
        evidence_excerpt="十五五规划强调算力基础设施建设",
        metadata={},
    )

    assert stable_signal_id(candidate) == stable_signal_id(candidate)
    assert stable_signal_id(candidate).startswith("SIG:")


def test_rule_extractor_finds_policy_and_capex_signal():
    payload = SourcePayload(
        source_type="news",
        source_id="EV:policy",
        title="十五五规划强调算力基础设施，大厂资本开支显著增加",
        content="十五五规划强调算力基础设施建设，多家大公司资本开支显著增加。",
        summary="",
        published_at=datetime(2026, 7, 13, tzinfo=UTC),
        url=None,
        metadata={},
    )

    signals = RuleSignalExtractor().extract(payload)

    assert {s.signal_type for s in signals} >= {"policy", "capex"}
    assert all(s.source_id == "EV:policy" for s in signals)
    assert all(s.value_score > 0 for s in signals)


def test_lightweight_propagation_explains_policy_signal():
    candidate = RuleSignalExtractor().extract(
        SourcePayload(
            source_type="news",
            source_id="EV:policy",
            title="十五五规划强调算力基础设施",
            content="十五五规划强调算力基础设施建设。",
            summary="",
            published_at=datetime(2026, 7, 13, tzinfo=UTC),
            url=None,
            metadata={},
        )
    )[0]

    propagations = build_lightweight_propagations(candidate)

    assert propagations
    assert "->" in propagations[0].relation_path
    assert propagations[0].reasoning
