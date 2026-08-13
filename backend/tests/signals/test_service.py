from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.signals.service import get_signal_detail


class _SignalResult:
    def __init__(self, signal):
        self._signal = signal

    def scalar_one_or_none(self):
        return self._signal


class _PropagationResult:
    def scalars(self):
        return self

    def all(self):
        return []


class _FakeSession:
    def __init__(self, signal):
        self._signal = signal
        self._calls = 0

    async def execute(self, *_args, **_kwargs):
        self._calls += 1
        if self._calls == 1:
            return _SignalResult(self._signal)
        return _PropagationResult()


@pytest.mark.asyncio
async def test_get_signal_detail_falls_back_for_malformed_memory_metadata():
    now = datetime(2026, 7, 22, tzinfo=UTC)
    signal = SimpleNamespace(
        signal_id="SIG:bad-meta",
        source_type="announcement",
        source_id="EV:bad-meta",
        source_title=None,
        source_url=None,
        published_at=None,
        detected_at=now,
        subject_name="光模块",
        subject_type="product",
        signal_type="mass_production",
        polarity="positive",
        strength=80,
        confidence=Decimal("0.800"),
        value_score=90,
        summary="metadata malformed",
        evidence_excerpt=None,
        status="new",
        metadata_={
            "lifecycle": ["bad"],
            "reinforced_count": "n/a",
            "contradicted_count": {},
            "source_count": [],
        },
        created_at=now,
        updated_at=None,
    )

    detail = await get_signal_detail(_FakeSession(signal), "SIG:bad-meta")

    assert detail is not None
    assert detail["memory"]["lifecycle_status"] == "active"
    assert detail["memory"]["reinforced_count"] == 0
    assert detail["memory"]["contradicted_count"] == 0
    assert detail["memory"]["source_count"] == 1
