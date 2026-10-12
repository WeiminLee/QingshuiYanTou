"""P0 read-only MCP tool handlers. Prefer Knowledge HTTP; no write tools."""
from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx

from app.mcp_data.truncation import truncate_evidence_text

logger = logging.getLogger(__name__)

TOOL_NAMES: tuple[str, ...] = (
    "fetch_evidence",
    "semantic_search",
    "compare_metric",
    "pull_history",
    "lookup_players",
    "lookup_products",
    "get_kline",
    "get_stock_profile",
    "data_readiness",
)

# Names that must never appear in TOOL_NAMES (guardrail).
WRITE_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "claim_job",
        "upsert_evidence",
        "write_todos",
        "enqueue",
        "vector_upsert",
        "link_upsert",
    }
)


def knowledge_base_url() -> str:
    return os.environ.get("KNOWLEDGE_BASE_URL", "http://127.0.0.1:8000").rstrip("/")


def knowledge_api_key() -> str:
    from app.mcp_data.auth import expected_api_key

    return expected_api_key() or os.environ.get("KNOWLEDGE_API_KEY", "")


async def knowledge_request(
    method: str,
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    timeout: float = 60.0,
) -> Any:
    url = f"{knowledge_base_url()}{path}"
    headers = {"X-API-Key": knowledge_api_key(), "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.request(method, url, headers=headers, json=json_body, params=params)
        resp.raise_for_status()
        if not resp.content:
            return {}
        return resp.json()


async def knowledge_get(path: str, **kwargs: Any) -> Any:
    return await knowledge_request("GET", path, **kwargs)


async def knowledge_post(path: str, body: dict[str, Any], **kwargs: Any) -> Any:
    return await knowledge_request("POST", path, json_body=body, **kwargs)


async def fetch_evidence(evidence_id: str) -> dict[str, Any]:
    doc = await knowledge_get(f"/api/v1/knowledge/evidence/{evidence_id}")
    text = doc.get("text_excerpt", "") or ""
    doc = dict(doc)
    doc["text_excerpt"] = truncate_evidence_text(text)
    return doc


async def semantic_search(
    query: str,
    scope: str = "entities",
    ts_code: str | None = None,
    top_k: int = 5,
) -> dict[str, Any]:
    return await knowledge_post(
        "/api/v1/knowledge/search/semantic",
        {"query": query, "scope": scope, "ts_code": ts_code, "top_k": top_k},
    )


async def compare_metric(
    dimension: str,
    scope: str | None = None,
    as_of: str | None = None,
    top_k: int = 30,
) -> dict[str, Any]:
    # Prefer plan-path alias; fall back handled by HTTP existence.
    return await knowledge_post(
        "/api/v1/knowledge/metrics/compare",
        {"dimension": dimension, "scope": scope, "as_of": as_of, "top_k": top_k},
    )


async def pull_history(
    subject: str,
    dimension: str | None = None,
    scope: str | None = None,
    before: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    return await knowledge_post(
        "/api/v1/knowledge/links/history",
        {
            "subject": subject,
            "dimension": dimension,
            "scope": scope,
            "before": before,
            "limit": limit,
        },
    )


async def lookup_players(keyword_norm_text: str, top_k: int = 20) -> dict[str, Any]:
    return await knowledge_post(
        "/api/v1/knowledge/links/lookup_players",
        {"keyword_norm_text": keyword_norm_text, "top_k": top_k},
    )


async def lookup_products(company: str, top_k: int = 20) -> dict[str, Any]:
    return await knowledge_post(
        "/api/v1/knowledge/links/lookup_products",
        {"company": company, "top_k": top_k},
    )


async def get_kline(
    ts_code: str,
    start_date: str = "",
    end_date: str = "",
    freq: str = "D",
) -> dict[str, Any]:
    return await knowledge_get(
        "/api/v1/knowledge/market/kline",
        params={
            "ts_code": ts_code,
            "start_date": start_date,
            "end_date": end_date,
            "freq": freq,
        },
    )


async def get_stock_profile(ts_code: str) -> dict[str, Any]:
    return await knowledge_get(
        "/api/v1/knowledge/market/stock_profile",
        params={"ts_code": ts_code},
    )


async def data_readiness() -> dict[str, Any]:
    return await knowledge_get("/api/v1/readiness")


def _json_result(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str)


def register_tools(mcp: Any) -> None:
    """Register P0 tools on a FastMCP instance."""

    @mcp.tool(name="fetch_evidence")
    async def _fetch_evidence(evidence_id: str) -> str:
        """Fetch L1 evidence by id (EV:…); text truncated to 8k chars."""
        return _json_result(await fetch_evidence(evidence_id))

    @mcp.tool(name="semantic_search")
    async def _semantic_search(
        query: str,
        scope: str = "entities",
        ts_code: str | None = None,
        top_k: int = 5,
    ) -> str:
        """Semantic search over entities/chunks (embedding may be unavailable)."""
        return _json_result(await semantic_search(query, scope=scope, ts_code=ts_code, top_k=top_k))

    @mcp.tool(name="compare_metric")
    async def _compare_metric(
        dimension: str,
        scope: str | None = None,
        as_of: str | None = None,
        top_k: int = 30,
    ) -> str:
        """Cross-section metric compare for expected-gap analysis."""
        return _json_result(
            await compare_metric(dimension=dimension, scope=scope, as_of=as_of, top_k=top_k)
        )

    @mcp.tool(name="pull_history")
    async def _pull_history(
        subject: str,
        dimension: str | None = None,
        scope: str | None = None,
        before: str | None = None,
        limit: int = 100,
    ) -> str:
        """Timeline of evidence links for a subject×dimension."""
        return _json_result(
            await pull_history(
                subject=subject,
                dimension=dimension,
                scope=scope,
                before=before,
                limit=limit,
            )
        )

    @mcp.tool(name="lookup_players")
    async def _lookup_players(keyword_norm_text: str, top_k: int = 20) -> str:
        """Players (subjects) co-occurring with a product/keyword."""
        return _json_result(await lookup_players(keyword_norm_text, top_k=top_k))

    @mcp.tool(name="lookup_products")
    async def _lookup_products(company: str, top_k: int = 20) -> str:
        """Products/scopes co-occurring with a company subject."""
        return _json_result(await lookup_products(company, top_k=top_k))

    @mcp.tool(name="get_kline")
    async def _get_kline(
        ts_code: str,
        start_date: str = "",
        end_date: str = "",
        freq: str = "D",
    ) -> str:
        """Stock OHLCV kline from local market DB."""
        return _json_result(
            await get_kline(ts_code=ts_code, start_date=start_date, end_date=end_date, freq=freq)
        )

    @mcp.tool(name="get_stock_profile")
    async def _get_stock_profile(ts_code: str) -> str:
        """Company main-business profile."""
        return _json_result(await get_stock_profile(ts_code))

    @mcp.tool(name="data_readiness")
    async def _data_readiness() -> str:
        """Freshness / readiness summary for data sources."""
        return _json_result(await data_readiness())
