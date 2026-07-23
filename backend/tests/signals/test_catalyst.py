from datetime import date

from app.signals.models import CatalystEvent, Signal


def test_catalyst_event_model_fields():
    event = CatalystEvent(
        event_id="CAT:abc",
        event_type="conference",
        title="英伟达 GTC 开发者大会",
        event_date=date(2026, 7, 28),
        source_type="fixture",
        importance=90,
        subjects=["AI算力", "光模块"],
    )

    assert event.event_id == "CAT:abc"
    assert event.event_type == "conference"
    assert event.status == "scheduled"
    assert event.subjects == ["AI算力", "光模块"]


def test_signal_has_catalyst_columns():
    signal = Signal(
        signal_id="SIG:abc",
        source_type="catalyst_event",
        source_id="CAT:abc",
        subject_name="AI算力",
        subject_type="concept",
        signal_type="conference",
        polarity="neutral",
        strength=90,
        confidence=0.75,
        freshness_score=88,
        value_score=86,
        summary="未来催化预警",
        signal_kind="catalyst",
        event_date=date(2026, 7, 28),
    )

    assert signal.signal_kind == "catalyst"
    assert signal.event_date == date(2026, 7, 28)
