"""Evidence-first knowledge construction primitives.

This module is intentionally pure: no database, Neo4j, Qdrant, or LLM imports.
It defines stable identifiers and lightweight schemas used by ingestion builders
and async extraction workers.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

EXTRACTOR_VERSION = "evidence-v1"

EVIDENCE_COLLECTION = "kg_evidence"
EXTRACTION_JOBS_COLLECTION = "kg_extraction_jobs"

SOURCE_ANNOUNCEMENT = "announcement"
SOURCE_ANNUAL_REPORT = "annual_report"
SOURCE_RESEARCH_REPORT = "research_report"
SOURCE_IRM = "irm"
SOURCE_MARKET = "market"
SOURCE_NEWS = "news"
SOURCE_UPLOAD = "upload"

SOURCE_TYPES = frozenset({
    SOURCE_ANNOUNCEMENT,
    SOURCE_ANNUAL_REPORT,
    SOURCE_RESEARCH_REPORT,
    SOURCE_IRM,
    SOURCE_MARKET,
    SOURCE_NEWS,
    SOURCE_UPLOAD,
})

JOB_COMBINED = "combined"
JOB_VECTOR = "vector"
JOB_TYPES = frozenset({JOB_COMBINED, JOB_VECTOR})

STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"
JOB_STATUSES = frozenset({
    STATUS_PENDING,
    STATUS_RUNNING,
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_SKIPPED,
})


@dataclass(slots=True)
class EvidenceInput:
    """Input schema for mechanical Evidence creation."""

    source_type: str
    source_name: str
    text_excerpt: str
    source_id: str
    subject_hint: dict[str, Any] = field(default_factory=dict)
    publish_date: str | datetime | None = None
    observed_at: str | datetime | None = None
    source_ref: dict[str, Any] = field(default_factory=dict)
    confidence: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def text_checksum(text: str) -> str:
    """Return a stable SHA256 checksum for normalized evidence text."""
    return _sha256((text or "").strip())


def stable_evidence_id(
    source_type: str,
    source_id: str,
    chunk_index: int,
    text: str,
) -> str:
    """Generate deterministic Evidence ID from source identity and content."""
    payload = "\n".join([
        str(source_type or ""),
        str(source_id or ""),
        str(chunk_index),
        text_checksum(text),
    ])
    return f"EV:{_sha256(payload)}"


def stable_job_id(
    evidence_id: str,
    job_type: str,
    extractor_version: str = EXTRACTOR_VERSION,
) -> str:
    """Generate deterministic extraction job ID."""
    payload = "\n".join([
        str(evidence_id or ""),
        str(job_type or ""),
        str(extractor_version or ""),
    ])
    return f"JOB:{_sha256(payload)}"


def default_source_confidence(source_type: str) -> float:
    """Base confidence by source type; no investment judgement is encoded."""
    source_type = (source_type or "").strip()
    if source_type in {SOURCE_ANNOUNCEMENT, SOURCE_ANNUAL_REPORT}:
        return 0.95
    if source_type == SOURCE_MARKET:
        return 1.0
    if source_type == SOURCE_IRM:
        return 0.85
    if source_type == SOURCE_RESEARCH_REPORT:
        return 0.80
    if source_type == SOURCE_NEWS:
        return 0.65
    if source_type == SOURCE_UPLOAD:
        return 0.70
    return 0.70
