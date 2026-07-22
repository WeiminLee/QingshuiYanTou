# KG 2-Hop Secondary Signals Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the signal layer so secondary signals are generated from KG-backed 2-hop propagation paths instead of free-form or purely template propagation.

**Architecture:** Keep the existing `signals` package and persistence model. Add a focused KG propagation planner that expands each `SignalCandidate` into 1-2 hop `PropagationCandidate` records using a small graph adapter interface; ingestion code will prefer KG paths and fall back to the existing lightweight propagation when KG is unavailable or empty.

**Tech Stack:** Python, FastAPI backend, SQLAlchemy async, Neo4j async driver via existing app core, pytest.

## Global Constraints

- Signals are a system-level data layer and can be consumed by any module.
- Signal layering is explicit: primary signals describe direct event impact; secondary signals describe KG-propagated read-through.
- Secondary signals must be based on KG paths, not free LLM target invention.
- First implementation supports KG paths up to 2 hops only.
- Preserve existing signal APIs and persistence tables.
- Keep implementation TDD: write failing tests, verify red, implement minimal code, verify green.

---

## File Structure

- Create `backend/app/signals/kg_propagation.py`: KG path data types, scoring, secondary type mapping, and graph adapter.
- Modify `backend/app/signals/evidence_ingestion.py`: use KG propagation for evidence-backed signals.
- Modify `backend/app/signals/event_ingestion.py`: use KG propagation for news/event-backed signals.
- Test `backend/tests/signals/test_kg_propagation.py`: pure unit tests for 2-hop conversion and scoring.
- Test `backend/tests/signals/test_evidence_ingestion.py`: verifies evidence ingestion prefers KG propagation and falls back when empty.

---

### Task 1: KG Propagation Core

**Files:**
- Create: `backend/app/signals/kg_propagation.py`
- Test: `backend/tests/signals/test_kg_propagation.py`

**Interfaces:**
- Consumes: `app.signals.extractor.SignalCandidate`
- Produces:
  - `KGEdge(src: str, rel_type: str, tgt: str, weight: float = 1.0, text: str = "", target_type: str = "entity")`
  - `KGPath(nodes: list[str], edges: list[KGEdge])`
  - `KGPathProvider.fetch_paths(entity: str, *, max_hops: int = 2) -> list[KGPath]`
  - `build_kg_propagations(candidate: SignalCandidate, paths: list[KGPath]) -> list[PropagationCandidate]`

- [ ] **Step 1: Write failing tests**

```python
from datetime import UTC, datetime

from app.signals.extractor import SignalCandidate
from app.signals.kg_propagation import KGEdge, KGPath, build_kg_propagations


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
```

- [ ] **Step 2: Run tests to verify red**

Run: `cd backend && .venv/bin/python -m pytest tests/signals/test_kg_propagation.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'app.signals.kg_propagation'`.

- [ ] **Step 3: Implement minimal KG propagation core**

Create `backend/app/signals/kg_propagation.py` with dataclasses, relation-to-secondary-type mapping, path scoring, and `build_kg_propagations`.

- [ ] **Step 4: Run tests to verify green**

Run: `cd backend && .venv/bin/python -m pytest tests/signals/test_kg_propagation.py -q`

Expected: PASS.

---

### Task 2: Ingestion Integration

**Files:**
- Modify: `backend/app/signals/evidence_ingestion.py`
- Modify: `backend/app/signals/event_ingestion.py`
- Test: `backend/tests/signals/test_evidence_ingestion.py`

**Interfaces:**
- Consumes: `build_kg_propagations(candidate, paths)`
- Produces: `extract_evidence_signal_records(evidence, kg_paths_by_subject: dict[str, list[KGPath]] | None = None)` and equivalent event helper support.

- [ ] **Step 1: Write failing ingestion tests**

```python
from app.signals.evidence_ingestion import extract_evidence_signal_records
from app.signals.kg_propagation import KGEdge, KGPath


def test_evidence_signals_prefer_kg_propagation_when_paths_exist():
    evidence = {
        "evidence_id": "EV:1",
        "source_type": "announcement",
        "source_name": "公告",
        "text_excerpt": "公司 800G 光模块已批量交付客户。",
        "subject_hint": {"title": "中际旭创 800G 光模块批量交付"},
        "metadata": {"tags": ["中际旭创"]},
    }
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

    signals, propagations = extract_evidence_signal_records(evidence, kg_paths_by_subject=paths)

    assert signals
    assert propagations
    assert propagations[0]["target_name"] == "光芯片"
    assert propagations[0]["metadata"]["secondary_type"] == "supply_chain_validation"


def test_evidence_signals_fall_back_to_lightweight_propagation_when_no_kg_paths():
    evidence = {
        "evidence_id": "EV:1",
        "source_type": "announcement",
        "source_name": "公告",
        "text_excerpt": "公司 800G 光模块已批量交付客户。",
        "subject_hint": {"title": "中际旭创 800G 光模块批量交付"},
        "metadata": {"tags": ["中际旭创"]},
    }

    signals, propagations = extract_evidence_signal_records(evidence, kg_paths_by_subject={})

    assert signals
    assert propagations
    assert propagations[0]["relation_path"]
```

- [ ] **Step 2: Run tests to verify red**

Run: `cd backend && .venv/bin/python -m pytest tests/signals/test_evidence_ingestion.py -q`

Expected: FAIL because `extract_evidence_signal_records` does not accept `kg_paths_by_subject`.

- [ ] **Step 3: Implement integration**

Update evidence and event ingestion helpers to accept optional `kg_paths_by_subject`. For each primary signal candidate, call KG propagation when paths exist for `candidate.subject_name`; otherwise keep existing `build_lightweight_propagations`.

- [ ] **Step 4: Run tests to verify green**

Run: `cd backend && .venv/bin/python -m pytest tests/signals/test_kg_propagation.py tests/signals/test_evidence_ingestion.py -q`

Expected: PASS.

---

## Self-Review

- Spec coverage: implements two-layer signal design, KG 2-hop propagation, fallback behavior, and reusable signal consumption records.
- Placeholder scan: no deferred behavior is required for this slice; LLM scoring, 3-hop propagation, and market reaction validation are explicitly outside this plan.
- Type consistency: `KGPath`, `KGEdge`, and `PropagationCandidate` are the only new cross-file interfaces.
