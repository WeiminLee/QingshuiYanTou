"""StructuredFact persistence helpers."""
from __future__ import annotations

import json
import hashlib
import logging
from datetime import datetime
from typing import Any

from app.core.neo4j_client import run_write, run_single

logger = logging.getLogger(__name__)

FORBIDDEN_STATE_VALUES = {
    "mispriced",
    "expected_alpha",
    "buy",
    "sell",
    "recommendation_upgrade",
    "recommendation_downgrade",
}


def stable_fact_id(subject_id: str, dimension: str, state_value: str, observed_at: Any, evidence_id: str) -> str:
    payload = "\n".join([str(subject_id or ""), str(dimension or ""), str(state_value or ""), str(observed_at or ""), str(evidence_id or "")])
    return f"SF:{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:24]}"


def validate_structured_fact(fact: dict[str, Any]) -> None:
    for key in ("dimension", "state_value"):
        value = str(fact.get(key) or "").lower()
        for bad in FORBIDDEN_STATE_VALUES:
            if bad in value:
                raise ValueError(f"forbidden structured fact value: {bad}")


def upsert_structured_fact(fact: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    validate_structured_fact(fact)
    fact_id = fact.get("fact_id") or stable_fact_id(
        str(fact.get("subject_id") or ""),
        str(fact.get("dimension") or ""),
        str(fact.get("state_value") or ""),
        fact.get("observed_at"),
        str(fact.get("evidence_id") or ""),
    )
    now = datetime.utcnow().isoformat()
    props = {
        "fact_id": fact_id,
        "subject_id": fact.get("subject_id"),
        "subject_type": fact.get("subject_type"),
        "dimension": fact.get("dimension"),
        "state_value": fact.get("state_value"),
        "observed_at": str(fact.get("observed_at") or ""),
        "valid_from": str(fact.get("valid_from") or fact.get("observed_at") or ""),
        "valid_to": fact.get("valid_to"),
        "evidence_id": fact.get("evidence_id"),
        "evidence_text": fact.get("evidence_text"),
        "confidence": fact.get("confidence"),
        "source_type": fact.get("source_type"),
        "source_name": fact.get("source_name"),
        "metadata": json.dumps(fact.get("metadata") or {}, ensure_ascii=False, sort_keys=True, default=str),
        "created_at": now,
        "updated_at": now,
    }
    existing = run_single("MATCH (f:StructuredFact {fact_id: $fact_id}) RETURN f", {"fact_id": fact_id})
    if existing:
        run_write("MATCH (f:StructuredFact {fact_id: $fact_id}) SET f += $props", {"fact_id": fact_id, "props": props})
        return {**props, "fact_id": fact_id}, False

    run_write("CREATE (f:StructuredFact $props)", {"props": props})
    subject_id = str(fact.get("subject_id") or "")
    if subject_id:
        run_write(
            "MATCH (s {entity_id: $subject_id}) MATCH (f:StructuredFact {fact_id: $fact_id}) MERGE (s)-[:HAS_FACT]->(f)",
            {"subject_id": subject_id, "fact_id": fact_id},
        )
    return {**props, "fact_id": fact_id}, True


def extract_rule_based_facts(evidence: dict[str, Any], entities: list[dict[str, Any]], relations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    text = str(evidence.get("text_excerpt") or "")
    subject_hint = evidence.get("subject_hint") or {}
    subject_id = str(subject_hint.get("ts_code") or "").strip()
    if not subject_id:
        return []
    facts: list[dict[str, Any]] = []
    if "量产" in text:
        facts.append({
            "subject_id": subject_id,
            "subject_type": "Company",
            "dimension": "production",
            "state_value": "mass_production_started",
            "observed_at": evidence.get("observed_at"),
            "valid_from": evidence.get("publish_date") or evidence.get("observed_at"),
            "evidence_id": evidence.get("evidence_id"),
            "evidence_text": text[:500],
            "confidence": evidence.get("confidence") or 0.8,
            "source_type": evidence.get("source_type"),
            "source_name": evidence.get("source_name"),
            "metadata": {"trigger": "量产"},
        })
    if "导入" in text or "进入供应链" in text:
        facts.append({
            "subject_id": subject_id,
            "subject_type": "Company",
            "dimension": "customer",
            "state_value": "customer_introduction",
            "observed_at": evidence.get("observed_at"),
            "valid_from": evidence.get("publish_date") or evidence.get("observed_at"),
            "evidence_id": evidence.get("evidence_id"),
            "evidence_text": text[:500],
            "confidence": evidence.get("confidence") or 0.8,
            "source_type": evidence.get("source_type"),
            "source_name": evidence.get("source_name"),
            "metadata": {"trigger": "导入"},
        })
    if "订单" in text and "排产" in text:
        facts.append({
            "subject_id": subject_id,
            "subject_type": "Company",
            "dimension": "order",
            "state_value": "order_scheduled",
            "observed_at": evidence.get("observed_at"),
            "valid_from": evidence.get("publish_date") or evidence.get("observed_at"),
            "evidence_id": evidence.get("evidence_id"),
            "evidence_text": text[:500],
            "confidence": evidence.get("confidence") or 0.8,
            "source_type": evidence.get("source_type"),
            "source_name": evidence.get("source_name"),
            "metadata": {"trigger": "订单排产"},
        })
    if "业绩不及预期" in text or "低于预期" in text:
        facts.append({
            "subject_id": subject_id,
            "subject_type": "Company",
            "dimension": "financial",
            "state_value": "earnings_below_expectation",
            "observed_at": evidence.get("observed_at"),
            "valid_from": evidence.get("publish_date") or evidence.get("observed_at"),
            "evidence_id": evidence.get("evidence_id"),
            "evidence_text": text[:500],
            "confidence": evidence.get("confidence") or 0.8,
            "source_type": evidence.get("source_type"),
            "source_name": evidence.get("source_name"),
            "metadata": {"trigger": "业绩不及预期"},
        })
    return facts
