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
    "get_market_snapshot",
    "data_readiness",
    # P0.5（2026-10-13）
    "get_announcement",
    "get_irm",
    "find_events",
    "get_event_detail",
    "scan_dimension",
    "backlinks",
    "get_top_concepts",
    "get_concept_stocks",
    "get_stock_concepts",
    "history_findings",
    "search_findings",
    "watermark",
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
        "write_observation",
        "write_finding",
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
        if resp.is_error:
            detail = " ".join((resp.text or "").split())[:400]
            raise RuntimeError(f"knowledge {method} {path} failed: {resp.status_code} {detail}")
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


async def get_market_snapshot(trade_date: str = "") -> dict[str, Any]:
    params = {"trade_date": trade_date} if trade_date else None
    return await knowledge_get("/api/v1/knowledge/market/snapshot", params=params)


async def data_readiness() -> dict[str, Any]:
    return await knowledge_get("/api/v1/readiness")


async def get_announcement(
    ts_code: str | None = None,
    keyword: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    page_size: int = 10,
) -> dict[str, Any]:
    return await knowledge_post(
        "/api/v1/knowledge/sources/announcement",
        {
            "ts_code": ts_code,
            "keyword": keyword,
            "start_date": start_date,
            "end_date": end_date,
            "page_size": page_size,
        },
    )


async def get_irm(
    ts_code: str | None = None,
    keyword: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    page_size: int = 20,
) -> dict[str, Any]:
    return await knowledge_post(
        "/api/v1/knowledge/sources/irm",
        {
            "ts_code": ts_code,
            "keyword": keyword,
            "start_date": start_date,
            "end_date": end_date,
            "page_size": page_size,
        },
    )


async def find_events(
    query: str | None = None,
    tags: list[str] | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    top_n: int = 10,
) -> dict[str, Any]:
    return await knowledge_post(
        "/api/v1/knowledge/sources/events",
        {
            "query": query,
            "tags": tags,
            "date_from": date_from,
            "date_to": date_to,
            "top_n": top_n,
        },
    )


async def get_event_detail(event_id: str) -> dict[str, Any]:
    return await knowledge_post("/api/v1/knowledge/sources/event_detail", {"event_id": event_id})


