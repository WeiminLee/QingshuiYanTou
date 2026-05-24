from __future__ import annotations

import sys
import types
from typing import Any

import pytest

import app.knowledge.vector_client as vector_client_module
from app.knowledge.irm_extractor import _upsert_qa_vector
from app.knowledge.vector_client import (
    COLLECTION_CHUNKS,
    COLLECTION_ENTITIES,
    COLLECTION_QA,
    COLLECTION_RELATIONS,
    PlaceholderEmbedding,
    QdrantClient,
    SearchResult,
    VectorClient,
    VectorRecord,
    init_collections,
    reset_vector_state,
    set_embedding_model,
    set_vector_client,
    upsert_evidence_chunk_vector,
)


class FailingVectorClient(VectorClient):
    def connect(self) -> None:
        pass

    def disconnect(self) -> None:
        pass

    def create_collection(self, name: str, dimension: int, description: str = "", metric: str = "COSINE") -> bool:
        return True

    def upsert(self, collection: str, records: list[VectorRecord]) -> bool:
        return False

    def search(
        self,
        collection: str,
        query_vector: list[float],
        top_k: int = 10,
        filter_expr: str | None = None,
    ) -> list[SearchResult]:
        return []

    def delete_collection(self, name: str) -> bool:
        return True


def test_upsert_evidence_chunk_vector_returns_false_when_client_upsert_fails() -> None:
    reset_vector_state(close=True)
    set_embedding_model(PlaceholderEmbedding(dimension=8))
    set_vector_client(FailingVectorClient())
    try:
        ok = upsert_evidence_chunk_vector({
            "evidence_id": "EV:test",
            "text_excerpt": "公司公告称产品已经量产。",
            "source_type": "announcement",
            "source_name": "测试公告",
            "subject_hint": {"ts_code": "300001.SZ"},
            "source_ref": {"chunk_index": 0},
            "checksum": "abc",
        })
        assert ok is False
    finally:
        reset_vector_state(close=True)


def test_init_collections_returns_false_when_create_collection_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    class CreateFailingQdrantClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def create_collection(
            self,
            name: str,
            dimension: int,
            description: str = "",
            metric: str = "COSINE",
        ) -> bool:
            return name != COLLECTION_CHUNKS

    monkeypatch.setattr(vector_client_module, "QdrantClient", CreateFailingQdrantClient)

    results = init_collections(embedder=PlaceholderEmbedding(dimension=8))

    assert results == {
        COLLECTION_ENTITIES: True,
        COLLECTION_RELATIONS: True,
        COLLECTION_CHUNKS: False,
        COLLECTION_QA: True,
    }


