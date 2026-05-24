from __future__ import annotations

# Qdrant 部署在 localhost，不应走全局 SOCKS 代理
# httpx 在 import 时读取代理环境变量，必须在所有 qdrant_client 导入前清空
import os as _qdrant_no_proxy_os
_SAVED_PROXIES = {}  # 暂存原始代理值，get_proxies() 恢复
for _k in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "all_proxy", "ALL_PROXY"):
    _SAVED_PROXIES[_k] = _qdrant_no_proxy_os.environ.get(_k, "")
    _qdrant_no_proxy_os.environ[_k] = ""

"""
向量数据库客户端抽象层（Qdrant）

存储策略（与 Neo4j 互补）：
  - Neo4j：结构化关系（实体节点、关系边、时序字段）
  - Vector DB：非结构化语义（实体描述、关系描述、文档片段、问答摘要）

Collection 设计：
  entities    — 实体描述向量（entity_id + entity_name + description + ts_code）
  relations   — 关系描述向量（from_entity + to_entity + relation_description）
  doc_chunks  — 文档分块向量（content + heading + source）
  qa_flash    — 研报摘要向量（question + answer + source）
"""

import hashlib
import logging
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)


def get_proxies() -> dict:
    """返回原始代理配置，供 requests/httpx 恢复访问外网"""
    return _SAVED_PROXIES.copy()

# ── 全局配置 ──────────────────────────────────────────────────────────────

_vector_client: Optional["VectorClient"] = None
_embedding_model: Optional["EmbeddingModelBase"] = None


def default_embedding_dimension() -> int:
    """Return the configured fallback embedding dimension."""
    from app.config import settings

    return int(getattr(settings, "embedding_dimension", 2560) or 2560)


def get_vector_client() -> "VectorClient":
    """获取全局向量客户端（延迟初始化）"""
    global _vector_client
    if _vector_client is None:
        from app.config import settings

        _vector_client = QdrantClient(
            url=getattr(settings, "qdrant_url", "http://localhost:6333"),
            api_key=getattr(settings, "qdrant_api_key", ""),
            collection_name=getattr(settings, "qdrant_collection", "qingshui_default"),
        )
        logger.info("向量库客户端初始化: Qdrant at %s", getattr(settings, "qdrant_url", "http://localhost:6333"))
    return _vector_client


def get_embedding_model() -> "EmbeddingModelBase":
    """获取全局 Embedding 模型（懒加载）。

    优先级：
    1. Hunyuan API key（生产环境 - D-06）
    2. Local embedding service URL（遗留回退）
    3. PlaceholderEmbedding（仅开发环境）
    """
    global _embedding_model
    if _embedding_model is None:
        from app.config import settings

        # 优先级 1: Hunyuan (D-06)
        sf_key = getattr(settings, "hunyuan_api_key", None) or ""
        if sf_key:
            _embedding_model = HunyuanEmbedding(
                api_key=sf_key,
                model=getattr(settings, "hunyuan_model", "hunyuan-embedding"),
                api_url=getattr(settings, "hunyuan_embedding_url",
                               "https://api.hunyuan.cloud.tencent.com/v1/embeddings"),
            )
            logger.info(f"Embedding 模型: Hunyuan ({_embedding_model._model})")
            return _embedding_model

        # 优先级 2: Local embedding service（遗留）
        emb_url = getattr(settings, "embedding_api_url", None) or ""
        emb_key = getattr(settings, "embedding_api_key", "") or ""
        if emb_url:
            _embedding_model = LocalEmbedding(api_url=emb_url, api_key=emb_key)
            logger.info(f"Embedding 模型: LocalEmbedding ({emb_url})")
            return _embedding_model

        # 优先级 3: Placeholder（仅开发环境）
        _embedding_model = PlaceholderEmbedding()
        logger.warning("Embedding 模型: PlaceholderEmbedding（请在 .env 配置 HUNYUAN_API_KEY 用于生产）")
    return _embedding_model


def set_vector_client(client: "VectorClient") -> None:
    """注入 mock/测试客户端"""
    global _vector_client
    _vector_client = client