async def scan_dimension(
    dimension: str,
    scope: str | None = None,
    as_of: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    return await knowledge_post(
        "/api/v1/knowledge/links/scan_dimension",
        {"dimension": dimension, "scope": scope, "as_of": as_of, "limit": limit},
    )


async def backlinks(evidence_id: str) -> dict[str, Any]:
    return await knowledge_post("/api/v1/knowledge/links/backlinks", {"evidence_id": evidence_id})


async def get_top_concepts(days: int = 5, top_n: int = 10) -> dict[str, Any]:
    return await knowledge_post("/api/v1/knowledge/market/concept_top", {"days": days, "top_n": top_n})


async def get_concept_stocks(concept_code: str, sort_by: str = "volume", limit: int = 30) -> dict[str, Any]:
    return await knowledge_post(
        "/api/v1/knowledge/market/concept_stocks",
        {"concept_code": concept_code, "sort_by": sort_by, "limit": limit},
    )


async def get_stock_concepts(ts_code: str) -> dict[str, Any]:
    return await knowledge_post("/api/v1/knowledge/market/stock_concepts", {"ts_code": ts_code})


async def history_findings(
    subject: str,
    dimension: str | None = None,
    scope: str | None = None,
    before: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    return await knowledge_post(
        "/api/v1/knowledge/ledger/history",
        {
            "subject": subject,
            "dimension": dimension,
            "scope": scope,
            "before": before,
            "limit": limit,
        },
    )


async def search_findings(
    dimension: str | None = None,
    kind: str | None = None,
    status: str | None = None,
    since: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    return await knowledge_post(
        "/api/v1/knowledge/ledger/search",
        {
            "dimension": dimension,
            "kind": kind,
            "status": status,
            "since": since,
            "limit": limit,
        },
    )


async def watermark(
    subject_ts_code: str,
    dimension: str,
    dimension_scope: str | None = None,
) -> dict[str, Any]:
    return await knowledge_post(
        "/api/v1/knowledge/ledger/watermark",
        {"subject_ts_code": subject_ts_code, "dimension": dimension, "dimension_scope": dimension_scope},
    )


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
        """Stock OHLCV kline from local market DB.

        ts_code examples: 300308.SZ (A-share), NVDA (US), 2330.TW (Taiwan),
        005930.KS (Korea). Overseas symbols use Yahoo code format.
        """
        return _json_result(
            await get_kline(ts_code=ts_code, start_date=start_date, end_date=end_date, freq=freq)
        )

    @mcp.tool(name="get_market_snapshot")
    async def _get_market_snapshot(trade_date: str = "") -> str:
        """One session's breadth, two-market turnover, and major index closes.

        trade_date is YYYYMMDD; empty means the latest stock session.
        up/down/flat exclude rows whose stock name contains 指数.
        amount_yi is the sum of stock amount (千元) converted to 亿元.
        """
        return _json_result(await get_market_snapshot(trade_date))

    @mcp.tool(name="get_stock_profile")
    async def _get_stock_profile(ts_code: str) -> str:
        """Company main-business profile."""
        return _json_result(await get_stock_profile(ts_code))

    @mcp.tool(name="data_readiness")
    async def _data_readiness() -> str:
        """Freshness / readiness summary for data sources."""
        return _json_result(await data_readiness())

    # ── P0.5（2026-10-13）：源材料 / 维度扫描 / 概念面 / 台账读 ──────────────

    @mcp.tool(name="get_announcement")
    async def _get_announcement(
        ts_code: str | None = None,
        keyword: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        page_size: int = 10,
    ) -> str:
        """Search listed-company announcements (title-level; fetch_evidence for text).

        start_date and end_date accept YYYYMMDD or YYYY-MM-DD.
        """
        return _json_result(
            await get_announcement(
                ts_code=ts_code,
                keyword=keyword,
                start_date=start_date,
                end_date=end_date,
                page_size=page_size,
            )
        )

    @mcp.tool(name="get_irm")
    async def _get_irm(
        ts_code: str | None = None,
        keyword: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        page_size: int = 20,
    ) -> str:
        """Search 互动易 Q&A (investor-relations answers from listed companies).

        start_date and end_date accept YYYYMMDD or YYYY-MM-DD.
        A bad parameter is ignored. The result still returns, with note explaining what was dropped.
        """
        return _json_result(
            await get_irm(
                ts_code=ts_code,
                keyword=keyword,
                start_date=start_date,
                end_date=end_date,
                page_size=page_size,
            )
        )

    @mcp.tool(name="find_events")
    async def _find_events(
        query: str | None = None,
        tags: list[str] | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        top_n: int = 10,
    ) -> str:
        """Search industry news events (CLS/tushare); use get_event_detail for full text."""
        return _json_result(
            await find_events(query=query, tags=tags, date_from=date_from, date_to=date_to, top_n=top_n)
        )

    @mcp.tool(name="get_event_detail")
    async def _get_event_detail(event_id: str) -> str:
        """Fetch full text of a news event by id."""
        return _json_result(await get_event_detail(event_id))

    @mcp.tool(name="scan_dimension")
    async def _scan_dimension(
        dimension: str,
        scope: str | None = None,
        as_of: str | None = None,
        limit: int = 50,
    ) -> str:
        """Cross-subject scan of one dimension (latest value per subject)."""
        return _json_result(
            await scan_dimension(dimension=dimension, scope=scope, as_of=as_of, limit=limit)
        )

    @mcp.tool(name="backlinks")
    async def _backlinks(evidence_id: str) -> str:
        """All keywords on an evidence and co-occurring evidence per keyword."""
        return _json_result(await backlinks(evidence_id))

    @mcp.tool(name="get_top_concepts")
    async def _get_top_concepts(days: int = 5, top_n: int = 10) -> str:
        """Hottest THS concepts over recent trade days (decayed score)."""
        return _json_result(await get_top_concepts(days=days, top_n=top_n))

    @mcp.tool(name="get_concept_stocks")
    async def _get_concept_stocks(concept_code: str, sort_by: str = "volume", limit: int = 30) -> str:
        """Constituent stocks of a concept (TI code or name, e.g. 885806.TI / CPO)."""
        return _json_result(
            await get_concept_stocks(concept_code=concept_code, sort_by=sort_by, limit=limit)
        )

    @mcp.tool(name="get_stock_concepts")
    async def _get_stock_concepts(ts_code: str) -> str:
        """All concepts a stock belongs to."""
        return _json_result(await get_stock_concepts(ts_code))

    @mcp.tool(name="history_findings")
    async def _history_findings(
        subject: str,
        dimension: str | None = None,
        scope: str | None = None,
        before: str | None = None,
        limit: int = 50,
    ) -> str:
        """Ledger timeline for a subject×dimension: observations + findings + watermark."""
        return _json_result(
            await history_findings(
                subject=subject,
                dimension=dimension,
                scope=scope,
                before=before,
                limit=limit,
            )
        )

    @mcp.tool(name="search_findings")
    async def _search_findings(
        dimension: str | None = None,
        kind: str | None = None,
        status: str | None = None,
        since: str | None = None,
        limit: int = 50,
    ) -> str:
        """Cross-subject findings scan (kind: progression/regression/new_event/association/divergence)."""
        return _json_result(
            await search_findings(
                dimension=dimension,
                kind=kind,
                status=status,
                since=since,
                limit=limit,
            )
        )

    @mcp.tool(name="watermark")
    async def _watermark(
        subject_ts_code: str,
        dimension: str,
        dimension_scope: str | None = None,
    ) -> str:
        """Read (subject×dimension) watermark: historical max stage level."""
        return _json_result(
            await watermark(
                subject_ts_code=subject_ts_code,
                dimension=dimension,
                dimension_scope=dimension_scope,
            )
        )
