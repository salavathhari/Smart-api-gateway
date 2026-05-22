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
from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from gateway.config import settings
from gateway.router import GatewayRouter
from gateway.connection_pool import ConnectionPoolManager
from gateway.logger import GatewayLogger
from gateway.database import db_manager
from gateway.auth import validate_token
from gateway.rate_limit import is_rate_limited
from gateway.circuit_breaker import circuit_breaker
from gateway.redis_client import redis_client
from gateway.load_balancer import LoadBalancer
from gateway.rate_limiter import RateLimiterManager



# ── Lifespan (startup / shutdown) ────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialise shared resources on startup; clean up on shutdown."""
    # Initialize HTTP pools
    app.state.pool_manager = ConnectionPoolManager()
    await app.state.pool_manager.startup()

    # Initialize DB & Redis
    await db_manager.connect()
    app.state.db = db_manager

    app.state.router = GatewayRouter(settings)
    app.state.logger = GatewayLogger()

    # Initialize rate limiter
    if settings.rate_limiter_enabled:
        app.state.rate_limiter = RateLimiterManager(
            algorithm=settings.rate_limiter_algorithm,
            rate=settings.rate_limiter_rate,
            capacity=settings.rate_limiter_capacity,
            window_seconds=settings.rate_limiter_window_seconds,
        )
        print("✅ Rate limiter initialized — protecting against abuse")
    else:
        app.state.rate_limiter = None
        print("⚠️  Rate limiter disabled")

    print("✅ Gateway started — connection pools ready")
    yield

    await db_manager.disconnect()
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


# ── Middleware: rate limiting ─────────────────────────────────────────────────

@app.middleware("http")
async def rate_limiting_middleware(request: Request, call_next):
    """
    Apply rate limiting per IP address.
    Returns 429 Too Many Requests if limit exceeded.
    Adds rate limit headers to all responses for observability.
    """
    rate_limiter: RateLimiterManager = request.app.state.rate_limiter
    client_ip = request.client.host if request.client else "unknown"
    state = {}
    
    # Determine if we should skip rate limiting for this path
    skip_rate_limit = request.url.path in ["/health", "/gateway/routes", "/gateway/metrics", "/gateway/ratelimit"]
    
    # Check rate limit only if enabled and not skipped
    if rate_limiter and settings.rate_limiter_enabled and not skip_rate_limit:
        # Check whitelist
        if client_ip not in settings.rate_limiter_whitelist:
            # Check rate limit
            allowed, state = await rate_limiter.check_limit(client_ip)
            
            if not allowed:
                print(
                    f"🚫 Rate limit exceeded for {client_ip}: "
                    f"{state.get('requests_made', 'N/A')}/{state.get('limit', 'N/A')} "
                    f"in {state.get('window_seconds', 'N/A')}s"
                )
                return JSONResponse(
                    status_code=429,
                    content={
                        "error": "rate_limit_exceeded",
                        "message": f"Too many requests. Limit: {settings.rate_limiter_rate} requests per {settings.rate_limiter_window_seconds} seconds",
                        "retry_after": settings.rate_limiter_window_seconds,
                        "client_ip": client_ip,
                    },
                )
    
    # Get rate limit state for headers (even for skipped endpoints)
    if not state and rate_limiter and settings.rate_limiter_enabled:
        _, state = await rate_limiter.check_limit(client_ip)
    
    # Process the request
    response = await call_next(request)
    
    # Add rate limit headers to all responses for observability
    if rate_limiter and settings.rate_limiter_enabled:
        response.headers["x-ratelimit-limit"] = str(settings.rate_limiter_rate)
        response.headers["x-ratelimit-remaining"] = str(max(0, state.get("tokens_remaining", state.get("requests_made", 0))))
        response.headers["x-ratelimit-reset"] = str(int(time.time()) + settings.rate_limiter_window_seconds)
    
    return response


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


@app.middleware("http")
async def gateway_logic_middleware(request: Request, call_next):
    """
    Combined Auth & Rate Limiting middleware.
    Decoupled from the proxy function so it applies to internal routes too.
    """
    path = request.url.path
    is_public = any(path.startswith(p) for p in settings.public_prefixes)
    
    # 1. Authentication
    user_payload = None
    if not is_public:
        try:
            user_payload = validate_token(request)
            if not user_payload:
                logger: GatewayLogger = request.app.state.logger
                elapsed_ms = (time.monotonic() - request.state.start_time) * 1000
                await logger.log(
                    request_id=request.state.request_id,
                    method=request.method,
                    path=request.url.path,
                    service="AUTH",
                    upstream="NONE",
                    status=401,
                    latency_ms=elapsed_ms,
                    error="unauthorized"
                )
                return JSONResponse(
                    status_code=401,
                    content={"error": "unauthorized", "message": "Authentication required"}
                )
            # Store payload for potential downstream use (in request.state)
            request.state.user = user_payload
        except HTTPException as e:
            return JSONResponse(status_code=e.status_code, content={"error": "auth_failed", "message": e.detail})

    # 2. Rate Limiting
    client_ip = request.client.host if request.client else "unknown"
    limit_key = user_payload.get("sub") if user_payload else client_ip
    
    is_limited, remaining = await is_rate_limited(
        limit_key, 
        settings.rate_limit_requests, 
        settings.rate_limit_window
    )
    
    if is_limited:
        return JSONResponse(
            status_code=429,
            content={"error": "too_many_requests", "message": "Rate limit exceeded"}
        )

    # 3. Proceed to route or proxy
    response = await call_next(request)
    
    # 4. Inject rate limit headers
    if remaining != -1:
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        
    return response