def test_qdrant_collection_methods_respect_native_bool_returns(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeNativeQdrantClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def collection_exists(self, name: str) -> bool:
            return False

        def create_collection(self, *args: Any, **kwargs: Any) -> bool:
            return False

        def delete_collection(self, *args: Any, **kwargs: Any) -> bool:
            return False

    install_fake_qdrant(monkeypatch, FakeNativeQdrantClient)
    client = QdrantClient()

    assert client.create_collection("test_collection", 8) is False
    assert client.delete_collection("test_collection") is False


def test_qdrant_upsert_returns_false_when_native_status_is_not_completed(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeNativeQdrantClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def collection_exists(self, name: str) -> bool:
            return True

        def upsert(self, *args: Any, **kwargs: Any) -> Any:
            return types.SimpleNamespace(status="failed")

    install_fake_qdrant(monkeypatch, FakeNativeQdrantClient)
    client = QdrantClient()

    ok = client.upsert(
        "test_collection",
        [VectorRecord(id="point-1", vector=[0.1, 0.2], payload={})],
    )

    assert ok is False


def test_qdrant_upsert_returns_false_when_native_result_is_false(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeNativeQdrantClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def collection_exists(self, name: str) -> bool:
            return True

        def upsert(self, *args: Any, **kwargs: Any) -> bool:
            return False

    install_fake_qdrant(monkeypatch, FakeNativeQdrantClient)
    client = QdrantClient()

    ok = client.upsert(
        "test_collection",
        [VectorRecord(id="point-1", vector=[0.1, 0.2], payload={})],
    )

    assert ok is False


def test_qdrant_upsert_returns_false_when_native_result_dict_status_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeNativeQdrantClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def collection_exists(self, name: str) -> bool:
            return True

        def upsert(self, *args: Any, **kwargs: Any) -> dict[str, str]:
            return {"status": "failed"}

    install_fake_qdrant(monkeypatch, FakeNativeQdrantClient)
    client = QdrantClient()

    ok = client.upsert(
        "test_collection",
        [VectorRecord(id="point-1", vector=[0.1, 0.2], payload={})],
    )

    assert ok is False


def test_qdrant_upsert_returns_false_and_skips_upsert_when_collection_create_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeNativeQdrantClient:
        upsert_called = False

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def collection_exists(self, name: str) -> bool:
            return False

        def create_collection(self, *args: Any, **kwargs: Any) -> bool:
            return False

        def upsert(self, *args: Any, **kwargs: Any) -> Any:
            type(self).upsert_called = True
            return types.SimpleNamespace(status="completed")

    install_fake_qdrant(monkeypatch, FakeNativeQdrantClient)
    client = QdrantClient()

    ok = client.upsert(
        "test_collection",
        [VectorRecord(id="point-1", vector=[0.1, 0.2], payload={})],
    )

    assert ok is False
    assert FakeNativeQdrantClient.upsert_called is False


def test_qdrant_upsert_returns_true_for_completed_enum_status(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeStatus:
        name = "COMPLETED"

    class FakeNativeQdrantClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def collection_exists(self, name: str) -> bool:
            return True

        def upsert(self, *args: Any, **kwargs: Any) -> Any:
            return types.SimpleNamespace(status=FakeStatus())

    install_fake_qdrant(monkeypatch, FakeNativeQdrantClient)
    client = QdrantClient()

    ok = client.upsert(
        "test_collection",
        [VectorRecord(id="point-1", vector=[0.1, 0.2], payload={})],
    )

    assert ok is True


def test_qdrant_collection_methods_treat_none_return_as_success(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeNativeQdrantClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def collection_exists(self, name: str) -> bool:
            return False

        def create_collection(self, *args: Any, **kwargs: Any) -> None:
            return None

        def delete_collection(self, *args: Any, **kwargs: Any) -> None:
            return None

    install_fake_qdrant(monkeypatch, FakeNativeQdrantClient)
    client = QdrantClient()

    assert client.create_collection("test_collection", 8) is True
    assert client.delete_collection("test_collection") is True


def test_qdrant_search_passes_filter_expr_to_query_points(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    class FakePoint:
        id = "point-1"
        score = 0.9
        payload = {"ts_code": "300001.SZ"}

    class FakeResult:
        points = [FakePoint()]

    class FakeNativeQdrantClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def query_points(self, **kwargs: Any) -> FakeResult:
            captured.update(kwargs)
            return FakeResult()

    install_fake_qdrant(monkeypatch, FakeNativeQdrantClient)
    client = QdrantClient(url="http://qdrant.test")

    result = client.search(
        collection="doc_chunks",
        query_vector=[0.1, 0.2],
        top_k=3,
        filter_expr='ts_code == "300001.SZ"',
    )

    assert len(result) == 1
    assert captured["collection_name"] == "doc_chunks"
    assert captured["limit"] == 3
    assert captured["query_filter"] is not None


def test_upsert_qa_vector_returns_false_when_client_upsert_fails() -> None:
    reset_vector_state(close=True)
    set_embedding_model(PlaceholderEmbedding(dimension=8))
    set_vector_client(FailingVectorClient())
    try:
        ok = _upsert_qa_vector(
            qa_id="QA:test",
            question="产品是否量产？",
            answer="公司表示产品已经量产。",
            ts_code="300001.SZ",
            company_name="测试公司",
            ann_date="2026-05-24",
        )
        assert ok is False
    finally:
        reset_vector_state(close=True)


def install_fake_qdrant(monkeypatch: pytest.MonkeyPatch, native_client: type) -> None:
    fake_qdrant = types.ModuleType("qdrant_client")
    fake_qdrant.QdrantClient = native_client

    fake_models = types.ModuleType("qdrant_client.models")

    class FakeDistance:
        COSINE = "COSINE"
        EUCLID = "EUCLID"
        DOT = "DOT"

    class FakeVectorParams:
        def __init__(self, size: int, distance: Any) -> None:
            self.size = size
            self.distance = distance

    class FakePointStruct:
        def __init__(self, id: str, vector: list[float], payload: dict[str, Any]) -> None:
            self.id = id
            self.vector = vector
            self.payload = payload

    class FakeMatchValue:
        def __init__(self, value: Any) -> None:
            self.value = value

    class FakeFieldCondition:
        def __init__(self, key: str, match: FakeMatchValue) -> None:
            self.key = key
            self.match = match

    class FakeFilter:
        def __init__(self, must: list[FakeFieldCondition]) -> None:
            self.must = must

    fake_models.Distance = FakeDistance
    fake_models.VectorParams = FakeVectorParams
    fake_models.PointStruct = FakePointStruct
    fake_models.MatchValue = FakeMatchValue
    fake_models.FieldCondition = FakeFieldCondition
    fake_models.Filter = FakeFilter

    monkeypatch.setitem(sys.modules, "qdrant_client", fake_qdrant)
    monkeypatch.setitem(sys.modules, "qdrant_client.models", fake_models)
