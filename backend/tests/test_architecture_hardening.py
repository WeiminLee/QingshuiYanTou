"""Regression tests for shared architecture hardening constraints."""

from __future__ import annotations

import ast
import inspect
from datetime import UTC
from pathlib import Path

import app.knowledge.evidence_service as evidence_service
from app.knowledge.evidence_builders import build_file_evidence, build_irm_evidence

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _utcnow_calls(relative_path: str) -> list[int]:
    source = (BACKEND_ROOT / relative_path).read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "utcnow"
            and isinstance(func.value, ast.Name)
            and func.value.id == "datetime"
        ):
            calls.append(node.lineno)
    return calls


def test_knowledge_runtime_uses_timezone_aware_utc() -> None:
    modules = [
        "app/knowledge/evidence_builders.py",
        "app/knowledge/evidence_service.py",
        "app/knowledge/structured_fact_service.py",
        "app/knowledge/file_indexer.py",
        "app/knowledge/pdf_rotator.py",
        "app/knowledge/irm_extractor.py",
    ]
    offenders = {module: _utcnow_calls(module) for module in modules}
    offenders = {module: lines for module, lines in offenders.items() if lines}
    assert offenders == {}


def test_evidence_builders_emit_timezone_aware_utc_observed_at() -> None:
    irm = build_irm_evidence({"question": "Q", "answer": "A"})
    file_evidence = build_file_evidence(
        {"file_path": "/tmp/a.pdf", "file_hash": "h", "file_type": "pdf"},
        "content",
        "announcement",
        "contract",
        "300001.SZ",
        max_chunks=1,
    )[0]

    assert irm.observed_at.tzinfo is UTC
    assert file_evidence.observed_at.tzinfo is UTC


def test_evidence_service_has_single_timezone_aware_clock() -> None:
    source = inspect.getsource(evidence_service)
    assert "datetime.now(timezone.utc)" in source
    assert "datetime.utcnow" not in source


def test_vector_defaults_are_configurable_and_resettable() -> None:
    from app.config import settings
    from app.knowledge import vector_client

    assert settings.embedding_dimension > 0
    assert vector_client.PlaceholderEmbedding().dimension() == settings.embedding_dimension

    class DummyClient:
        def __init__(self):
            self.closed = False

        def disconnect(self):
            self.closed = True

    class DummyEmbedding(vector_client.EmbeddingModelBase):
        def __init__(self):
            self.closed = False

        def embed(self, text: str) -> list[float]:
            return [0.0]

        def embed_batch(self, texts: list[str]) -> list[list[float]]:
            return [[0.0] for _ in texts]

        def dimension(self) -> int:
            return 1

        def close(self) -> None:
            self.closed = True

    client = DummyClient()
    embedding = DummyEmbedding()
    vector_client.set_vector_client(client)
    vector_client.set_embedding_model(embedding)

    vector_client.reset_vector_state(close=True)

    assert client.closed is True
    assert embedding.closed is True


def test_parser_and_schema_versions_are_centralized() -> None:
    from app.core import metadata

    assert metadata.CURRENT_PARSER_VERSION == "v1.0"
    assert metadata.CURRENT_KG_SCHEMA_VERSION == "v4"
    assert metadata.SOURCE_CLOUD_API in metadata.SOURCE_META_MAP
    assert {meta.parser_version for meta in metadata.SOURCE_META_MAP.values()} == {metadata.CURRENT_PARSER_VERSION}


def test_runtime_models_do_not_hardcode_parser_version_defaults() -> None:
    source = (BACKEND_ROOT / "app/models/models.py").read_text(encoding="utf-8")
    assert 'server_default="v1.0"' not in source
    assert "CURRENT_PARSER_VERSION" in source


def test_structured_fact_upsert_uses_single_write_transaction() -> None:
    import app.knowledge.structured_fact_service as service

    source = inspect.getsource(service.upsert_structured_fact)
    assert "write_transaction()" in source
    assert "run_write(" not in source