# ── Health check ──────────────────────────────────────────────────────────────

@app.get("/health", tags=["Gateway"])
async def health_check(request: Request):
    logger: GatewayLogger = request.app.state.logger
    elapsed_ms = (time.monotonic() - request.state.start_time) * 1000
    await logger.log(
        request_id=request.state.request_id,
        method="GET",
        path="/health",
        service="GATEWAY",
        upstream="INTERNAL",
        status=200,
        latency_ms=elapsed_ms
    )
    return {"status": "ok", "service": "smart-api-gateway", "phase": 3}



@app.get("/gateway/routes", tags=["Gateway"])
async def list_routes(request: Request):
    """Return the current routing table so you can inspect it at runtime."""
    router: GatewayRouter = request.app.state.router
    return {"routes": router.describe()}

@app.get("/dashboard/logs", tags=["Monitoring"])
async def get_logs(limit: int = 100):
    """Retrieve structured logs from MongoDB (Day 7)."""
    try:
        if db_manager.db is None:
            return JSONResponse(
                status_code=503,
                content={"error": "database_unavailable", "message": "MongoDB not connected"}
            )
        
        # Fetch latest logs, hide _id for JSON serialization
        cursor = db_manager.db.logs.find({}, {"_id": 0}).sort("ts", -1).limit(limit)
        logs = await cursor.to_list(length=limit)
        return {"total": len(logs), "logs": logs}
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": "fetch_failed", "message": str(e)}
        )


@app.get("/gateway/debug", tags=["Gateway"])
async def debug_status(request: Request):
    """Detailed health check including DB and Redis status."""
    db_ok = False
    redis_ok = False
    
    try:
        # Check MongoDB connection
        await db_manager.client.admin.command('ping')
        db_ok = True
    except:
        db_ok = False

    try:
        if db_manager.redis:
            await db_manager.redis.ping()
            redis_ok = True
    except:
        redis_ok = False

    return {
        "gateway": "ok",
        "database": "connected (MongoDB)" if db_ok else "unavailable",
        "redis": "connected" if redis_ok else "unavailable",
        "config": {
            "environment": settings.environment,
            "port": settings.gateway_port
        }
    }


@app.get("/gateway/cache-test", tags=["Gateway"])
async def cache_test():
    """Simple test to verify Redis is connected."""
    if not db_manager.redis:
        return JSONResponse(
            status_code=503,
            content={"error": "redis_unavailable", "message": "Redis client not initialized"}
        )
    
    try:
        uid = str(uuid.uuid4())[:8]
        await db_manager.redis.set(f"test:{uid}", "working", ex=10)
        val = await db_manager.redis.get(f"test:{uid}")
        return {"redis": "ok", "value": val, "key": f"test:{uid}"}
    except Exception as e:
        return JSONResponse(
            status_code=503,
            content={"error": "redis_error", "message": str(e)}
        )

@app.get("/gateway/ratelimit", tags=["Gateway"])
async def get_ratelimit_info(request: Request):
    """Return rate limiting configuration and status."""
    if not settings.rate_limiter_enabled:
        return {
            "enabled": False,
            "message": "Rate limiting is disabled",
        }

    client_ip = request.client.host if request.client else "unknown"
    rate_limiter = request.app.state.rate_limiter

    # Check current status for this IP
    _, state = await rate_limiter.check_limit(client_ip)

    return {
        "enabled": True,
        "algorithm": settings.rate_limiter_algorithm,
        "rate": f"{settings.rate_limiter_rate} requests per {settings.rate_limiter_window_seconds} seconds",
        "capacity": settings.rate_limiter_capacity,
        "window_seconds": settings.rate_limiter_window_seconds,
        "whitelist": settings.rate_limiter_whitelist,
        "current_client": {
            "ip": client_ip,
            "status": state,
        },
    }


# ── Catch-all proxy ───────────────────────────────────────────────────────────