def set_embedding_model(model: "EmbeddingModelBase") -> None:
    """注入自定义 Embedding 模型（用于测试）"""
    global _embedding_model
    _embedding_model = model


def reset_vector_state(close: bool = False) -> None:
    """Reset global vector client and embedding model state."""
    global _vector_client, _embedding_model
    client = _vector_client
    embedding = _embedding_model
    _vector_client = None
    _embedding_model = None
    if not close:
        return
    for resource in (client, embedding):
        if resource is None:
            continue
        close_fn = getattr(resource, "close", None) or getattr(resource, "disconnect", None)
        if callable(close_fn):
            close_fn()


# ── Embedding 模型抽象 ────────────────────────────────────────────────────

class EmbeddingModelBase(ABC):
    """Embedding 模型接口"""

    @abstractmethod
    def embed(self, text: str) -> list[float]:
        """单条文本 → 向量"""
        raise NotImplementedError

    @abstractmethod
    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """批量文本 → 向量列表"""
        raise NotImplementedError

    @abstractmethod
    def dimension(self) -> int:
        """返回向量维度"""
        raise NotImplementedError


class LocalEmbedding(EmbeddingModelBase):
    """
    本地 embedding 服务（http://10.57.230.169:8000/v1/embeddings）。

    请求格式：POST /v1/embeddings  { "texts": ["...", "..."] }
    返回格式：{ "embeddings": [[2560 floats], ...] }
    """

    def __init__(
        self,
        api_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: float = 30.0,
    ):
        # BUG-19 修复：从 settings 读取默认值
        if api_url is None:
            from app.config import settings
            api_url = settings.embedding_api_url or "http://localhost:8000"
        if api_key is None:
            from app.config import settings
            api_key = settings.embedding_api_key or None

        self._api_url = api_url.rstrip("/") + "/v1/embeddings"
        self._api_key = api_key
        self._timeout = timeout
        self._async_client: Optional[httpx.AsyncClient] = None
        self._sync_client: Optional[httpx.Client] = None
        self._dim: Optional[int] = None

    async def _aget(self) -> httpx.AsyncClient:
        if self._async_client is None:
            headers = {}
            if self._api_key:
                headers["Authorization"] = f"Bearer {self._api_key}"
            self._async_client = httpx.AsyncClient(
                timeout=self._timeout, headers=headers, trust_env=False,
            )
        return self._async_client

    def _get_sync(self) -> httpx.Client:
        """同步客户端（用于 embed() 同步调用）"""
        if self._sync_client is None:
            headers = {}
            if self._api_key:
                headers["Authorization"] = f"Bearer {self._api_key}"
            self._sync_client = httpx.Client(
                timeout=self._timeout, headers=headers, trust_env=False,
            )
        return self._sync_client

    async def aclose(self) -> None:
        """关闭异步客户端连接池"""
        if self._async_client is not None:
            await self._async_client.aclose()
            self._async_client = None

    def close(self) -> None:
        """关闭同步客户端连接池"""
        if self._sync_client is not None:
            self._sync_client.close()
            self._sync_client = None

    async def __aenter__(self) -> "LocalEmbedding":
        return self

    async def __aexit__(self, *args) -> None:
        await self.aclose()

    def __enter__(self) -> "LocalEmbedding":
        return self

    def __exit__(self, *args) -> None:
        self.close()

    async def aembed(self, texts: list[str]) -> list[list[float]]:
        client = await self._aget()
        payload = {"texts": texts}
        try:
            resp = await client.post(self._api_url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            embeddings: list[list[float]] = data["embeddings"]
            if self._dim is None and embeddings:
                self._dim = len(embeddings[0])
                logger.info(f"[LocalEmbedding] 检测到向量维度: {self._dim}")
            return embeddings
        except Exception as exc:
            logger.error(f"[LocalEmbedding] 调用失败: {exc}", exc_info=True)
            raise

    def embed(self, text: str) -> list[float]:
        """同步接口：upsert_entity_vector 等同步函数需要"""
        client = self._get_sync()
        payload = {"texts": [text]}
        resp = client.post(self._api_url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        embeddings: list[list[float]] = data["embeddings"]
        if self._dim is None and embeddings:
            self._dim = len(embeddings[0])
            logger.info(f"[LocalEmbedding] 同步检测向量维度: {self._dim}")
        return embeddings[0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError("embed_batch is async-only; use aembed()")

    def dimension(self) -> int:
        if self._dim is None:
            return default_embedding_dimension()
        return self._dim


class PlaceholderEmbedding(EmbeddingModelBase):
    """占位实现（本地服务不可用时用于接口联调）"""

    def __init__(self, dimension: int | None = None):
        self._dim = int(dimension or default_embedding_dimension())

    def embed(self, text: str) -> list[float]:
        h = hashlib.sha256(text.encode()).digest()
        vec = list(h) + [0] * max(0, self._dim - len(h))
        import math
        norm = math.sqrt(sum(v * v for v in vec))
        return [v / norm for v in vec[: self._dim]]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]

    def dimension(self) -> int:
        return self._dim


class HunyuanEmbedding(EmbeddingModelBase):
    """
    Tencent Cloud Hunyuan embedding API.

    Endpoint: https://api.hunyuan.cloud.tencent.com/v1/embeddings
    Model: hunyuan-embedding

    API format:
    - Request: POST {"input": [...], "model": "hunyuan-embedding"}
    - Response: {"data": [{"embedding": [...]}, ...]}
    """

    def __init__(
        self,
        api_key: str = "",
        model: str = "hunyuan-embedding",
        api_url: str = "https://api.hunyuan.cloud.tencent.com/v1/embeddings",
        timeout: float = 60.0,
        max_retries: int = 3,
    ):
        self._api_key = api_key
        self._model = model
        self._api_url = api_url
        self._timeout = timeout
        self._max_retries = max_retries
        self._dim: int | None = None
        self._sync_client: httpx.Client | None = None
        self._async_client: httpx.AsyncClient | None = None

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def embed(self, text: str) -> list[float]:
        """Synchronous embed using a synchronous HTTP client."""
        client = self._get_sync()
        resp = client.post(
            self._api_url,
            json={"input": [text], "model": self._model},
            headers=self._headers(),
        )
        resp.raise_for_status()
        data = resp.json()
        embeddings = [item["embedding"] for item in data["data"]]
        if self._dim is None and embeddings:
            self._dim = len(embeddings[0])
            logger.info(f"[HunyuanEmbedding] Detected vector dimension: {self._dim}")
        return embeddings[0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError("embed_batch is async-only; use aembed()")

    async def aembed(self, texts: list[str]) -> list[list[float]]:
        """Async batch embed with retry and error handling."""
        import tenacity

        retry_policy = tenacity.retry(
            stop=tenacity.stop_after_attempt(self._max_retries),
            wait=tenacity.wait_exponential(multiplier=1, min=2, max=30),
            retry=tenacity.retry_if_exception_type((httpx.HTTPStatusError, httpx.ConnectError)),
        )

        @retry_policy
        async def _call_api():
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    self._api_url,
                    json={"input": texts, "model": self._model},
                    headers=self._headers(),
                )
                resp.raise_for_status()
                return resp.json()

        data = await _call_api()
        embeddings = [item["embedding"] for item in data["data"]]
        if self._dim is None and embeddings:
            self._dim = len(embeddings[0])
            logger.info(f"[HunyuanEmbedding] Detected vector dimension: {self._dim}")
        return embeddings

    def _get_sync(self) -> httpx.Client:
        """Return a reusable synchronous HTTP client."""
        if self._sync_client is None:
            self._sync_client = httpx.Client(timeout=self._timeout)
        return self._sync_client

    def dimension(self) -> int:
        if self._dim is None:
            return default_embedding_dimension()
        return self._dim

    async def aclose(self) -> None:
        """Close async client."""
        if self._async_client is not None:
            await self._async_client.aclose()
            self._async_client = None

    def close(self) -> None:
        """Close sync client."""
        if self._sync_client is not None:
            self._sync_client.close()
            self._sync_client = None

    async def __aenter__(self) -> "HunyuanEmbedding":
        return self

    async def __aexit__(self, *args) -> None:
        await self.aclose()

    def __enter__(self) -> "HunyuanEmbedding":
        return self

    def __exit__(self, *args) -> None:
        self.close()


# ── 向量客户端接口 ────────────────────────────────────────────────────────

@dataclass
class SearchResult:
    """检索结果"""
    id: str
    score: float
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class VectorRecord:
    """待写入记录"""
    id: str
    vector: list[float]
    payload: dict[str, Any] = field(default_factory=dict)


class VectorClient(ABC):
    """向量数据库操作接口"""

    @abstractmethod
    def connect(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def disconnect(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def create_collection(
        self,
        name: str,
        dimension: int,
        description: str = "",
        metric: str = "COSINE",
    ) -> bool:
        raise NotImplementedError

    @abstractmethod
    def upsert(self, collection: str, records: list[VectorRecord]) -> bool:
        raise NotImplementedError

    @abstractmethod
    def search(
        self,
        collection: str,
        query_vector: list[float],
        top_k: int = 10,
        filter_expr: Optional[str] = None,
    ) -> list[SearchResult]:
        raise NotImplementedError

    @abstractmethod
    def delete_collection(self, name: str) -> bool:
        raise NotImplementedError

    def search_by_text(
        self,
        collection: str,
        query_text: str,
        top_k: int = 10,
        filter_expr: Optional[str] = None,
        embedder: Optional[EmbeddingModelBase] = None,
    ) -> list[SearchResult]:
        if embedder is None:
            embedder = get_embedding_model()
        query_vector = embedder.embed(query_text)
        return self.search(collection, query_vector, top_k, filter_expr)


# ── Qdrant 实现 ────────────────────────────────────────────────────────────

class QdrantClient(VectorClient):
    """Qdrant 向量库客户端"""

    def __init__(
        self,
        url: str = "http://localhost:6333",
        api_key: str = "",
        collection_name: str = "qingshui",
    ):
        self._url = url
        self._api_key = api_key
        self._collection_name = collection_name
        self._connected = False
        import os as _os
        for _k in ("NO_PROXY", "no_proxy", "NOPROXY"):
            _os.environ[_k] = "localhost,127.0.0.1,::1"

    def connect(self) -> None:
        self._connected = True
        logger.info("Qdrant 连接: %s", self._url)

    def disconnect(self) -> None:
        self._connected = False

    def _ensure_connected(self) -> None:
        if not self._connected:
            self.connect()

    def create_collection(
        self,
        name: str,
        dimension: int,
        description: str = "",
        metric: str = "COSINE",
    ) -> bool:
        self._ensure_connected()
        try:
            import qdrant_client
            from qdrant_client.models import Distance, VectorParams

            client = qdrant_client.QdrantClient(url=self._url, api_key=self._api_key or None)
            if client.collection_exists(name):
                logger.info("Qdrant Collection 已存在: %s", name)
                return True
            distance_map = {"COSINE": Distance.COSINE, "EUCLID": Distance.EUCLID, "DOT": Distance.DOT}
            client.create_collection(
                collection_name=name,
                vectors_config=VectorParams(
                    size=dimension,
                    distance=distance_map.get(metric, Distance.COSINE),
                ),
            )
            logger.info("Qdrant Collection 创建成功: %s (dim=%d)", name, dimension)
            return True
        except ImportError:
            logger.warning("qdrant-client 未安装")
            return False
        except Exception as e:
            logger.warning("Qdrant Collection 创建失败 [%s]: %s", name, e)
            return False

    def upsert(self, collection: str, records: list[VectorRecord]) -> bool:
        self._ensure_connected()
        if not records:
            return True
        try:
            import qdrant_client
            from qdrant_client.models import PointStruct, Distance, VectorParams

            client = qdrant_client.QdrantClient(url=self._url, api_key=self._api_key or None)
            if not client.collection_exists(collection):
                dim = len(records[0].vector)
                client.create_collection(
                    collection_name=collection,
                    vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
                )
                logger.info("Qdrant Collection 创建: %s (dim=%d)", collection, dim)
            points = [
                PointStruct(id=r.id, vector=r.vector, payload=r.payload)
                for r in records
            ]
            client.upsert(collection_name=collection, points=points)
            logger.debug("Qdrant upsert 完成: %d 条", len(records))
            return True
        except Exception as e:
            logger.warning("Qdrant upsert 失败 [%s]: %s", collection, e)
            return False

    def search(
        self,
        collection: str,
        query_vector: list[float],
        top_k: int = 10,
        filter_expr: Optional[str] = None,
    ) -> list[SearchResult]:
        self._ensure_connected()
        try:
            import qdrant_client

            client = qdrant_client.QdrantClient(url=self._url, api_key=self._api_key or None)
            results = client.query_points(
                collection_name=collection,
                query=query_vector,
                limit=top_k,
                with_payload=True,
            )
            return [
                SearchResult(id=str(r.id), score=r.score, payload=r.payload or {})
                for r in results.points
            ]
        except Exception as e:
            logger.error(f"[RETRIEVE-FAIL] Qdrant search failed [{collection}]: {e}", exc_info=True)
            return []

    def delete_collection(self, name: str) -> bool:
        self._ensure_connected()
        try:
            import qdrant_client
            client = qdrant_client.QdrantClient(url=self._url, api_key=self._api_key or None)
            client.delete_collection(collection_name=name)
            logger.info("Qdrant Collection 已删除: %s", name)
            return True
        except Exception as e:
            logger.warning("Qdrant delete_collection 失败: %s", e)
            return False


# ── Collection 初始化 ───────────────────────────────────────────────────────

COLLECTION_ENTITIES  = "kg_entities"
COLLECTION_RELATIONS = "kg_relations"
COLLECTION_CHUNKS    = "doc_chunks"
COLLECTION_QA        = "qa_flash"


def init_collections(
    embedder: Optional[EmbeddingModelBase] = None,
) -> dict[str, bool]:
    if embedder is None:
        embedder = get_embedding_model()

    dim = embedder.dimension()
    client = QdrantClient(collection_name="qingshui")

    collections = {
        COLLECTION_ENTITIES:  "实体描述向量（entity_id + entity_name + description）",
        COLLECTION_RELATIONS: "关系描述向量（from_entity + to_entity + description）",
        COLLECTION_CHUNKS:    "文档分块向量（content + heading + source）",
        COLLECTION_QA:        "研报摘要向量（question + answer + source）",
    }

    results = {}
    for name, desc in collections.items():
        try:
            client.create_collection(name=name, dimension=dim, description=desc)
            results[name] = True
        except Exception as e:
            logger.warning("Collection 初始化失败 [%s]: %s", name, e)
            results[name] = False

    return results


# ── 快捷写入函数 ─────────────────────────────────────────────────────────

def upsert_entity_vector(
    entity_id: str,
    entity_name: str,
    description: str,
    entity_type: str = "",
    ts_code: str = "",
    collection: str = COLLECTION_ENTITIES,
) -> bool:
    """将实体描述写入向量库"""
    try:
        client = get_vector_client()
        embedder = get_embedding_model()
        vec = embedder.embed(f"{entity_name} {description}")
        point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, str(entity_id)))
        record = VectorRecord(
            id=point_id,
            vector=vec,
            payload={
                "entity_id": entity_id,
                "entity_name": entity_name,
                "description": description,
                "entity_type": entity_type,
                "ts_code": ts_code,
            },
        )
        return bool(client.upsert(collection, [record]))
    except Exception as e:
        logger.warning("upsert_entity_vector 失败: %s", e)
        return False


def upsert_relation_vector(
    relation_key: str,
    from_name: str,
    to_name: str,
    description: str,
    from_entity: str = "",
    to_entity: str = "",
    ts_code: str = "",
    collection: str = COLLECTION_RELATIONS,
) -> bool:
    """将关系描述写入向量库"""
    try:
        client = get_vector_client()
        embedder = get_embedding_model()
        vec = embedder.embed(f"{from_name} 与 {to_name}：{description}")
        point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, str(relation_key)))
        record = VectorRecord(
            id=point_id,
            vector=vec,
            payload={
                "from_entity": from_entity,
                "to_entity": to_entity,
                "from_name": from_name,
                "to_name": to_name,
                "description": description,
                "ts_code": ts_code,
            },
        )
        return bool(client.upsert(collection, [record]))
    except Exception as e:
        logger.warning("upsert_relation_vector 失败: %s", e)
        return False


