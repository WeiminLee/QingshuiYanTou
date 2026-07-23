from datetime import date
from types import SimpleNamespace

import pytest

from app.signals.catalyst import (
    CatalystEventCandidate,
    FixtureCatalystProvider,
    build_catalyst_signal_payload,
    event_in_window,
    stable_catalyst_event_id,
    stable_catalyst_signal_id,
)
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


def test_fixture_provider_produces_deterministic_future_event():
    today = date(2026, 7, 23)
    first = FixtureCatalystProvider().list_candidates(today=today)
    second = FixtureCatalystProvider().list_candidates(today=today)

    assert first == second
    assert any(item.event_type == "conference" for item in first)
    assert any("光模块" in item.subjects for item in first)


@pytest.mark.parametrize(
    ("event_date", "expected"),
    [
        (date(2026, 7, 23), True),
        (date(2026, 7, 28), True),
        (date(2026, 7, 29), False),
        (date(2026, 7, 22), False),
    ],
)
def test_event_in_window_is_inclusive(event_date, expected):
    assert event_in_window(event_date, today=date(2026, 7, 23), window_days=5) is expected


def test_stable_ids_are_deterministic():
    candidate = CatalystEventCandidate(
        event_type="conference",
        title="英伟达 GTC 开发者大会",
        event_date=date(2026, 7, 28),
        source_type="fixture",
        source_id="nvidia-gtc-2026-07-28",
        importance=90,
        subjects=["AI算力", "光模块"],
    )

    assert stable_catalyst_event_id(candidate) == stable_catalyst_event_id(candidate)
    assert stable_catalyst_event_id(candidate).startswith("CAT:")
    assert stable_catalyst_signal_id("CAT:abc", ["英伟达GTC", "光模块"]) == stable_catalyst_signal_id(
        "CAT:abc", ["英伟达GTC", "光模块"]
    )


def test_build_catalyst_signal_payload_scores_portfolio_hit_high():
    event = SimpleNamespace(
        event_id="CAT:abc",
        event_type="conference",
        title="英伟达 GTC 开发者大会",
        event_date=date(2026, 7, 28),
        source_url=None,
        importance=90,
        subjects=["AI算力", "光模块", "CPO"],
        metadata_={},
    )

    payload = build_catalyst_signal_payload(
        event,
        today=date(2026, 7, 23),
        path_nodes=["英伟达GTC", "AI算力", "光模块", "中际旭创"],
        subject_name="AI算力",
        subject_type="concept",
        path_confidence=0.72,
        user_hits={"portfolio": ["中际旭创"], "watchlist": [], "preferences": ["光模块"]},
    )

    assert payload["signal_kind"] == "catalyst"
    assert payload["event_date"] == date(2026, 7, 28)
    assert payload["source_type"] == "catalyst_event"
    assert payload["metadata"]["catalyst"]["lead_days"] == 5
    assert payload["metadata"]["catalyst"]["alert_level"] == "high"
    assert payload["metadata"]["user_hits"]["portfolio"] == ["中际旭创"]
    assert payload["metadata"]["path_nodes"] == ["英伟达GTC", "AI算力", "光模块", "中际旭创"]
