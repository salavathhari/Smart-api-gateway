"""
Smart API Gateway - Phase 1: Core Reverse Proxy
Entry point for the FastAPI gateway server.
"""

import asyncio
import time
import uuid
from contextlib import asynccontextmanager

import httpx
import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from gateway.config import settings
from gateway.router import GatewayRouter
from gateway.connection_pool import ConnectionPoolManager
from gateway.logger import GatewayLogger


# ── Lifespan (startup / shutdown) ────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialise shared resources on startup; clean up on shutdown."""
    app.state.pool_manager = ConnectionPoolManager()
    await app.state.pool_manager.startup()

    app.state.router = GatewayRouter(settings)
    app.state.logger = GatewayLogger()

    print("✅ Gateway started — connection pools ready")
    yield

    await app.state.pool_manager.shutdown()
    print("🛑 Gateway shut down — pools closed")


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Smart API Gateway",
    description="Phase 1 — Core reverse proxy with async forwarding & connection pooling",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Middleware: request tracing ───────────────────────────────────────────────

@app.middleware("http")
async def request_tracing_middleware(request: Request, call_next):
    """Attach a unique request-ID and measure latency for every request."""
    request_id = str(uuid.uuid4())[:8]
    request.state.request_id = request_id
    request.state.start_time = time.monotonic()

    # Inject tracing header so downstream services can correlate logs
    request.headers.__dict__["_list"].append(
        (b"x-request-id", request_id.encode())
    )

    response = await call_next(request)

    elapsed_ms = (time.monotonic() - request.state.start_time) * 1000
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Response-Time"] = f"{elapsed_ms:.2f}ms"
    return response


# ── Health check ──────────────────────────────────────────────────────────────

@app.get("/health", tags=["Gateway"])
async def health_check():
    return {"status": "ok", "service": "smart-api-gateway", "phase": 1}


@app.get("/gateway/routes", tags=["Gateway"])
async def list_routes(request: Request):
    """Return the current routing table so you can inspect it at runtime."""
    router: GatewayRouter = request.app.state.router
    return {"routes": router.describe()}


# ── Catch-all proxy ───────────────────────────────────────────────────────────

@app.api_route(
    "/{full_path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
    tags=["Proxy"],
)
async def proxy(request: Request, full_path: str):
    """
    Core reverse-proxy handler.

    Steps
    -----
    1. Resolve the upstream URL from the routing table.
    2. Pick the right HTTP client from the connection pool.
    3. Stream the response back to the caller.
    4. Log the transaction.
    """
    router: GatewayRouter = request.app.state.router
    pool_manager: ConnectionPoolManager = request.app.state.pool_manager
    logger: GatewayLogger = request.app.state.logger

    # 1. Route resolution
    upstream_url, service_name = router.resolve(request.url.path)
    if upstream_url is None:
        return JSONResponse(
            status_code=404,
            content={
                "error": "no_route",
                "message": f"No upstream configured for path: /{full_path}",
                "path": f"/{full_path}",
            },
        )

    # 2. Forward the request
    try:
        client: httpx.AsyncClient = pool_manager.get_client(service_name)

        # Re-assemble query string
        target_url = upstream_url
        if request.url.query:
            target_url = f"{upstream_url}?{request.url.query}"

        body = await request.body()

        # Copy headers; strip hop-by-hop headers that must not be forwarded
        headers = {
            k: v
            for k, v in request.headers.items()
            if k.lower()
            not in {
                "host",
                "content-length",
                "transfer-encoding",
                "connection",
                "keep-alive",
                "upgrade",
                "proxy-authenticate",
                "proxy-authorization",
                "te",
                "trailers",
            }
        }
        headers["X-Forwarded-For"] = request.client.host if request.client else "unknown"
        headers["X-Forwarded-Host"] = request.headers.get("host", "gateway")
        headers["X-Gateway-Service"] = service_name

        upstream_response = await client.request(
            method=request.method,
            url=target_url,
            headers=headers,
            content=body,
            timeout=settings.request_timeout,
        )

        # 3. Log
        elapsed_ms = (time.monotonic() - request.state.start_time) * 1000
        await logger.log(
            request_id=request.state.request_id,
            method=request.method,
            path=f"/{full_path}",
            service=service_name,
            upstream=upstream_url,
            status=upstream_response.status_code,
            latency_ms=elapsed_ms,
        )

        # 4. Return upstream response (strip hop-by-hop response headers too)
        excluded_response_headers = {"transfer-encoding", "connection"}
        response_headers = {
            k: v
            for k, v in upstream_response.headers.items()
            if k.lower() not in excluded_response_headers
        }

        return Response(
            content=upstream_response.content,
            status_code=upstream_response.status_code,
            headers=response_headers,
            media_type=upstream_response.headers.get("content-type"),
        )

    except httpx.ConnectError as exc:
        return JSONResponse(
            status_code=502,
            content={
                "error": "upstream_unreachable",
                "service": service_name,
                "detail": str(exc),
            },
        )
    except httpx.TimeoutException:
        return JSONResponse(
            status_code=504,
            content={
                "error": "upstream_timeout",
                "service": service_name,
                "timeout_seconds": settings.request_timeout,
            },
        )
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=500,
            content={"error": "gateway_error", "detail": str(exc)},
        )


# ── Dev runner ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run(
        "gateway.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
