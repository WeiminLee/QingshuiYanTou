"""Entailment is separate from relevance: period, metric variant, and unit must match."""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.knowledge.retrieval.facts import lookup_registered_passage

_VARIANT_GROUPS = (("综合毛利率", "扣非毛利率"),)
_UNIT_TOKENS = ("百分点", "亿元", "万元", "元", "%")
_PERIOD_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(\d{4})年?第?三季度"), "Q3"),
    (re.compile(r"(\d{4})Q3"), "Q3"),
    (re.compile(r"(\d{4})年?第?二季度"), "Q2"),
    (re.compile(r"(\d{4})Q2"), "Q2"),
    (re.compile(r"(\d{4})年?第?一季度"), "Q1"),
    (re.compile(r"(\d{4})Q1"), "Q1"),
    (re.compile(r"(\d{4})年?第?四季度"), "Q4"),
    (re.compile(r"(\d{4})Q4"), "Q4"),
    (re.compile(r"(\d{4})年?全年"), "FY"),
    (re.compile(r"FY(\d{4})"), "FY"),
    (re.compile(r"(\d{4})年上半年"), "H1"),
    (re.compile(r"(\d{4})H1"), "H1"),
)

_model = None


@dataclass(frozen=True)
class SlotJudgment:
    period_ok: bool
    metric_ok: bool
    unit_ok: bool


def install_entailment_model(model) -> None:
    global _model
    _model = model


def reset_entailment_model() -> None:
    global _model
    _model = None


def get_entailment_model():
    return _model or default_slot_judge


def canonical_periods(text: str) -> set[str]:
    found: set[str] = set()
    for pattern, suffix in _PERIOD_PATTERNS:
        for match in pattern.finditer(text or ""):
            found.add(f"{match.group(1)}{suffix}")
    return found


def normalize_period(period: str) -> str:
    found = canonical_periods(period)
    if len(found) == 1:
        return next(iter(found))
    return period.strip()


def units_in(text: str) -> set[str]:
    found: set[str] = set()
    remaining = text or ""
    for token in _UNIT_TOKENS:
        if token in remaining:
            found.add(token)
            remaining = remaining.replace(token, "")
    return found


def _period_ok(period: str | None, passage: str) -> bool:
    if not period:
        return True
    return canonical_periods(passage) == {normalize_period(period)}


def _metric_ok(dimension: str, passage: str) -> bool:
    if not dimension:
        return True
    for group in _VARIANT_GROUPS:
        if dimension not in group:
            continue
        return dimension in (passage or "")
    return True


def _unit_ok(unit: str | None, passage: str) -> bool:
    if not unit:
        return True
    return unit in units_in(passage)


def default_slot_judge(claim: dict, passage: str) -> SlotJudgment:
    return SlotJudgment(
        period_ok=_period_ok(claim.get("period"), passage),
        metric_ok=_metric_ok(claim.get("dimension") or "", passage),
        unit_ok=_unit_ok(claim.get("unit"), passage),
    )



async def entailment_errors(
    *,
    dimension: str,
    judgment: str,
    to_state: dict | None,
    supports: list[dict],
) -> list[str]:
    """Reject a write when the cited span does not entail the claim's slots."""
    state = to_state or {}
    claim = {
        "dimension": state.get("metric") or dimension,
        "period": state.get("period"),
        "unit": state.get("unit"),
        "value": state.get("value"),
        "judgment": judgment,
    }
    model = get_entailment_model()
    errors: list[str] = []
    for sup in supports:
        evidence_id = sup.get("evidence_id")
        passage = lookup_registered_passage(evidence_id) if evidence_id else None
        if passage is None and evidence_id:
            from app.knowledge.evidence_service import EvidenceService

            ev = await EvidenceService().get_evidence(evidence_id)
            passage = (ev or {}).get("text_excerpt") or ""
        passage = passage or ""
        start = int(sup.get("span_start") or 0)
        end = int(sup.get("span_end") or 0)
        cited = passage[start:end] if end > start else passage
        slots = model(claim, cited)
        if not slots.period_ok:
            errors.append(f"引用段未支撑结论的期间: {evidence_id}")
        if not slots.metric_ok:
            errors.append(f"引用段未支撑结论的指标口径: {evidence_id}")
        if not slots.unit_ok:
            errors.append(f"引用段未支撑结论的单位: {evidence_id}")
    return errors
