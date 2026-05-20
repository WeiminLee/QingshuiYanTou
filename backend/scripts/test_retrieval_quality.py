"""
Qdrant P99 延迟实测

Tests Qdrant vector search P99 latency < 500ms over 20 iterations.

Uses the same proxy-clearing pattern as vector_client.py to avoid
SOCKS proxy interference with localhost connections.

Run:
  uv run --directory backend python scripts/test_retrieval_quality.py --iterations 20
"""
import os as _no_proxy_os
for _k in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "all_proxy", "ALL_PROXY"):
    _no_proxy_os.environ[_k] = ""

import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ── Load settings (qdrant_url, qdrant_collection) ──────────────────────────

def _load_env():
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_bytes().decode("utf-8", errors="replace").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                _no_proxy_os.environ.setdefault(k.strip(), v.strip())

_load_env()

try:
    from app.config import settings
    QDRANT_URL = getattr(settings, "qdrant_url", "http://localhost:6333")
    COLLECTION = getattr(settings, "qdrant_collection", "qingshui")
except Exception:
    QDRANT_URL = "http://localhost:6333"
    COLLECTION = "qingshui"

# ── Qdrant client (no proxy) ───────────────────────────────────────────────

_client = None
_vector_size = None

def _get_client():
    global _client, _vector_size
    if _client is None:
        from qdrant_client import QdrantClient
        _client = QdrantClient(url=QDRANT_URL, prefer_grpc=True)
        logger.info("Qdrant client initialised at %s", QDRANT_URL)
    return _client

def _discover_collection():
    """Find first available collection and its vector size."""
    client = _get_client()
    collections = client.get_collections()
    for c in collections.collections:
        try:
            info = client.get_collection(c.name)
            # VectorParams.size gives the dimension
            params = info.config.params
            size = getattr(params.vectors, 'size', None)
            if size:
                return c.name, size
        except Exception:
            pass
    return None, None

# ── Test queries (semiconductor / optical sector terms) ──────────────────────

TEST_QUERIES = [
    "中际旭创光模块产品",
    "半导体先进封装产业链",
    "光器件上游供应商",
    "天孚通信产品布局",
    "台积电晶圆制造",
]

SEARCH_LIMIT = 10


def _search_via_grpc(query_vector, collection, limit=10):
    """Direct gRPC search via qdrant_client 1.17.x (query_points API)."""
    client = _get_client()
    results = client.query_points(
        collection_name=collection,
        query=query_vector,
        limit=limit,
        with_payload=False,
    )
    return results


def _search_via_rest(query_vector, collection, limit=10):
    """Fallback REST search via httpx."""
    import httpx
    with httpx.Client(timeout=10.0) as http:
        resp = http.post(
            f"{QDRANT_URL}/collections/{collection}/points/search",
            json={
                "vector": query_vector,
                "limit": limit,
                "with_payload": False,
            },
        )
        resp.raise_for_status()
        return resp.json().get("result", [])


def run_latency_test(iterations: int = 20) -> list[float]:
    """
    Run `iterations` vector searches and return latencies in seconds.
    Uses a fixed zero vector matching the collection's vector dimension.
    """
    global _vector_size

    collection, vec_size = _discover_collection()
    if collection is None:
        logger.warning("No Qdrant collection found — using fallback (zero results)")
        collection = COLLECTION
        vec_size = 2560  # default fallback

    _vector_size = vec_size
    logger.info("Using collection=%s vector_size=%d", collection, vec_size)

    query_vector = [0.0] * _vector_size

    latencies = []
    for i in range(iterations):
        query_label = TEST_QUERIES[i % len(TEST_QUERIES)]
        t0 = time.perf_counter()
        try:
            _search_via_grpc(query_vector, collection, limit=SEARCH_LIMIT)
            latency = time.perf_counter() - t0
            latencies.append(latency)
            logger.debug("iter %d/%d [%s] %.3fs", i + 1, iterations, query_label, latency)
        except Exception as e:
            logger.warning("iter %d/%d failed: %s", i + 1, iterations, e)
            # Record as 5s on failure (large enough to fail P99 threshold)
            latencies.append(5.0)

    return latencies


def compute_stats(latencies: list[float]) -> dict:
    sorted_latencies = sorted(latencies)
    n = len(sorted_latencies)
    p50_idx = int(n * 0.50)
    p90_idx = int(n * 0.90)
    p99_idx = int(n * 0.99)

    return {
        "count": n,
        "min": min(sorted_latencies),
        "max": max(sorted_latencies),
        "mean": sum(sorted_latencies) / n,
        "p50": sorted_latencies[max(0, p50_idx - 1)],
        "p90": sorted_latencies[max(0, p90_idx - 1)],
        "p99": sorted_latencies[min(n - 1, p99_idx)],
    }


def main():
    parser = argparse.ArgumentParser(description="Qdrant P99 latency test")
    parser.add_argument("--iterations", type=int, default=20,
                        help="Number of search iterations (default: 20)")
    args = parser.parse_args()

    print("=" * 60)
    print(f"Qdrant P99 Latency Test — {args.iterations} iterations")
    print(f"URL: {QDRANT_URL}  (Default collection: {COLLECTION})")
    print("=" * 60)

    latencies = run_latency_test(iterations=args.iterations)
    stats = compute_stats(latencies)

    print()
    print(f"  Iterations : {stats['count']}")
    print(f"  Min        : {stats['min']*1000:.1f}ms")
    print(f"  Mean       : {stats['mean']*1000:.1f}ms")
    print(f"  Max        : {stats['max']*1000:.1f}ms")
    print(f"  P50        : {stats['p50']*1000:.1f}ms")
    print(f"  P90        : {stats['p90']*1000:.1f}ms")
    print(f"  P99        : {stats['p99']*1000:.1f}ms")
    print()

    P99_MS = stats["p99"] * 1000
    THRESHOLD_MS = 500.0

    if P99_MS < THRESHOLD_MS:
        print(f"PASS: P99 latency {P99_MS:.1f}ms < {THRESHOLD_MS}ms threshold")
        return 0
    else:
        print(f"FAIL: P99 latency {P99_MS:.1f}ms >= {THRESHOLD_MS}ms threshold")
        return 1


if __name__ == "__main__":
    sys.exit(main())
