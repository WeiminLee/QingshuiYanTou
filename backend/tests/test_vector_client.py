from __future__ import annotations

from app.knowledge.vector_client import (
    PlaceholderEmbedding,
    SearchResult,
    VectorClient,
    VectorRecord,
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
