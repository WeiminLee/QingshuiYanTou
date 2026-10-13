"""Data MCP server entry.

Usage:
  python -m app.mcp_data.server --transport stdio
  python -m app.mcp_data.server --transport streamable-http --host 127.0.0.1 --port 8100
"""
from __future__ import annotations

import argparse
import logging

from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.types import ASGIApp, Receive, Scope, Send

from app.mcp_data.auth import validate_api_key
from app.mcp_data.tools_readonly import TOOL_NAMES, register_tools

logger = logging.getLogger(__name__)


def build_mcp(name: str = "qingshui-data") -> FastMCP:
    mcp = FastMCP(
        name,
        instructions=(
            "Qingshui YanTou read-only Data MCP. "
            f"P0 tools: {', '.join(TOOL_NAMES)}. No write/claim/enqueue."
        ),
        host="127.0.0.1",
        port=8100,
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
    )
    register_tools(mcp)
    return mcp


class ApiKeyMiddleware:
    """Require X-API-Key on MCP HTTP paths; /health is open."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path") or ""
        if path in ("/health", "/healthz"):
            await self.app(scope, receive, send)
            return
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers") or []}
        key = headers.get("x-api-key")
        if not validate_api_key(key):
            body = b'{"detail":"invalid api key"}'
            await send(
                {
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [(b"content-type", b"application/json")],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return
        await self.app(scope, receive, send)


async def health(_: Request) -> Response:
    return JSONResponse({"ok": True, "service": "qingshui-data-mcp", "tools": list(TOOL_NAMES)})


def build_http_app(mcp: FastMCP) -> Starlette:
    mcp_app = mcp.streamable_http_app()

    async def lifespan(app: Starlette):
        # Ensure session manager is started if FastMCP exposes it
        sm = getattr(mcp, "session_manager", None)
        if sm is not None and hasattr(sm, "run"):
            async with sm.run():
                yield
        else:
            yield

    app = Starlette(
        routes=[
            Route("/health", health, methods=["GET"]),
            Route("/healthz", health, methods=["GET"]),
            Mount("/", app=mcp_app),
        ],
        lifespan=lifespan,
    )
    return ApiKeyMiddleware(app)  # type: ignore[return-value]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Qingshui read-only Data MCP")
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default="stdio",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8100)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO)
    mcp = build_mcp()

    if args.transport == "stdio":
        mcp.run(transport="stdio")
        return

    if args.host not in ("127.0.0.1", "localhost", "::1"):
        logger.warning(
            "Binding %s — prefer 127.0.0.1 behind nginx with auth; open bind is discouraged",
            args.host,
        )

    import uvicorn

    # Rebuild with desired host/port on FastMCP for path defaults
    mcp = FastMCP(
        "qingshui-data",
        instructions=mcp.instructions,
        host=args.host,
        port=args.port,
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
    )
    register_tools(mcp)
    app = build_http_app(mcp)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