@app.api_route(
    "/{full_path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
    tags=["Proxy"],
)
async def proxy(request: Request, full_path: str):
    """
    Core reverse-proxy handler with Redis caching.
    Delegates forward to targeted service.
    """
    router: GatewayRouter = request.app.state.router
    pool_manager: ConnectionPoolManager = request.app.state.pool_manager
    logger: GatewayLogger = request.app.state.logger
    redis = db_manager.redis

    try:
        # 1. Route resolution
        upstream_url, service_name = router.resolve(request.url.path)
        if upstream_url is None:
            # Log resolution failure
            elapsed_ms = (time.monotonic() - request.state.start_time) * 1000
            await logger.log(
                request_id=request.state.request_id,
                method=request.method,
                path=request.url.path,
                service="NONE",
                upstream="NONE",
                status=404,
                latency_ms=elapsed_ms,
                error="no_route"
            )
            return JSONResponse(
                status_code=404,
                content={
                    "error": "no_route",
                    "message": f"No upstream configured for path: /{full_path}",
                    "path": f"/{full_path}",
                },
            )

        # 2. Cache Lookup (GET only)
        has_cache = settings.cache_enabled and request.method in settings.cacheable_methods and redis
        cache_key = f"cache:{request.method}:{request.url.path}:{request.url.query}"
        
        if has_cache:
            cached_res = await redis.get(cache_key)
            if cached_res:
                data = json.loads(cached_res)
                # Log cache hit
                elapsed_ms = (time.monotonic() - request.state.start_time) * 1000
                await logger.log(
                    request_id=request.state.request_id,
                    method=request.method,
                    path=f"/{full_path}",
                    service=service_name,
                    upstream="CACHED",
                    status=data["status"],
                    latency_ms=elapsed_ms,
                )
                return Response(
                    content=data["content"],
                    status_code=data["status"],
                    headers={**data["headers"], "X-Cache": "HIT"},
                    media_type=data["headers"].get("content-type"),
                )

        # 2.5 Circuit Breaker
        if not circuit_breaker.allow_request(service_name):
            return JSONResponse(
                status_code=503,
                content={
                    "error": "service_unavailable",
                    "message": f"Circuit breaker is open for service: {service_name}",
                    "retry_after": settings.circuit_breaker_recovery_timeout
                }
            )

        # 3. Forward the request (with retries)
        last_error = None
        for attempt in range(settings.max_retries + 1):
            try:
                client: httpx.AsyncClient = pool_manager.get_client(service_name)

                # Re-assemble query string
                target_url = upstream_url
                if request.url.query:
                    target_url = f"{upstream_url}?{request.url.query}"

                body = await request.body()
                user_payload = getattr(request.state, "user", None)

                # Copy headers; strip hop-by-hop headers
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
                headers["X-Retry-Attempt"] = str(attempt)

                # Inject user context if authenticated (passed from middleware)
                if user_payload:
                    headers["X-User-ID"] = str(user_payload.get("sub", ""))
                    headers["X-User-Roles"] = ",".join(user_payload.get("roles", []))

                upstream_response = await client.request(
                    method=request.method,
                    url=target_url,
                    headers=headers,
                    content=body,
                    timeout=settings.request_timeout,
                )

                # Record success for circuit breaker
                if upstream_response.status_code < 500:
                    circuit_breaker.record_success(service_name)
                else:
                    circuit_breaker.record_failure(service_name)

                # 4. Return upstream response (strip hop-by-hop response headers)
                excluded_response_headers = {"transfer-encoding", "connection"}
                response_headers = {
                    k: v
                    for k, v in upstream_response.headers.items()
                    if k.lower() not in excluded_response_headers
                }
                response_headers["X-Cache"] = "MISS"

                # 5. Save to Cache if applicable
                if has_cache and upstream_response.status_code == 200:
                    cache_data = {
                        "content": upstream_response.text,
                        "status": upstream_response.status_code,
                        "headers": dict(response_headers)
                    }
                    await redis.set(cache_key, json.dumps(cache_data), ex=settings.cache_ttl)

                # 6. Log success
                elapsed_ms = (time.monotonic() - request.state.start_time) * 1000
                await logger.log(
                    request_id=request.state.request_id,
                    method=request.method,
                    path=request.url.path,
                    service=service_name,
                    upstream=upstream_url,
                    status=upstream_response.status_code,
                    latency_ms=elapsed_ms,
                )

                return Response(
                    content=upstream_response.content,
                    status_code=upstream_response.status_code,
                    headers=response_headers,
                    media_type=upstream_response.headers.get("content-type"),
                )

            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                last_error = exc
                circuit_breaker.record_failure(service_name)
                
                if attempt < settings.max_retries:
                    wait_time = settings.retry_backoff_factor * (2 ** attempt)
                    print(f"⚠️ Request failed ({exc}). Retrying in {wait_time}s... (Attempt {attempt+1}/{settings.max_retries})")
                    await asyncio.sleep(wait_time)
                    continue
                
                # If all retries fail
                status_code = 502 if isinstance(exc, httpx.ConnectError) else 504
                error_type = "upstream_unreachable" if isinstance(exc, httpx.ConnectError) else "upstream_timeout"
                
                # Log failure
                elapsed_ms = (time.monotonic() - request.state.start_time) * 1000
                await logger.log(
                    request_id=request.state.request_id,
                    method=request.method,
                    path=f"/{full_path}",
                    service=service_name,
                    upstream=upstream_url,
                    status=status_code,
                    latency_ms=elapsed_ms,
                    error=str(exc)
                )

                return JSONResponse(
                    status_code=status_code,
                    content={
                        "error": error_type,
                        "service": service_name,
                        "detail": str(exc),
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
