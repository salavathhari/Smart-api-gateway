"""
Tests for Phase 1 — Core Gateway
Run: pytest tests/ -v

Router tests: pure Python unit tests.
Integration tests: Starlette TestClient (handles lifespan, synchronous but correct).
Logger tests: async unit tests.
"""

import asyncio
import pytest
from starlette.testclient import TestClient

from gateway.router import GatewayRouter
from gateway.config import Settings


# ─────────────────────────────────────────────────────────────────────────────
# Fixture — full app with lifespan (app.state populated)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def gateway():
    from gateway.main import app
    with TestClient(app) as client:
        yield client


# ─────────────────────────────────────────────────────────────────────────────
# Fixture — redis cleanup for async tests
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
async def redis_cleanup():
    """Clean up Redis after each async test."""
    yield
    # Flush the test data after test
    from gateway.redis_client import redis_client
    try:
        await redis_client.flushdb()
    except Exception:
        pass  # Redis may not be available, that's ok


# ─────────────────────────────────────────────────────────────────────────────
# Router unit tests
# ─────────────────────────────────────────────────────────────────────────────

class TestGatewayRouter:
    def _router(self) -> GatewayRouter:
        s = Settings(
            auth_service_url="http://auth:9001",
            chat_service_url="http://chat:9002",
            ai_service_url="http://ai:9003",
        )
        return GatewayRouter(s)

    def test_resolves_auth(self):
        url, svc = self._router().resolve("/auth/login")
        assert svc == "auth" and url == "http://auth:9001/auth/login"

    def test_resolves_chat(self):
        url, svc = self._router().resolve("/chat/rooms")
        assert svc == "chat" and url == "http://chat:9002/chat/rooms"

    def test_resolves_ai(self):
        url, svc = self._router().resolve("/ai/complete")
        assert svc == "ai" and url == "http://ai:9003/ai/complete"

    def test_unknown_returns_none(self):
        url, svc = self._router().resolve("/unknown/path")
        assert url is None and svc is None

    def test_root_returns_none(self):
        assert self._router().resolve("/") == (None, None)

    def test_preserves_deep_path(self):
        url, _ = self._router().resolve("/auth/user/profile/avatar")
        assert url == "http://auth:9001/auth/user/profile/avatar"

    def test_describe_has_all_routes(self):
        prefixes = [r["prefix"] for r in self._router().describe()]
        assert {"/auth", "/chat", "/ai"}.issubset(prefixes)

    def test_dynamic_route_add(self):
        r = self._router()
        r.add_route("/metrics", "metrics", "http://metrics:9099")
        url, svc = r.resolve("/metrics/cpu")
        assert svc == "metrics" and url == "http://metrics:9099/metrics/cpu"

    def test_longest_prefix_wins(self):
        r = self._router()
        r.add_route("/a", "short", "http://short:9099")
        _, svc = r.resolve("/auth/me")
        assert svc == "auth"


# ─────────────────────────────────────────────────────────────────────────────
# Integration tests (lifespan active via TestClient)
# ─────────────────────────────────────────────────────────────────────────────

def test_health_endpoint(gateway):
    resp = gateway.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert resp.json()["phase"] == 3


def test_gateway_routes_endpoint(gateway):
    resp = gateway.get("/gateway/routes")
    assert resp.status_code == 200
    prefixes = [r["prefix"] for r in resp.json()["routes"]]
    assert "/auth" in prefixes and "/chat" in prefixes


def test_unknown_route_404(gateway):
    resp = gateway.get("/unknown/endpoint")
    assert resp.status_code == 404
    assert resp.json()["error"] == "no_route"


def test_request_id_header(gateway):
    resp = gateway.get("/health")
    assert "x-request-id" in resp.headers


def test_response_time_header(gateway):
    resp = gateway.get("/health")
    assert "x-response-time" in resp.headers
    assert resp.headers["x-response-time"].endswith("ms")


# ─────────────────────────────────────────────────────────────────────────────
# Logger unit tests
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_logger_buffers():
    from gateway.logger import GatewayLogger
    logger = GatewayLogger()
    await logger.log(
        request_id="x1", method="GET", path="/auth/me",
        service="auth", upstream="http://localhost:9001/auth/me",
        status=200, latency_ms=12.5,
    )
    assert len(logger.recent(10)) == 1


@pytest.mark.asyncio
async def test_logger_stats():
    from gateway.logger import GatewayLogger
    logger = GatewayLogger()
    for i in range(5):
        await logger.log(
            request_id=f"r{i}", method="GET", path="/chat/rooms",
            service="chat", upstream="http://localhost:9002/chat/rooms",
            status=500 if i == 4 else 200, latency_ms=10.0,
        )
    stats = logger.stats()
    assert stats["total"] == 5
    assert stats["errors"] == 1
    assert stats["by_service"]["chat"] == 5