def upsert_chunk_vector(
    chunk_id: str,
    content: str,
    heading: str = "",
    source: str = "",
    ts_code: str = "",
    collection: str = COLLECTION_CHUNKS,
) -> bool:
    """将文档分块写入向量库"""
    try:
        client = get_vector_client()
        embedder = get_embedding_model()
        text = f"{heading} {content}" if heading else content
        vec = embedder.embed(text)
        point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, str(chunk_id)))
        record = VectorRecord(
            id=point_id,
            vector=vec,
            payload={
                "content": content,
                "heading": heading,
                "source": source,
                "ts_code": ts_code,
            },
        )
        return bool(client.upsert(collection, [record]))
    except Exception as e:
        logger.warning("upsert_chunk_vector 失败: %s", e)
        return False


def upsert_evidence_chunk_vector(
    evidence: dict[str, Any],
    collection: str = COLLECTION_CHUNKS,
) -> bool:
    """将 Evidence 片段写入向量库。"""
    try:
        evidence_id = str(evidence.get("evidence_id") or "")
        text = str(evidence.get("text_excerpt") or "")
        if not evidence_id or not text.strip():
            logger.warning("upsert_evidence_chunk_vector 输入无效: evidence_id=%s", evidence_id)
            return False

        client = get_vector_client()
        embedder = get_embedding_model()
        vec = embedder.embed(text)
        point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, evidence_id))
        record = VectorRecord(
            id=point_id,
            vector=vec,
            payload={
                "evidence_id": evidence_id,
                "content": text,
                "source_type": evidence.get("source_type", ""),
                "source_name": evidence.get("source_name", ""),
                "subject_hint": evidence.get("subject_hint") or {},
                "source_ref": evidence.get("source_ref") or {},
                "publish_date": evidence.get("publish_date"),
                "observed_at": evidence.get("observed_at"),
                "checksum": evidence.get("checksum", ""),
            },
        )
        return bool(client.upsert(collection, [record]))
    except Exception as e:
        logger.warning("upsert_evidence_chunk_vector 失败: %s", e)
        return False


def semantic_search_entities(
    query: str,
    ts_code: Optional[str] = None,
    top_k: int = 5,
) -> list[SearchResult]:
    try:
        client = get_vector_client()
        embedder = get_embedding_model()
        filter_expr = f'ts_code == "{ts_code}"' if ts_code else None
        return client.search_by_text(
            collection=COLLECTION_ENTITIES,
            query_text=query,
            top_k=top_k,
            filter_expr=filter_expr,
            embedder=embedder,
        )
    except Exception as e:
        logger.warning("semantic_search_entities 失败: %s", e)
        return []


def semantic_search_chunks(
    query: str,
    ts_code: Optional[str] = None,
    top_k: int = 5,
) -> list[SearchResult]:
    try:
        client = get_vector_client()
        embedder = get_embedding_model()
        filter_expr = f'ts_code == "{ts_code}"' if ts_code else None
        return client.search_by_text(
            collection=COLLECTION_CHUNKS,
            query_text=query,
            top_k=top_k,
            filter_expr=filter_expr,
            embedder=embedder,
        )
    except Exception as e:
        logger.warning("semantic_search_chunks 失败: %s", e)
        return []
