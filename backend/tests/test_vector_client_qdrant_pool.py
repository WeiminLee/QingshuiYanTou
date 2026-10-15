from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.knowledge.vector_client import QdrantClient


def _fake_qdrant(points=None):
    cli = MagicMock()
    cli.query_points.return_value = MagicMock(points=points or [])
    return cli


def test_search_reuses_cached_client_across_calls():
    svc = QdrantClient(url="http://localhost:6333")
    fake = _fake_qdrant()
    with patch.object(svc, "_create_qdrant_client", return_value=fake) as m:
        svc.search("doc_chunks", [0.1] * 4, top_k=1)
        svc.search("doc_chunks", [0.1] * 4, top_k=1)
    assert m.call_count == 1
    assert fake.query_points.call_count == 2


def test_search_drops_cached_client_after_failure_then_rebuilds():
    svc = QdrantClient(url="http://localhost:6333")
    bad = _fake_qdrant()
    bad.query_points.side_effect = TimeoutError("timed out")
    with patch.object(svc, "_create_qdrant_client", return_value=bad):
        assert svc.search("doc_chunks", [0.1] * 4) == []
    assert svc._client_instance is None

    good = _fake_qdrant()
    with patch.object(svc, "_create_qdrant_client", return_value=good) as m:
        assert svc.search("doc_chunks", [0.1] * 4) == []
    assert m.call_count == 1
    assert svc._client_instance is good


def test_client_instance_passed_timeout():
    svc = QdrantClient(url="http://localhost:6333", timeout=42.0)
    with patch("qdrant_client.QdrantClient") as m:
        svc._get_qdrant_client()
        assert m.call_args.kwargs.get("timeout") == 42.0