# ─────────────────────────────────────────────────────────────────────────────
# Rate Limiter unit tests
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_token_bucket_allows_requests_within_limit():
    """Token bucket should allow requests within the limit."""
    from gateway.rate_limiter import TokenBucketRateLimiter
    limiter = TokenBucketRateLimiter(rate=5, capacity=5, window_seconds=1)
    
    # First 5 requests should be allowed
    for i in range(5):
        allowed, state = await limiter.is_allowed("ip1")
        assert allowed is True


@pytest.mark.asyncio
async def test_token_bucket_denies_requests_over_limit(redis_cleanup):
    """Token bucket should deny requests exceeding capacity."""
    from gateway.rate_limiter import TokenBucketRateLimiter
    limiter = TokenBucketRateLimiter(rate=5, capacity=5, window_seconds=1)
    
    # Use all 5 tokens
    for i in range(5):
        await limiter.is_allowed("ip1")
    
    # 6th request should be denied
    allowed, state = await limiter.is_allowed("ip1")
    assert allowed is False


@pytest.mark.asyncio
async def test_token_bucket_different_ips_independent():
    """Different IPs should have independent token buckets."""
    from gateway.rate_limiter import TokenBucketRateLimiter
    limiter = TokenBucketRateLimiter(rate=5, capacity=5, window_seconds=1)
    
    # Use all tokens for ip1
    for i in range(5):
        await limiter.is_allowed("ip1")
    
    # ip2 should still have tokens available
    allowed, state = await limiter.is_allowed("ip2")
    assert allowed is True


@pytest.mark.asyncio
async def test_sliding_window_allows_requests_within_limit():
    """Sliding window should allow requests within the limit."""
    from gateway.rate_limiter import SlidingWindowRateLimiter
    limiter = SlidingWindowRateLimiter(limit=5, window_seconds=1)
    
    # First 5 requests should be allowed
    for i in range(5):
        allowed, state = await limiter.is_allowed("ip1")
        assert allowed is True


@pytest.mark.asyncio
async def test_sliding_window_denies_requests_over_limit(redis_cleanup):
    """Sliding window should deny requests exceeding limit."""
    from gateway.rate_limiter import SlidingWindowRateLimiter
    limiter = SlidingWindowRateLimiter(limit=5, window_seconds=1)
    
    # Use all 5 requests
    for i in range(5):
        await limiter.is_allowed("ip1")
    
    # 6th request should be denied
    allowed, state = await limiter.is_allowed("ip1")
    assert allowed is False


@pytest.mark.asyncio
async def test_rate_limiter_manager_token_bucket():
    """Rate limiter manager should use token bucket algorithm."""
    from gateway.rate_limiter import RateLimiterManager
    
    manager = RateLimiterManager(
        algorithm="token_bucket",
        rate=3,
        capacity=3,
        window_seconds=1
    )
    
    # 3 requests allowed - use unique identifier to avoid Redis pollution
    unique_id = "manager_token_test"
    for i in range(3):
        allowed, state = await manager.check_limit(unique_id)
        assert allowed is True
    
    # 4th denied
    allowed, state = await manager.check_limit(unique_id)
    assert allowed is False


@pytest.mark.asyncio
async def test_rate_limiter_manager_sliding_window():
    """Rate limiter manager should use sliding window algorithm."""
    from gateway.rate_limiter import RateLimiterManager
    
    manager = RateLimiterManager(
        algorithm="sliding_window",
        rate=3,
        capacity=3,
        window_seconds=1
    )
    
    # 3 requests allowed - use unique identifier to avoid Redis pollution
    unique_id = "manager_sliding_test"
    for i in range(3):
        allowed, state = await manager.check_limit(unique_id)
        assert allowed is True
    
    # 4th denied
    allowed, state = await manager.check_limit(unique_id)
    assert allowed is False


# ─────────────────────────────────────────────────────────────────────────────
# Rate Limiter integration tests
# ─────────────────────────────────────────────────────────────────────────────

def test_health_endpoint_phase_3(gateway):
    """Health endpoint should report phase 3."""
    resp = gateway.get("/health")
    assert resp.status_code == 200
    assert resp.json()["phase"] == 3


def test_ratelimit_info_endpoint(gateway):
    """Gateway should expose rate limit configuration."""
    resp = gateway.get("/gateway/ratelimit")
    assert resp.status_code == 200
    data = resp.json()
    assert data["enabled"] is True
    assert "algorithm" in data
    assert "rate" in data


def test_ratelimit_info_includes_client_ip(gateway):
    """Rate limit info should include current client IP."""
    resp = gateway.get("/gateway/ratelimit")
    assert resp.status_code == 200
    data = resp.json()
    assert "current_client" in data
    assert "ip" in data["current_client"]
    assert "status" in data["current_client"]


def test_rate_limit_headers_on_response(gateway):
    """Proxied responses should include rate limit headers."""
    resp = gateway.get("/health")
    assert "x-ratelimit-limit" in resp.headers
    assert "x-ratelimit-remaining" in resp.headers
    assert "x-ratelimit-reset" in resp.headers
