"""Short facts are retrieval keys. The original passage stays on the evidence id."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class ShortFact:
    fact_id: str
    subject: str
    dimension: str
    period: str
    value: str
    unit: str
    evidence_id: str
    valid_from: str | None = None
    valid_until: str | None = None


def retrieval_key(fact: ShortFact) -> str:
    """Text the bi-encoder ranks. This is not the evidence passage."""
    return f"{fact.subject} {fact.dimension} {fact.period} {fact.value}{fact.unit}"


def fact_view(fact: ShortFact) -> dict:
    return {
        "fact_id": fact.fact_id,
        "subject": fact.subject,
        "dimension": fact.dimension,
        "period": fact.period,
        "value": fact.value,
        "unit": fact.unit,
        "evidence_id": fact.evidence_id,
        "valid_from": fact.valid_from,
        "valid_until": fact.valid_until,
    }


def _day(value: str) -> date:
    return date.fromisoformat(value[:10])


def fact_is_in_force(fact: ShortFact, as_of: str) -> bool:
    """True when as_of falls inside [valid_from, valid_until). An ended fact is out."""
    day = _day(as_of)
    if fact.valid_from and day < _day(fact.valid_from):
        return False
    if fact.valid_until and day >= _day(fact.valid_until):
        return False
    return True


class FactCatalog:
    """In-process fact index. Passages are stored by evidence id, not on the fact."""

    def __init__(self) -> None:
        self._facts: list[ShortFact] = []
        self._passages: dict[str, str] = {}

    def register(self, fact: ShortFact, passage: str) -> None:
        self._facts = [item for item in self._facts if item.fact_id != fact.fact_id]
        self._facts.append(fact)
        self._passages[fact.evidence_id] = passage

    def facts(self) -> list[ShortFact]:
        return list(self._facts)

    def passage(self, evidence_id: str) -> str | None:
        return self._passages.get(evidence_id)

    def clear(self) -> None:
        self._facts.clear()
        self._passages.clear()


_catalog = FactCatalog()


def get_catalog() -> FactCatalog:
    return _catalog


def reset_catalog() -> None:
    _catalog.clear()


def register_short_fact(fact: ShortFact, passage: str) -> None:
    _catalog.register(fact, passage)


def lookup_registered_passage(evidence_id: str) -> str | None:
    return _catalog.passage(evidence_id)
